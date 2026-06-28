#!/usr/bin/env python3
"""
summarize.py  (Summarize — the OPTIONAL AI summary step, multi-provider)

Classify each cluster bundle with an ADOS-grounded ontology (Primary Archetype +
Primary Domain/Subdomain Pair) and fill only the archetype-conditioned prose
fields. Deterministic facts (dates, version zips, file artifacts, member ids,
signals) are copied from clusters.json and merged OVER the model output — the
model never owns them.

Providers: ollama (local, $0) | openai | anthropic (API, token-exact) |
cursor | codex | claude (local CLI, billed against your signed-in plan/quota).
Cost is estimated before any paid call and gated by --max-usd; a circuit breaker
stops the run on repeated failures or budget breach. All calls are traced to a
JSONL ledger.

Usage:
  python scripts/summarize.py --provider ollama --model gpt-oss:20b
  python scripts/summarize.py --provider openai --model gpt-5-mini --max-usd 2 --yes
  python scripts/summarize.py --run-label modeltest --limit 5 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
import interrupt  # noqa: E402
import ulog  # noqa: E402
import paths  # noqa: E402
import run_log  # noqa: E402
import cost as cost_lib  # noqa: E402
import confirm  # noqa: E402
import provider_detect  # noqa: E402
import models_bank  # noqa: E402
import redact  # noqa: E402
import power as power_lib  # noqa: E402
from trace import TraceWriter, sha256_text, write_json, validate_with_jsonschema  # noqa: E402
from providers import get_provider, ProviderError, CLOUD_PROVIDERS  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from classify import load_ontology, classify_cluster  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Deterministic facts the model must never author; merged over its output.
DETERMINISTIC_KEYS = (
    "item_id", "slug", "start_date", "end_date", "n_conversations", "n_passes",
    "version_zip_files", "file_artifacts", "source_conversation_ids",
    "signal_summary",
)


def build_system_prompt(ontology: dict) -> str:
    arches = ontology["archetypes"]["archetypes"]
    domains = ontology["domains"]["domains"]
    arch_lines = "\n".join(
        f"  - {a['id']}: {a['label']} — {a['when_to_use']} "
        f"[fields: {', '.join(a['field_contract'].keys())}]"
        for a in arches
    )
    dom_lines = "\n".join(
        f"  - {d['id']}: {d['label']}"
        + (f" (subdomains: {', '.join(d['subdomains'])})" if d.get("subdomains") else "")
        for d in domains
    )
    return (
        "You classify and summarize one extracted item from reduced chat "
        "transcripts, using the ADOS controlled vocabulary. Output ONLY a single "
        "JSON object. Be terse and factual.\n\n"
        "ADOS DEFINITIONS:\n"
        "- ARCHETYPE = what reusable KIND of thing is delivered. It is NOT a "
        "domain, a file extension, or a tool stack. Pick exactly ONE "
        "primary_archetype. Add secondary_archetypes only for distinct material "
        "contribution.\n"
        "- DOMAIN/SUBDOMAIN PAIR = what body of knowledge governs correctness and "
        "evidence. Pick exactly ONE primary_domain_pair.\n"
        "- GOAL = the durable target state in one sentence.\n"
        "- OBJECTIVE role = forming (shapes the delivery), speeding (route "
        "efficiency), or governance (traceability/validation/control).\n"
        "- is_durable_project = true if it spans multiple Passes/versions; false "
        "for a one-off interaction.\n\n"
        "DRIFT GUARDS (obey strictly):\n"
        "1. Incidental code does NOT make the item software_app — ask what is "
        "DELIVERED.\n"
        "2. Do NOT pick the Primary Archetype from the most visible single file.\n"
        "3. Do NOT pick 'software_engineering' as the Primary Domain just because "
        "software implements the product (e.g. an SAT app is Primary Domain "
        "education/sat_preparation, Primary Archetype software_app; "
        "software_engineering is at most Secondary).\n"
        "4. Drop any Domain/Subdomain whose label changes no correctness, "
        "evidence, risk, or vocabulary (materiality test).\n"
        "5. Never invent file names, versions, or dates — those are supplied "
        "separately and merged over your output.\n\n"
        "CONTROLLED ARCHETYPES (use these ids):\n" + arch_lines + "\n\n"
        "CONTROLLED DOMAINS (use these ids):\n" + dom_lines + "\n\n"
        "Fill archetype_fields with EXACTLY the keys listed for your chosen "
        "primary_archetype above. Use empty string/array if unknown."
    )


OUTPUT_SHAPE = (
    "{\n"
    '  "title": str, "description": str, "is_durable_project": bool,\n'
    '  "primary_archetype": {"id": str, "label": str, "rationale": str},\n'
    '  "secondary_archetypes": [{"id": str, "distinct_contribution": str}],\n'
    '  "primary_domain_pair": {"domain": str, "subdomain": str|null, "rationale": str},\n'
    '  "secondary_domain_pairs": [{"domain": str, "subdomain": str|null, "distinct_contribution": str}],\n'
    '  "confidence": number,\n'
    '  "goal": str,\n'
    '  "objectives": [{"text": str, "role": "forming|speeding|governance"}],\n'
    '  "requirements": [str],\n'
    '  "requirements_evolution": [{"date": str|null, "change": str}],\n'
    '  "deliveries": [{"name": str, "materiality": "material|supporting", "kind": str}],\n'
    '  "archetype_fields": { ...keys from the chosen archetype contract... }\n'
    "}"
)


def _eta(elapsed_secs: float, n_done: int, n_remaining: int) -> str:
    """Project remaining wall time from the running per-item average."""
    if n_done <= 0 or n_remaining <= 0:
        return "done" if n_remaining <= 0 else "—"
    avg = elapsed_secs / n_done
    return confirm.format_duration(avg * n_remaining)


def parse_json_object(raw: str) -> dict | None:
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        obj = None
    if obj is None:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            try:
                obj = json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                obj = None
    return obj if isinstance(obj, dict) else None


def complete_with_retry(provider, system_prompt: str, prompt: str,
                        max_parse_retries: int, on_retry=None):
    """Call the provider with structured output, retrying on a parse miss (FR-B4).

    Returns (parsed | None, in_tok, out_tok, attempts, provider_err, timing).
    `timing` is a dict of server-reported milliseconds {load_ms, eval_ms,
    prompt_eval_ms, total_ms} summed across attempts (load is paid once, on the
    first/cold call; retries are warm). A parse miss (model returned non-JSON)
    triggers up to `max_parse_retries` extra requests; a transport ProviderError
    stops immediately. Tokens accumulate across all attempts so cost accounting
    stays honest."""
    parsed: dict | None = None
    in_tok = out_tok = 0
    provider_err = ""
    attempts = 0
    timing = {"load_ms": 0.0, "eval_ms": 0.0, "prompt_eval_ms": 0.0, "total_ms": 0.0}
    for attempt in range(1, max(0, max_parse_retries) + 2):
        attempts = attempt
        try:
            text, usage = provider.complete(system_prompt, prompt, json_mode=True)
        except ProviderError as e:
            provider_err = str(e)
            break
        in_tok += usage.input_tokens
        out_tok += usage.output_tokens
        timing["load_ms"] += getattr(usage, "load_ms", 0.0)
        timing["eval_ms"] += getattr(usage, "eval_ms", 0.0)
        timing["prompt_eval_ms"] += getattr(usage, "prompt_eval_ms", 0.0)
        timing["total_ms"] += getattr(usage, "total_ms", 0.0)
        parsed = parse_json_object(text)
        if parsed is not None:
            break
        if attempt <= max_parse_retries and on_retry is not None:
            on_retry(attempt)
    return parsed, in_tok, out_tok, attempts, provider_err, timing


def archetype_contract(ontology: dict, arch_id: str) -> dict:
    for a in ontology["archetypes"]["archetypes"]:
        if a["id"] == arch_id:
            return a["field_contract"]
    return {}


def ensure_archetype_fields(fields: dict, contract: dict) -> dict:
    """Guarantee every contract key is present (empty default), enforcing the
    archetype field contract regardless of LLM omissions."""
    out = dict(fields) if isinstance(fields, dict) else {}
    for key, meaning in contract.items():
        if key not in out or out[key] in (None, ""):
            out[key] = [] if str(meaning).startswith("array:") else out.get(key, "")
    return out


# Controlled enums from schema/extracted_item_schema.json. Smaller models often
# emit "" or null for these OPTIONAL fields; the schema only accepts an enum
# member or the field's absence, so we drop empties/invalids rather than write
# values that fail validation.
OBJECTIVE_ROLES = {"forming", "speeding", "governance"}
DELIVERY_MATERIALITY = {"material", "supporting"}


def _nonempty_str(value) -> str | None:
    """Return a stripped string, or None when the value is missing/blank."""
    if isinstance(value, str):
        s = value.strip()
        return s or None
    return None


def _as_obj(value) -> dict:
    """Coerce a model-supplied field to a dict. Weak models sometimes emit a
    bare string/list where the schema expects an object (e.g.
    "primary_archetype": "software_app"); treat anything non-dict as absent so
    the deterministic prior fills in rather than the run crashing."""
    return value if isinstance(value, dict) else {}


def _as_text(value) -> str:
    """Coerce a model-supplied field to a plain string (drop non-strings)."""
    return value.strip() if isinstance(value, str) else ""


def _as_list(value) -> list:
    """Coerce a model-supplied field to a list (anything else → empty), so the
    cleaners never iterate a stray string/int/dict character-by-character."""
    return value if isinstance(value, list) else []


def _clean_objectives(objectives) -> list[dict]:
    """objectives[].text is required; role is an optional enum (drop if invalid)."""
    out: list[dict] = []
    for o in _as_list(objectives):
        if not isinstance(o, dict):
            continue
        text = _nonempty_str(o.get("text"))
        if not text:
            continue
        obj: dict = {"text": text}
        role = _nonempty_str(o.get("role"))
        if role and role.lower() in OBJECTIVE_ROLES:
            obj["role"] = role.lower()
        out.append(obj)
    return out


def _clean_deliveries(deliveries) -> list[dict]:
    """deliveries[].name is required; materiality (enum) and kind (string) are
    optional — drop them when blank/invalid instead of emitting ''/null."""
    out: list[dict] = []
    for d in _as_list(deliveries):
        if not isinstance(d, dict):
            continue
        name = _nonempty_str(d.get("name"))
        if not name:
            continue
        deliv: dict = {"name": name}
        materiality = _nonempty_str(d.get("materiality"))
        if materiality and materiality.lower() in DELIVERY_MATERIALITY:
            deliv["materiality"] = materiality.lower()
        kind = _nonempty_str(d.get("kind"))
        if kind:
            deliv["kind"] = kind
        out.append(deliv)
    return out


def _clean_requirements(requirements) -> list[str]:
    return [r.strip() for r in _as_list(requirements)
            if isinstance(r, str) and r.strip()]


def _clean_requirements_evolution(items) -> list[dict]:
    """requirements_evolution[].change is required; date may be string or null."""
    out: list[dict] = []
    for r in _as_list(items):
        if not isinstance(r, dict):
            continue
        change = _nonempty_str(r.get("change"))
        if not change:
            continue
        out.append({"date": _nonempty_str(r.get("date")), "change": change})
    return out


def _clean_secondary_archetypes(items) -> list[dict]:
    """secondary_archetypes[].id is required."""
    out: list[dict] = []
    for s in _as_list(items):
        if not isinstance(s, dict):
            continue
        sid = _nonempty_str(s.get("id"))
        if not sid:
            continue
        entry: dict = {"id": sid}
        dc = _nonempty_str(s.get("distinct_contribution"))
        if dc:
            entry["distinct_contribution"] = dc
        out.append(entry)
    return out


def _clean_domain_pairs(items) -> list[dict]:
    """secondary_domain_pairs[].domain is required; subdomain is string|null."""
    out: list[dict] = []
    for s in _as_list(items):
        if not isinstance(s, dict):
            continue
        domain = _nonempty_str(s.get("domain"))
        if not domain:
            continue
        entry: dict = {"domain": domain, "subdomain": _nonempty_str(s.get("subdomain"))}
        for key in ("rationale", "distinct_contribution"):
            val = _nonempty_str(s.get(key))
            if val:
                entry[key] = val
        out.append(entry)
    return out


def _clamp_confidence(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def raw_schema_valid(parsed: dict | None) -> bool:
    """True when the model's raw JSON already carries the core schema shape
    (clean, schema-conformant output) BEFORE any coercion to the deterministic
    prior. Distinct from llm_ok (= parseable JSON returned): a model can return
    parseable JSON that is missing required structure and still need coercion.
    Reasoning/instruct models that wrap or malform JSON fail this; coder models
    that emit clean schema JSON pass it. Drives the schema-valid column in
    `gpt metrics` (FR-B2)."""
    if not isinstance(parsed, dict):
        return False
    pa = parsed.get("primary_archetype")
    if not (isinstance(pa, dict) and _nonempty_str(pa.get("id"))):
        return False
    pdp = parsed.get("primary_domain_pair")
    if not (isinstance(pdp, dict) and _nonempty_str(pdp.get("domain"))):
        return False
    if not isinstance(parsed.get("goal"), str):
        return False
    for key in ("objectives", "requirements"):
        if not isinstance(parsed.get(key, []), list):
            return False
    if not isinstance(parsed.get("archetype_fields", {}), dict):
        return False
    return True


def build_item(cluster: dict, parsed: dict, ontology: dict,
               provider: str, model: str, bundle_hash: str,
               item_cost_usd: float, llm_ok: bool = True,
               schema_valid: bool = False) -> dict:
    prior = cluster.get("classify_prior") or classify_cluster(cluster)
    pa = _as_obj(parsed.get("primary_archetype"))
    pa_id = _nonempty_str(pa.get("id")) or prior["primary_archetype"]["id"]
    contract = archetype_contract(ontology, pa_id)
    pdp = _as_obj(parsed.get("primary_domain_pair")) or prior["primary_domain_pair"]

    return {
        # --- LLM-owned classification + meaning ---
        "item_id": cluster["slug"],
        "slug": cluster["slug"],
        "title": _as_text(parsed.get("title")) or cluster["slug"],
        "description": _as_text(parsed.get("description")),
        "version": (cluster.get("version_zip_files") or [{}])[-1].get("version")
        if cluster.get("version_zip_files") else None,
        "is_durable_project": bool(parsed.get(
            "is_durable_project", cluster.get("n_versions", 0) >= 1)),
        "primary_archetype": {
            "id": pa_id,
            "label": _as_text(pa.get("label")),
            "rationale": _as_text(pa.get("rationale")),
        },
        "secondary_archetypes": _clean_secondary_archetypes(
            parsed.get("secondary_archetypes")),
        "primary_domain_pair": {
            "domain": _nonempty_str(pdp.get("domain")) or "general_knowledge",
            "subdomain": _nonempty_str(pdp.get("subdomain")),
            "rationale": _as_text(pdp.get("rationale")),
        },
        "secondary_domain_pairs": _clean_domain_pairs(
            parsed.get("secondary_domain_pairs")),
        "confidence": _clamp_confidence(parsed.get("confidence", 0.0)),
        "goal": _as_text(parsed.get("goal")),
        "objectives": _clean_objectives(parsed.get("objectives")),
        "requirements": _clean_requirements(parsed.get("requirements")),
        "requirements_evolution": _clean_requirements_evolution(
            parsed.get("requirements_evolution")),
        "deliveries": _clean_deliveries(parsed.get("deliveries")),
        "archetype_fields": ensure_archetype_fields(
            parsed.get("archetype_fields"), contract),
        # --- deterministic facts (copied verbatim, merged OVER model) ---
        "start_date": cluster.get("start_date"),
        "end_date": cluster.get("end_date"),
        "n_conversations": cluster.get("n_conversations", 0),
        "n_passes": cluster.get("n_passes", cluster.get("n_versions", 0)),
        "version_zip_files": cluster.get("version_zip_files", []),
        "file_artifacts": cluster.get("file_artifacts", []),
        "source_conversation_ids": cluster.get("member_ids", []),
        "signal_summary": cluster.get("signal_summary", {}),
        # --- provenance + honest failure recording (FR-B5 / NFR-Q4) ---
        # llm_ok distinguishes a real LLM record from a deterministic-prior
        # fallback; schema_valid records whether the model's raw JSON was clean.
        # `gpt metrics` excludes fallbacks from depth-on-success using these.
        "provider": provider,
        "model": model,
        "cost_usd": round(item_cost_usd, 6),
        "bundle_sha": bundle_hash,
        "llm_ok": bool(llm_ok),
        "classification_source": "llm" if llm_ok else "deterministic_prior",
        "schema_valid": bool(schema_valid),
    }


def build_prompt(cluster: dict, truncated: str, ontology: dict) -> str:
    prior = cluster.get("classify_prior") or classify_cluster(cluster)
    pa_id = prior["primary_archetype"]["id"]
    contract = archetype_contract(ontology, pa_id)
    return (
        f"Deterministic classification PRIOR (confirm or OVERRIDE with reason):\n"
        f"  candidate primary_archetype = {pa_id}\n"
        f"  candidate primary_domain_pair = {prior['primary_domain_pair']}\n"
        f"  archetype_fields keys if you keep this archetype: "
        f"{list(contract.keys())}\n\n"
        f"Emit a JSON object with this shape:\n{OUTPUT_SHAPE}\n\n"
        f"Bundle (deterministic facts + reduced transcripts) for slug "
        f"'{cluster['slug']}':\n\n{truncated}"
    )


# --- batching: classify many items in one provider call --------------------
# The system prompt (the full ADOS ontology, ~5.8k chars) is sent on every
# per-item call, so for small bundles it dominates input. Packing N items into
# one call sends the ontology once and amortizes per-call CLI/startup latency —
# measured ~2.5x faster and ~65% fewer input tokens on real bundles, with
# identical schema-validity. Robustness is preserved: any item the batch does
# not return cleanly falls back to its normal per-item call (see main loop).

# Per-item framing overhead (chars) added on top of the bundle when estimating
# whether another item still fits under --batch-max-chars.
_BATCH_ITEM_OVERHEAD = 400


def build_batch_prompt(chunk: list[tuple[dict, str, str]],
                       ontology: dict) -> str:
    """One prompt asking the model to classify every item in `chunk` and return
    a single JSON object keyed by slug (each value uses OUTPUT_SHAPE)."""
    slugs = [c["slug"] for c, _t, _h in chunk]
    parts: list[str] = []
    for c, truncated, _h in chunk:
        prior = c.get("classify_prior") or classify_cluster(c)
        pa_id = prior["primary_archetype"]["id"]
        contract = archetype_contract(ontology, pa_id)
        parts.append(
            f'### ITEM slug="{c["slug"]}"\n'
            f"  candidate primary_archetype = {pa_id}\n"
            f"  candidate primary_domain_pair = {prior['primary_domain_pair']}\n"
            f"  archetype_fields keys if you keep this archetype: "
            f"{list(contract.keys())}\n"
            f"  bundle:\n{truncated}\n")
    return (
        f"Classify EACH of the following {len(chunk)} items INDEPENDENTLY. "
        f"For every item produce a JSON object with this shape:\n{OUTPUT_SHAPE}\n\n"
        f"Return ONE JSON object whose keys are EXACTLY these item slugs:\n"
        f"{slugs}\n"
        f"and whose values are the per-item JSON objects. Classify each item on "
        f"its own evidence; never merge or cross-reference items.\n\n"
        + "\n".join(parts))


def split_batch_result(parsed, slugs: list[str]) -> dict[str, dict]:
    """From a parsed batched object, return {slug: obj} for the slugs that came
    back as a usable dict. Missing/malformed slugs are simply absent, so the
    caller can fall back to a per-item call for them."""
    out: dict[str, dict] = {}
    if isinstance(parsed, dict):
        for slug in slugs:
            v = parsed.get(slug)
            if isinstance(v, dict):
                out[slug] = v
    return out


def chunk_work(work: list[tuple[dict, str, str]], batch_size: int,
               batch_max_chars: int, sys_len: int):
    """Yield lists of work items, at most `batch_size` each and bounded so the
    batch prompt (system + items) stays under `batch_max_chars`. A single item
    larger than the budget still ships alone (it would be truncated anyway)."""
    chunk: list[tuple[dict, str, str]] = []
    chunk_chars = sys_len
    for item in work:
        item_chars = len(item[1]) + _BATCH_ITEM_OVERHEAD
        if chunk and (len(chunk) >= batch_size
                      or chunk_chars + item_chars > batch_max_chars):
            yield chunk
            chunk, chunk_chars = [], sys_len
        chunk.append(item)
        chunk_chars += item_chars
    if chunk:
        yield chunk


def prefetch_batches(provider, system_prompt: str,
                     work: list[tuple[dict, str, str]], ontology: dict, *,
                     batch_size: int, batch_max_chars: int,
                     max_parse_retries: int, trace, skip: set[str]
                     ) -> dict[str, tuple]:
    """Run batched provider calls and return a map
    {slug: (parsed, in_tok, out_tok, timing, secs)} for items that came back
    usable. The batch's tokens/time are attributed across the slugs that parsed,
    by bundle char-share (the run-level estimate already gates total spend, so
    this is honest at the ledger total; per-item is approximate). Items absent
    from the result fall back to the per-item path, so batching never reduces
    robustness below the per-item baseline."""
    out: dict[str, tuple] = {}
    pending = [w for w in work if w[0]["slug"] not in skip]
    sys_len = len(system_prompt)
    for chunk in chunk_work(pending, batch_size, batch_max_chars, sys_len):
        slugs = [c["slug"] for c, _t, _h in chunk]
        prompt = build_batch_prompt(chunk, ontology)
        t0 = time.time()
        parsed, in_tok, out_tok, _attempts, err, timing = complete_with_retry(
            provider, system_prompt, prompt, max_parse_retries,
            on_retry=lambda a, _s=slugs: trace.event(
                "BATCH_RETRY", ",".join(_s), {"attempt": a}, severity="WARN"))
        secs = time.time() - t0
        by_slug = split_batch_result(parsed, slugs)
        if not by_slug:
            trace.event("BATCH_MISS", ",".join(slugs),
                        {"error": (err or "no slugs parsed")[:200]},
                        severity="WARN")
            continue
        char_by = {c["slug"]: len(t) for c, t, _h in chunk
                   if c["slug"] in by_slug}
        tot = sum(char_by.values()) or 1
        for slug in by_slug:
            share = char_by[slug] / tot
            out[slug] = (
                by_slug[slug],
                int(in_tok * share), int(out_tok * share),
                {k: v * share for k, v in timing.items()},
                secs * share,
            )
        trace.event("BATCH_OK", ",".join(by_slug),
                    {"n": len(by_slug), "of": len(slugs),
                     "secs": round(secs, 1), "in_tok": in_tok,
                     "out_tok": out_tok})
    return out


def main() -> int:
    cfg = paths.load_config()
    ollama_cfg = cfg.get("ollama") or {}
    default_host = ollama_cfg.get("host", "http://localhost:11434")
    default_model = ollama_cfg.get("model", "gpt-oss:20b")
    default_num_ctx = int(ollama_cfg.get("num_ctx", 32768))
    default_max_chars = int(cfg.get("char_budget_per_bundle", 48000))

    ap = argparse.ArgumentParser(
        description="Summarize (optional AI step, multi-provider): classify + "
                    "summarize each project with an ADOS ontology. "
                    "Deterministic facts merged over.")
    ap.add_argument("--provider", default=None,
                    choices=["ollama", "openai", "anthropic", "cursor",
                             "codex", "claude"],
                    help="LLM provider. Default: auto-detect the first available "
                         "of codex -> ollama -> claude. "
                         "cursor/codex/claude use your CLI's signed-in plan.")
    ap.add_argument("--model", default=None,
                    help="Model name/tag. If --provider is omitted, the provider "
                         "and required options are resolved from the model bank "
                         "(config/models.json). See `--list-models`.")
    ap.add_argument("--list-models", action="store_true",
                    help="Print the model bank (every model you can pass to "
                         "--model, with its provider) and exit.")
    ap.add_argument("--host", default=None, help="Ollama host (ollama only).")
    ap.add_argument("--num-ctx", type=int, default=None, help="Ollama context window.")
    ap.add_argument("--run-label", default=None,
                    help="Optional: read/write under runs/<label>/. Omit for "
                         "default paths at data root. Use 'latest' for the "
                         "most recent labeled run.")
    ap.add_argument("--store", default=None)
    ap.add_argument("--bundles", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--max-chars", type=int, default=None)
    ap.add_argument("--min-versions", type=int, default=1,
                    help="Only summarize clusters with >= N version zips (default 1; 0=all).")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true",
                    help="Print cost estimate + prompt sizes; zero LLM calls.")
    ap.add_argument("--yes", "--noask", dest="noask", action="store_true",
                    help="Skip the time/cost confirmation prompt before the AI summary.")
    ap.add_argument("--max-usd", type=float, default=None,
                    help="Hard budget cap; run aborts before exceeding it.")
    ap.add_argument("--max-usd-per-item", type=float, default=None)
    ap.add_argument("--max-consecutive-failures", type=int, default=3)
    ap.add_argument("--max-parse-retries", type=int, default=1,
                    help="On a parse miss (model returned non-JSON), re-request "
                         "this many times before recording an honest failure "
                         "(FR-B4). Default 1. Set 0 to disable retries.")
    ap.add_argument("--batch-size", type=int, default=1,
                    help="Classify up to N items per provider call (1=per-item, "
                         "the default). Batching sends the ontology system "
                         "prompt once and amortizes CLI startup, so it is "
                         "markedly faster + cheaper for the subscription CLIs "
                         "(codex/claude). Any item the batch does not return "
                         "cleanly falls back to its own per-item call. Keep at 1 "
                         "for local Ollama unless num-ctx is large enough.")
    ap.add_argument("--batch-max-chars", type=int, default=120000,
                    help="Upper bound on a batch's total prompt chars so it "
                         "never overflows the model context; items beyond the "
                         "cap start a new batch (only used when --batch-size>1).")
    ap.add_argument("--meter-power", action="store_true",
                    help="Meter GPU power (nvidia-smi power.draw) during the run "
                         "and write a power trace, so `gpt metrics` can report "
                         "measured Wh/item (FR-B6). No-op without nvidia-smi.")
    ap.add_argument("--scrub-cloud", action="store_true",
                    help="Cloud pre-send scrubber (NFR-P3): redact emails, home "
                         "paths, phones, and tokens from each bundle BEFORE "
                         "sending it to a cloud provider (cursor/codex/claude/"
                         "openai/anthropic). Local Ollama is offline and exempt.")
    ap.add_argument("--no-preflight", action="store_true")
    ap.add_argument("--no-validate", action="store_true",
                    help="Skip jsonschema validation of the output.")
    ap.add_argument("--resume", action="store_true",
                    help="Reuse items already in the output JSON (matching "
                         "bundle hash) and only summarize the rest. Output is "
                         "saved after every item, so a killed run can resume "
                         "from where it stopped.")
    args = ap.parse_args()

    ulog.set_stage("Summarize")

    # No arguments (or --list-models): show the model bank and exit. This makes
    # `gpt summarize` a discoverable menu — pick a row and run it by name.
    if args.list_models or len(sys.argv) <= 1:
        sys.stderr.write(models_bank.format_bank(cfg=cfg) + "\n")
        return 0

    # Resolve --model against the bank when --provider is omitted, so a model
    # name alone is enough (provider + options come from the bank).
    bank_entry = None
    if args.model:
        bank_entry = models_bank.resolve(args.model, cfg=cfg)

    provider_name = args.provider
    if provider_name is None and bank_entry is not None:
        provider_name = bank_entry["provider"]
        ulog.log("BANK", args.model,
                 status=f"provider '{provider_name}' (from model bank)")
        if bank_entry.get("ambiguous"):
            ulog.log("BANK", args.model,
                     status=f"name also under {bank_entry['ambiguous']}; "
                            f"using '{provider_name}' (pass --provider to override)")
    elif provider_name is None and args.model:
        # Named a model we don't recognize and gave no provider — fail loudly
        # rather than auto-detecting a provider that ignores the model name.
        sys.stderr.write(models_bank.format_bank(cfg=cfg) + "\n")
        ap.error(f"--model '{args.model}' is not in the model bank and is not an "
                 f"installed Ollama model. Pick a model from the list above, "
                 f"pass --provider explicitly, or add it to config/models.json.")

    if provider_name is None:
        provider_name, notes = provider_detect.detect_provider(cfg=cfg)
        for line in notes:
            ulog.log("DETECT", "provider", status=line)
        if provider_name is None:
            ulog.err("DETECT", "provider",
                     error="no provider available. Install/sign in to codex, "
                           "ollama, or claude (see README), or pass --provider.")
            return 1
        ulog.log("DETECT", "provider", status=f"using {provider_name}")

    model = args.model or (default_model if provider_name == "ollama" else "")
    # CLI providers default to the model their signed-in plan selects.
    cli_optional_model = ("cursor", "codex", "claude")
    if not model and provider_name not in cli_optional_model:
        ap.error(f"--model is required for provider '{provider_name}'.")

    run_label = paths.resolve_run_label(args.run_label)
    if args.run_label == "latest" and not run_label:
        ap.error("No runs/latest pointer — pass --store/--bundles, an explicit "
                 "--run-label, or run the build steps with a label first.")
    bank_num_ctx = bank_entry.get("num_ctx") if bank_entry else None
    bank_host = bank_entry.get("host") if bank_entry else None
    num_ctx = (args.num_ctx if args.num_ctx is not None
               else bank_num_ctx if bank_num_ctx is not None
               else default_num_ctx)
    max_chars = args.max_chars if args.max_chars is not None else default_max_chars

    store = paths.store_dir(args.store, run_label=run_label)
    bundles = paths.bundles_dir(args.bundles, run_label=run_label)
    out_path = paths.reconstructed_json(args.out, run_label=run_label)
    root = paths.run_data_root(store=store, run_label=run_label)

    ontology = load_ontology()
    ontology_version = ontology["archetypes"].get("version", "?")
    system_prompt = build_system_prompt(ontology)
    pricing = cost_lib.load_pricing()

    # --- load + filter clusters ---
    cpath = os.path.join(store, "clusters.json")
    try:
        with open(cpath, encoding="utf-8") as f:
            clusters = json.load(f)
    except OSError as e:
        ulog.err("READ", cpath, error=e)
        return 1
    clusters = [c for c in clusters
                if c.get("n_versions", 0) >= args.min_versions
                or c.get("n_conversations", 0) >= 2]
    if args.limit > 0:
        clusters = clusters[: args.limit]
    # Ensure each cluster has a deterministic prior.
    for c in clusters:
        c.setdefault("classify_prior", classify_cluster(c))
    ulog.log("FILTER", cpath, status=f"{len(clusters)} items to summarize")

    # Cloud pre-send scrubber gate (NFR-P3): only cloud providers leave the
    # machine, so only they are scrubbed; local Ollama stays raw + offline.
    scrub_cloud = args.scrub_cloud and provider_name in CLOUD_PROVIDERS
    if args.scrub_cloud and provider_name not in CLOUD_PROVIDERS:
        ulog.log("SCRUB", provider_name,
                 status="local/offline provider — pre-send scrub not needed")
    elif scrub_cloud:
        ulog.log("SCRUB", provider_name,
                 status="cloud pre-send scrubber ON — bundles redacted before send")

    # --- gather bundle sizes for cost estimate ---
    work: list[tuple[dict, str, str]] = []   # (cluster, truncated_bundle, hash)
    bundle_chars: list[int] = []
    scrub_hits = 0
    for c in clusters:
        bpath = os.path.join(bundles, f"{c['slug']}.md")
        if not os.path.exists(bpath):
            continue
        with open(bpath, encoding="utf-8") as f:
            bundle = f.read()
        if scrub_cloud:
            bundle, findings = redact.scrub(bundle)
            scrub_hits += len(findings)
        truncated = bundle if len(bundle) <= max_chars else \
            bundle[:max_chars] + "\n[...truncated...]"
        prompt_chars = len(system_prompt) + len(build_prompt(c, truncated, ontology))
        bundle_chars.append(prompt_chars)
        work.append((c, truncated, sha256_text(truncated)))
    if scrub_cloud:
        ulog.log("SCRUB", out_path,
                 status=f"redacted {scrub_hits} PII match(es) across "
                        f"{len(work)} bundle(s) before any cloud call")

    est = cost_lib.estimate_run(pricing, provider_name, model or "*", bundle_chars)
    sys.stderr.write(cost_lib.format_estimate(est) + "\n")

    if args.dry_run:
        for c, _t, _h in work:
            ulog.log("DRY-RUN", c["slug"],
                     status=f"prior={c['classify_prior']['primary_archetype']['id']}")
        ulog.log("DRY-RUN", out_path, status=f"would summarize {len(work)} items")
        return 0

    # --- hard budget cap (independent of the interactive gate) ---
    if est["est_usd"] > 0 and args.max_usd is not None \
            and est["est_usd"] > args.max_usd:
        ulog.err("BUDGET", out_path,
                 error=f"estimate ${est['est_usd']:.2f} exceeds --max-usd "
                       f"${args.max_usd:.2f}. Raise the cap or use --limit.")
        return 1

    # --- confirmation gate (time and/or cost; all providers) ---
    subscription = bool(
        pricing.get("providers", {}).get(provider_name, {}).get("subscription")
        or pricing.get("providers", {}).get(provider_name, {}).get("usage_based"))
    if not confirm.gate(provider_name, model, len(work),
                        est_usd=est["est_usd"], subscription=subscription,
                        noask=args.noask):
        ulog.log("GATE", out_path, status="declined; nothing summarized")
        return 3

    # --- provider preflight ---
    prov_kwargs: dict = {"model": model, "timeout": args.timeout}
    if provider_name == "ollama":
        prov_kwargs.update(host=args.host or bank_host or default_host,
                           num_ctx=num_ctx)
    provider = get_provider(provider_name, **prov_kwargs)
    if not args.no_preflight:
        ok, msg = provider.preflight()
        if not ok:
            ulog.err("PREFLIGHT", provider_name, error=msg)
            return 1
        ulog.log("PREFLIGHT", provider_name, status=f"model={model or '(default)'}")

    run_log.append_command(" ".join(["summarize"] + sys.argv[1:]), root)
    run_log.stage_start("summarize", root)

    ledger = cost_lib.CostLedger(pricing=pricing)
    breaker = cost_lib.CircuitBreaker(
        max_consecutive_failures=args.max_consecutive_failures,
        max_usd=args.max_usd, max_usd_per_item=args.max_usd_per_item)
    trace = TraceWriter(os.path.join(root, "summarize_trace.jsonl"),
                        run_id=f"{provider_name}:{model}")

    items: list[dict] = []
    failed: list[str] = []
    skipped_breaker: list[str] = []

    # --- resume: reuse items already summarized for an unchanged bundle ---
    done: dict[str, dict] = {}
    if args.resume and os.path.exists(out_path):
        try:
            with open(out_path, encoding="utf-8") as f:
                prev = json.load(f)
            for it in prev.get("items", []):
                if it.get("slug") and it.get("bundle_sha"):
                    done[it["slug"]] = it
            ulog.log("RESUME", out_path,
                     status=f"{len(done)} item(s) already summarized")
        except (OSError, json.JSONDecodeError) as e:
            ulog.err("RESUME", out_path, error=f"ignoring prior output ({e})")

    total = len(work)
    interrupt.set_total(total, unit="items")
    in_tok_total = out_tok_total = 0
    proc_secs = 0.0          # wall time across freshly-summarized items
    n_processed = 0          # freshly-summarized items (for the running ETA)

    # Optional GPU power metering for the keep-vs-return economics (FR-B6).
    power_trace_path = os.path.join(root, "power_trace.jsonl")
    meter = power_lib.PowerMeter(power_trace_path) if args.meter_power else None
    if meter is not None:
        meter.__enter__()
        ulog.log("POWER", power_trace_path,
                 status=("metering GPU power.draw" if meter.available
                         else "nvidia-smi not found; power metering skipped"))

    # --- batch prefetch: classify many items per call, then the per-item loop
    # consumes the cached results (and falls back to a per-item call for any
    # item the batch did not return cleanly). Run-level --max-usd already gates
    # total spend, so no extra budget gate is needed here.
    batch_size = max(1, args.batch_size)
    prefetch: dict[str, tuple] = {}
    if batch_size > 1 and work:
        hash_by_slug = {c["slug"]: h for c, _t, h in work}
        skip = {slug for slug, it in done.items()
                if it.get("bundle_sha") == hash_by_slug.get(slug)}
        ulog.log("BATCH", out_path,
                 status=f"batching up to {batch_size}/call "
                        f"(≤{args.batch_max_chars:,} chars); "
                        f"misses fall back to per-item")
        prefetch = prefetch_batches(
            provider, system_prompt, work, ontology,
            batch_size=batch_size, batch_max_chars=args.batch_max_chars,
            max_parse_retries=args.max_parse_retries, trace=trace, skip=skip)
        ulog.log("BATCH", out_path,
                 status=f"{len(prefetch)} item(s) classified in batch; "
                        f"{max(0, total - len(skip) - len(prefetch))} fall back "
                        f"to per-item")

    def snapshot() -> dict:
        return {
            "generated_by": f"{provider_name}:{model}",
            "provider": provider_name,
            "model": model or "*",
            "ontology_version": ontology_version,
            "n_items": len(items),
            "n_failed": len(failed),
            "failed_slugs": failed,
            "skipped_breaker": skipped_breaker,
            "breaker_tripped": breaker.tripped,
            "breaker_reason": breaker.reason,
            "input_tokens": in_tok_total,
            "output_tokens": out_tok_total,
            "cost_usd": round(ledger.total_usd, 4),
            "items": items,
        }

    for idx, (c, truncated, bhash) in enumerate(work, start=1):
        slug = c["slug"]
        interrupt.advance(f"summarizing {slug}", unit="items")

        # Reuse a prior result for this exact bundle (resume).
        prior_item = done.get(slug)
        if prior_item is not None and prior_item.get("bundle_sha") == bhash:
            items.append(prior_item)
            ledger.total_usd += float(prior_item.get("cost_usd") or 0.0)
            ulog.log("LLM skip", slug,
                     status=f"{idx}/{total} reused (resume; unchanged bundle)")
            continue

        if breaker.tripped:
            skipped_breaker.append(slug)
            continue

        t0 = time.time()
        item_usd = 0.0
        # A batched call (--batch-size>1) may already hold this item's result;
        # consume it for free. Otherwise make the normal per-item call. Any item
        # the batch missed is absent here and falls through to the per-item path,
        # so batching never lowers robustness below the per-item baseline.
        pf = prefetch.pop(slug, None)
        if pf is not None:
            parsed, item_in, item_out, timing, secs = pf
            provider_err = ""
        else:
            # Pre-call budget check using per-item estimate (only the per-item
            # path spends here; the batch prefetch is already within the
            # run-level --max-usd estimate gated before the run started).
            per_item_est = est["est_usd_per_item"]
            if breaker.would_exceed(ledger.total_usd, per_item_est):
                breaker.trip(f"next item would exceed --max-usd ${args.max_usd}")
                trace.event("BUDGET_TRIP", slug, {"spent": ledger.total_usd},
                            severity="WARN")
                skipped_breaker.append(slug)
                continue
            prompt = build_prompt(c, truncated, ontology)
            # Structured-output enforcement + retry (FR-B4): json_mode requests
            # format=json where the backend supports it; on a parse miss we
            # re-request up to --max-parse-retries before recording an honest
            # failure, so a transient malformed response no longer injects a
            # permanent zero.
            parsed, item_in, item_out, _attempts, provider_err, timing = \
                complete_with_retry(
                    provider, system_prompt, prompt, args.max_parse_retries,
                    on_retry=lambda a, _s=slug: trace.event(
                        "LLM_RETRY", _s, {"attempt": a, "reason": "parse_miss"},
                        severity="WARN"))
            secs = time.time() - t0

        llm_ok = parsed is not None
        schema_valid = bool(llm_ok and raw_schema_valid(parsed))
        if item_in or item_out:
            item_usd = ledger.record(provider_name, model or "*", slug,
                                     item_in, item_out)
        in_tok_total += item_in
        out_tok_total += item_out

        if llm_ok:
            breaker.record_success()
            proc_secs += secs
            n_processed += 1
            trace.event("LLM_OK", slug,
                        {"secs": round(secs, 1), "in_tok": item_in,
                         "out_tok": item_out, "usd": round(item_usd, 5),
                         "schema_valid": schema_valid,
                         "load_ms": round(timing["load_ms"], 1),
                         "eval_ms": round(timing["eval_ms"], 1),
                         "prompt_eval_ms": round(timing["prompt_eval_ms"], 1)})
            ulog.log("LLM done", slug,
                     status=f"{idx}/{total} {secs:.0f}s "
                            f"in={item_in:,} out={item_out:,} tok "
                            f"${item_usd:.4f} "
                            f"arch={_as_obj(parsed.get('primary_archetype')).get('id')} "
                            f"| ETA {_eta(proc_secs, n_processed, total - idx)}")
        else:
            failed.append(slug)
            breaker.record_failure()
            err = provider_err or "non-JSON response after retries"
            trace.event("LLM_FAIL", slug, {"error": err[:300]}, severity="ERROR")
            ulog.err("LLM call", slug, error=err[:200])
            parsed = {}

        items.append(build_item(c, parsed or {}, ontology, provider_name,
                                model or "*", bhash, item_usd,
                                llm_ok=llm_ok, schema_valid=schema_valid))
        breaker.check_spend(ledger.total_usd)
        # Persist after every item so a killed run resumes from here.
        write_json(out_path, snapshot())

    result = snapshot()
    if meter is not None:
        meter.__exit__()
        psum = meter.summary()
        if psum.get("available") and psum.get("n", 0) >= 2:
            n_done = len(items) or 1
            result["power_wh"] = psum["wh"]
            result["power_wh_per_item"] = round(psum["wh"] / n_done, 4)
            result["power_trace"] = power_trace_path
            ulog.log("POWER", power_trace_path,
                     status=f"{psum['wh']:.3f} Wh over {psum['duration_s']:.0f}s "
                            f"({result['power_wh_per_item']:.4f} Wh/item)")
    write_json(out_path, result)
    ulog.log("WRITE", out_path,
             status=f"{len(items)} items, "
                    f"{in_tok_total:,}+{out_tok_total:,} tok, "
                    f"${ledger.total_usd:.4f}, {len(failed)} failed")

    if not args.no_validate:
        schema_path = os.path.join(ROOT, "schema", "extracted_item_schema.json")
        ok, errors = validate_with_jsonschema(result, schema_path)
        if not ok:
            ulog.err("VALIDATE", out_path,
                     error=f"{len(errors)} schema issue(s): {errors[:5]}")
        else:
            ulog.log("VALIDATE", out_path, status="schema OK")

    run_log.stage_end("summarize", root, n_items=len(items), provider=provider_name,
                      model=model, n_failed=len(failed), cost_usd=round(ledger.total_usd, 4),
                      cloud_provider=provider_name in CLOUD_PROVIDERS,
                      scrub_cloud=bool(scrub_cloud), scrub_hits=scrub_hits)

    if breaker.tripped:
        ulog.err("BREAKER", out_path,
                 error=f"tripped: {breaker.reason}; {len(skipped_breaker)} item(s) skipped")
        return 4
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(interrupt.run_cli(main, "gpt summarize"))
