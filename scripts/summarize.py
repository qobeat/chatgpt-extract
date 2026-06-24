#!/usr/bin/env python3
"""
summarize.py  (Stage 4 — OPTIONAL LLM, multi-provider)

Classify each cluster bundle with an ADOS-grounded ontology (Primary Archetype +
Primary Domain/Subdomain Pair) and fill only the archetype-conditioned prose
fields. Deterministic facts (dates, version zips, file artifacts, member ids,
signals) are copied from clusters.json and merged OVER the model output — the
model never owns them.

Providers: ollama (local, $0) | openai | anthropic | cursor. Cost is estimated
before any paid call and gated by --max-usd; a circuit breaker stops the run on
repeated failures or budget breach. All calls are traced to a JSONL ledger.

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
import ulog  # noqa: E402
import paths  # noqa: E402
import run_log  # noqa: E402
import cost as cost_lib  # noqa: E402
from trace import TraceWriter, sha256_text, write_json, validate_with_jsonschema  # noqa: E402
from providers import get_provider, ProviderError  # noqa: E402

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


def archetype_contract(ontology: dict, arch_id: str) -> dict:
    for a in ontology["archetypes"]["archetypes"]:
        if a["id"] == arch_id:
            return a["field_contract"]
    return {}


def ensure_archetype_fields(fields: dict, contract: dict) -> dict:
    """Guarantee every contract key is present (empty default), enforcing the
    archetype field contract regardless of LLM omissions."""
    out = dict(fields or {})
    for key, meaning in contract.items():
        if key not in out or out[key] in (None, ""):
            out[key] = [] if str(meaning).startswith("array:") else out.get(key, "")
    return out


def build_item(cluster: dict, parsed: dict, ontology: dict,
               provider: str, model: str, bundle_hash: str,
               item_cost_usd: float) -> dict:
    prior = cluster.get("classify_prior") or classify_cluster(cluster)
    pa = parsed.get("primary_archetype") or {}
    pa_id = pa.get("id") or prior["primary_archetype"]["id"]
    contract = archetype_contract(ontology, pa_id)
    pdp = parsed.get("primary_domain_pair") or prior["primary_domain_pair"]

    return {
        # --- LLM-owned classification + meaning ---
        "item_id": cluster["slug"],
        "slug": cluster["slug"],
        "title": parsed.get("title") or cluster["slug"],
        "description": parsed.get("description", ""),
        "version": (cluster.get("version_zip_files") or [{}])[-1].get("version")
        if cluster.get("version_zip_files") else None,
        "is_durable_project": bool(parsed.get(
            "is_durable_project", cluster.get("n_versions", 0) >= 1)),
        "primary_archetype": {
            "id": pa_id,
            "label": pa.get("label", ""),
            "rationale": pa.get("rationale", ""),
        },
        "secondary_archetypes": parsed.get("secondary_archetypes", []),
        "primary_domain_pair": {
            "domain": pdp.get("domain", "general_knowledge"),
            "subdomain": pdp.get("subdomain"),
            "rationale": pdp.get("rationale", ""),
        },
        "secondary_domain_pairs": parsed.get("secondary_domain_pairs", []),
        "confidence": parsed.get("confidence", 0.0),
        "goal": parsed.get("goal", ""),
        "objectives": parsed.get("objectives", []),
        "requirements": parsed.get("requirements", []),
        "requirements_evolution": parsed.get("requirements_evolution", []),
        "deliveries": parsed.get("deliveries", []),
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
        # --- provenance ---
        "provider": provider,
        "model": model,
        "cost_usd": round(item_cost_usd, 6),
        "bundle_sha": bundle_hash,
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


def main() -> int:
    cfg = paths.load_config()
    ollama_cfg = cfg.get("ollama") or {}
    default_host = ollama_cfg.get("host", "http://localhost:11434")
    default_model = ollama_cfg.get("model", "gpt-oss:20b")
    default_num_ctx = int(ollama_cfg.get("num_ctx", 32768))
    default_max_chars = int(cfg.get("char_budget_per_bundle", 48000))

    ap = argparse.ArgumentParser(
        description="Stage 4 (optional, multi-provider): classify + summarize each "
                    "cluster with an ADOS ontology. Deterministic facts merged over.")
    ap.add_argument("--provider", default="ollama",
                    choices=["ollama", "openai", "anthropic", "cursor"],
                    help="LLM provider (default: ollama, local, $0).")
    ap.add_argument("--model", default=None, help="Model id/tag.")
    ap.add_argument("--host", default=None, help="Ollama host (ollama only).")
    ap.add_argument("--num-ctx", type=int, default=None, help="Ollama context window.")
    ap.add_argument("--run-label", default=None)
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
    ap.add_argument("--yes", action="store_true",
                    help="Skip the cost-estimate confirmation prompt.")
    ap.add_argument("--max-usd", type=float, default=None,
                    help="Hard budget cap; run aborts before exceeding it.")
    ap.add_argument("--max-usd-per-item", type=float, default=None)
    ap.add_argument("--max-consecutive-failures", type=int, default=3)
    ap.add_argument("--no-preflight", action="store_true")
    ap.add_argument("--no-validate", action="store_true",
                    help="Skip jsonschema validation of the output.")
    args = ap.parse_args()

    provider_name = args.provider
    model = args.model or (default_model if provider_name == "ollama" else "")
    if not model and provider_name != "cursor":
        ap.error(f"--model is required for provider '{provider_name}'.")

    run_label = args.run_label
    num_ctx = args.num_ctx if args.num_ctx is not None else default_num_ctx
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

    # --- gather bundle sizes for cost estimate ---
    work: list[tuple[dict, str, str]] = []   # (cluster, truncated_bundle, hash)
    bundle_chars: list[int] = []
    for c in clusters:
        bpath = os.path.join(bundles, f"{c['slug']}.md")
        if not os.path.exists(bpath):
            continue
        with open(bpath, encoding="utf-8") as f:
            bundle = f.read()
        truncated = bundle if len(bundle) <= max_chars else \
            bundle[:max_chars] + "\n[...truncated...]"
        prompt_chars = len(system_prompt) + len(build_prompt(c, truncated, ontology))
        bundle_chars.append(prompt_chars)
        work.append((c, truncated, sha256_text(truncated)))

    est = cost_lib.estimate_run(pricing, provider_name, model or "*", bundle_chars)
    sys.stderr.write(cost_lib.format_estimate(est) + "\n")

    if args.dry_run:
        for c, _t, _h in work:
            ulog.log("DRY-RUN", c["slug"],
                     status=f"prior={c['classify_prior']['primary_archetype']['id']}")
        ulog.log("DRY-RUN", out_path, status=f"would summarize {len(work)} items")
        return 0

    # --- budget gate ---
    if provider_name != "ollama" and est["est_usd"] > 0:
        if args.max_usd is not None and est["est_usd"] > args.max_usd:
            ulog.err("BUDGET", out_path,
                     error=f"estimate ${est['est_usd']:.2f} exceeds --max-usd "
                           f"${args.max_usd:.2f}. Raise the cap or use --limit.")
            return 1
        if not args.yes:
            sys.stderr.write(
                f"[cost] Proceed with ~${est['est_usd']:.2f} on {provider_name}? "
                f"Re-run with --yes to confirm (or --dry-run / --provider ollama).\n")
            return 3

    # --- provider preflight ---
    prov_kwargs: dict = {"model": model, "timeout": args.timeout}
    if provider_name == "ollama":
        prov_kwargs.update(host=args.host or default_host, num_ctx=num_ctx)
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

    for c, truncated, bhash in work:
        slug = c["slug"]
        if breaker.tripped:
            skipped_breaker.append(slug)
            continue
        # Pre-call budget check using per-item estimate.
        per_item_est = est["est_usd_per_item"]
        if breaker.would_exceed(ledger.total_usd, per_item_est):
            breaker.trip(f"next item would exceed --max-usd ${args.max_usd}")
            trace.event("BUDGET_TRIP", slug, {"spent": ledger.total_usd},
                        severity="WARN")
            skipped_breaker.append(slug)
            continue

        prompt = build_prompt(c, truncated, ontology)
        t0 = time.time()
        parsed: dict | None = None
        item_usd = 0.0
        try:
            text, usage = provider.complete(system_prompt, prompt, json_mode=True)
            parsed = parse_json_object(text)
            if parsed is None:
                raise ProviderError("non-JSON response")
            item_usd = ledger.record(provider_name, model or "*", slug,
                                     usage.input_tokens, usage.output_tokens)
            breaker.record_success()
            trace.event("LLM_OK", slug,
                        {"secs": round(time.time() - t0, 1),
                         "in_tok": usage.input_tokens,
                         "out_tok": usage.output_tokens, "usd": round(item_usd, 5)})
            ulog.log("LLM done", slug,
                     status=f"{time.time()-t0:.0f}s ${item_usd:.4f} "
                            f"arch={(parsed.get('primary_archetype') or {}).get('id')}")
        except ProviderError as e:
            failed.append(slug)
            breaker.record_failure()
            trace.event("LLM_FAIL", slug, {"error": str(e)[:300]}, severity="ERROR")
            ulog.err("LLM call", slug, error=str(e)[:200])
            parsed = {}

        items.append(build_item(c, parsed or {}, ontology, provider_name,
                                model or "*", bhash, item_usd))
        breaker.check_spend(ledger.total_usd)

    result = {
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
        "cost_usd": round(ledger.total_usd, 4),
        "items": items,
    }

    write_json(out_path, result)
    ulog.log("WRITE", out_path,
             status=f"{len(items)} items, ${ledger.total_usd:.4f}, "
                    f"{len(failed)} failed")

    if not args.no_validate:
        schema_path = os.path.join(ROOT, "schema", "extracted_item_schema.json")
        ok, errors = validate_with_jsonschema(result, schema_path)
        if not ok:
            ulog.err("VALIDATE", out_path,
                     error=f"{len(errors)} schema issue(s): {errors[:5]}")
        else:
            ulog.log("VALIDATE", out_path, status="schema OK")

    run_log.stage_end("summarize", root, n_items=len(items), provider=provider_name,
                      model=model, n_failed=len(failed), cost_usd=round(ledger.total_usd, 4))

    if breaker.tripped:
        ulog.err("BREAKER", out_path,
                 error=f"tripped: {breaker.reason}; {len(skipped_breaker)} item(s) skipped")
        return 4
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
