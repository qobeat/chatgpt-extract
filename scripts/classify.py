#!/usr/bin/env python3
"""
classify.py  (deterministic prior — zero-LLM)

Propose a candidate Primary Archetype + Primary Domain/Subdomain Pair for each
cluster from the deterministic signals emitted by extract_cards. This is an
*auditable prior* (ADOS-EVAL): it justifies a starting guess from observable
evidence; the LLM stage (summarize.py) must confirm or override it under the
ADOS drift guards. It never fabricates — only scores ontology candidates.

Usage:
  python scripts/classify.py --store output/store      # annotate clusters.json
  # or import classify_cluster(cluster, ontology) from another module
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
import interrupt  # noqa: E402
import ulog  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_ontology() -> dict:
    with open(os.path.join(ROOT, "ontology", "archetypes.json"), encoding="utf-8") as f:
        arch = json.load(f)
    with open(os.path.join(ROOT, "ontology", "domains.json"), encoding="utf-8") as f:
        dom = json.load(f)
    return {"archetypes": arch, "domains": dom}


# Keyword banks for cheap, transparent scoring (lowercased, matched on title kw).
_ARCHETYPE_KW = {
    "study_education_resource": ["sat", "ap", "exam", "homework", "study", "quiz",
                                 "practice", "tutor", "physics", "calculus", "essay"],
    "media_generation": ["image", "portrait", "photo", "logo", "dalle", "render",
                          "illustration", "picture", "art"],
    "advisory_troubleshooting": ["fix", "error", "issue", "problem", "troubleshoot",
                                 "why", "broken", "not", "working", "debug"],
    "personal_admin": ["meeting", "schedule", "email", "plan", "reminder",
                       "calendar", "appointment", "skip", "reply", "message"],
    "content_writing": ["write", "draft", "rewrite", "translate", "summary",
                        "letter", "post", "blog", "copy"],
    "research_analysis": ["compare", "research", "analysis", "evaluate", "review",
                          "investigate", "vs"],
    "knowledge_qa": ["what", "who", "how", "when", "explain", "meaning", "define"],
    "ai_agent_prompt": ["prompt", "agent", "skill", "persona", "system"],
    "controlled_spec_or_schema": ["schema", "glossary", "ontology", "spec",
                                  "standard", "contract", "taxonomy"],
    "data_extraction_processing": ["extract", "parse", "csv", "dataset", "scrape",
                                   "convert", "pipeline"],
}

# --- Eval-facet priors (docs/REDESIGN-PROPOSAL.md §4; ontology/{cognitive_types,
# difficulty,verifiability}.json). These are deterministic PRIORS only — the LLM
# stage confirms/overrides under the ADOS drift guards. Kept in sync with the
# ontology banks (source of truth) via tests/test_classify.py.
_ARCH_TO_COGNITIVE = {
    "software_app": "reason_analyze",
    "runtime_package": "reason_analyze",
    "automation_or_diagnostic_script": "reason_analyze",
    "data_extraction_processing": "extract_transform",
    "research_analysis": "reason_analyze",
    "knowledge_qa": "retrieve",
    "advisory_troubleshooting": "converse_advise",
    "study_education_resource": "explain",
    "personal_admin": "plan_strategize",
    "ai_agent_prompt": "generate_create",
    "controlled_spec_or_schema": "classify_judge",
    "content_writing": "generate_create",
    "media_generation": "generate_create",
}
_COGNITIVE_DEFAULT_VERIF = {
    "retrieve": "objective", "explain": "rubric", "extract_transform": "objective",
    "classify_judge": "objective", "reason_analyze": "objective",
    "generate_create": "subjective", "plan_strategize": "rubric",
    "converse_advise": "rubric",
}
# Domains needing expert knowledge (raises the difficulty specialisation sub-axis).
_SPECIALIZED_DOMAINS = {
    "information_security", "health_medical", "finance", "law_governance",
    "natural_science", "automotive", "ai_ml",
}
# Difficulty tier thresholds — mirror ontology/difficulty.json score_range.
_TIER_RANGES = (("T1", 0, 2), ("T2", 3, 5), ("T3", 6, 8), ("T4", 9, 12))

_DOMAIN_KW = {
    ("education", None): ["sat", "ap", "exam", "homework", "study", "quiz", "tutor"],
    ("natural_science", "physics"): ["physics", "force", "velocity", "quantum"],
    ("natural_science", "mathematics"): ["math", "calculus", "algebra", "equation"],
    ("automotive", None): ["bmw", "car", "vehicle", "navigation", "tesla", "ev"],
    ("finance", "crypto"): ["crypto", "bitcoin", "ethereum", "token", "coin"],
    ("finance", None): ["stock", "market", "tax", "budget", "invest"],
    ("health_medical", None): ["medical", "health", "symptom", "doctor", "diagnosis"],
    ("arts_creative", None): ["art", "portrait", "logo", "poem", "story", "name",
                              "design", "music"],
    ("personal_productivity", None): ["meeting", "schedule", "email", "plan",
                                      "reminder", "calendar"],
    ("law_governance", None): ["contract", "hoa", "legal", "compliance", "policy"],
    ("humanities_social", None): ["history", "literature", "philosophy", "politics"],
}


def _tier_for(score: int) -> str:
    for tier, lo, hi in _TIER_RANGES:
        if lo <= score <= hi:
            return tier
    return "T4"


def _facet_priors(archetype: str, domain: str, *, has_code: bool, has_image: bool,
                  n_data: int, n_versions: int, n_conv: int) -> dict:
    """Deterministic priors for eval facets C/D/E/G from observable signals.

    A prior justifies a starting guess; the LLM stage may override it. Difficulty
    is the sum of four 0-3 sub-axes (steps, specialisation, ambiguity,
    context_load) mapped to a tier (ontology/difficulty.json)."""
    cognitive = _ARCH_TO_COGNITIVE.get(archetype, "retrieve")

    verifiability = _COGNITIVE_DEFAULT_VERIF.get(cognitive, "rubric")
    if domain == "arts_creative" or archetype == "media_generation":
        verifiability = "subjective"

    steps = min(3, (2 if (has_code or n_versions >= 2) else 1 if n_versions == 1 else 0)
                + (1 if cognitive == "reason_analyze" else 0))
    specialisation = 2 if domain in _SPECIALIZED_DOMAINS else (
        0 if domain in ("general_knowledge", "personal_productivity") else 1)
    ambiguity = 2 if cognitive in ("converse_advise", "generate_create",
                                   "plan_strategize", "explain") else 1
    context_load = min(3, (2 if n_conv >= 4 else 1 if n_conv >= 2 else 0)
                       + (1 if n_versions >= 2 else 0))
    score = steps + specialisation + ambiguity + context_load

    if has_image and not has_code:
        modality = "mixed" if n_data >= 1 else "image"
    elif has_code:
        modality = "mixed" if (has_image or n_data >= 2) else "code"
    elif n_data >= 2:
        modality = "data"
    else:
        modality = "text"

    return {
        "cognitive_type": cognitive,
        "difficulty": {
            "tier": _tier_for(score), "steps": steps,
            "specialisation": specialisation, "ambiguity": ambiguity,
            "context_load": context_load, "score": score,
        },
        "verifiability_class": verifiability,
        "modality": modality,
    }


def classify_cluster(cluster: dict) -> dict:
    """Return {primary_archetype, primary_domain_pair, scores} as a prior."""
    sig = cluster.get("signal_summary") or {}
    kw = set(sig.get("top_title_keywords") or [])
    # Title-token fallback from titles when keywords are sparse.
    if not kw:
        for t in (cluster.get("titles") or [])[:20]:
            kw.update(w for w in t.lower().replace("/", " ").split() if w)
    n_versions = sig.get("n_version_zips", cluster.get("n_versions", 0))
    has_code = bool(sig.get("has_code"))
    has_image = bool(sig.get("has_image_asset"))
    ext = sig.get("file_ext_classes") or {}
    arts = " ".join(cluster.get("file_artifacts") or []).lower()
    n_conv = cluster.get("n_conversations", 1)

    scores: dict[str, float] = {}

    def bump(a: str, pts: float) -> None:
        scores[a] = scores.get(a, 0.0) + pts

    # Structural priors (deterministic, strongest signals).
    if n_versions >= 2:
        bump("software_app", 3.0)
    if n_versions == 1:
        bump("software_app", 1.0)
        bump("automation_or_diagnostic_script", 0.5)
    if "setup.py" in arts or "pyproject" in arts or "package.json" in arts:
        bump("runtime_package", 2.0)
    if "skill.md" in arts:
        bump("ai_agent_prompt", 2.5)
    if any(s in arts for s in (".json", "schema", "glossary")):
        bump("controlled_spec_or_schema", 1.0)
    if has_image and not has_code and n_versions == 0:
        bump("media_generation", 3.0)
    if ext.get("code", 0) >= 1 and n_versions == 0 and ext.get("code", 0) <= 3:
        bump("automation_or_diagnostic_script", 1.0)
    if ext.get("data", 0) >= 2:
        bump("data_extraction_processing", 1.0)
    if not cluster.get("file_artifacts") and n_versions == 0 and not has_image:
        # Pure conversation: knowledge or advisory or personal admin.
        bump("knowledge_qa", 1.0)
        if n_conv == 1:
            bump("advisory_troubleshooting", 0.5)

    # Keyword priors (weaker, transparent).
    for arch, words in _ARCHETYPE_KW.items():
        hit = len(kw.intersection(words))
        if hit:
            bump(arch, 0.8 * hit)

    if not scores:
        bump("knowledge_qa", 0.5)

    primary = max(scores.items(), key=lambda kv: kv[1])
    secondary = sorted((a for a in scores if a != primary[0]),
                       key=lambda a: -scores[a])[:2]

    # Domain prior.
    dom_scores: dict[tuple, float] = {}
    for pair, words in _DOMAIN_KW.items():
        hit = len(kw.intersection(words))
        if hit:
            dom_scores[pair] = dom_scores.get(pair, 0.0) + hit
    if (has_code or n_versions >= 1) and not dom_scores:
        dom_scores[("software_engineering", None)] = 1.0
    if not dom_scores:
        dom_scores[("general_knowledge", None)] = 0.5
    dpair = max(dom_scores.items(), key=lambda kv: kv[1])[0]

    facets = _facet_priors(
        primary[0], dpair[0], has_code=has_code, has_image=has_image,
        n_data=int(ext.get("data", 0) or 0), n_versions=n_versions, n_conv=n_conv)

    return {
        "primary_archetype": {"id": primary[0], "score": round(primary[1], 2)},
        "secondary_archetypes": [{"id": a, "score": round(scores[a], 2)}
                                 for a in secondary if scores[a] > 0],
        "primary_domain_pair": {"domain": dpair[0], "subdomain": dpair[1]},
        **facets,
        "scores": {a: round(s, 2) for a, s in sorted(scores.items(),
                                                      key=lambda kv: -kv[1])},
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Annotate clusters.json with a deterministic archetype/domain "
                    "prior (classify_prior).")
    ap.add_argument("--store", default="output/store",
                    help="Store dir with clusters.json (default: output/store).")
    args = ap.parse_args()
    ulog.set_stage("Classify")

    cpath = os.path.join(args.store, "clusters.json")
    try:
        with open(cpath, encoding="utf-8") as f:
            clusters = json.load(f)
    except OSError as e:
        ulog.err("READ", cpath, error=e)
        return 1

    for c in clusters:
        c["classify_prior"] = classify_cluster(c)
    with open(cpath, "w", encoding="utf-8") as f:
        json.dump(clusters, f, ensure_ascii=False, indent=2)
    ulog.log("WRITE", cpath, status=f"annotated {len(clusters)} clusters with prior")

    # Quick distribution print for auditability.
    dist: dict[str, int] = {}
    for c in clusters:
        a = c["classify_prior"]["primary_archetype"]["id"]
        dist[a] = dist.get(a, 0) + 1
    for a, n in sorted(dist.items(), key=lambda kv: -kv[1]):
        print(f"  {a:<32} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(interrupt.run_cli(main, "gpt run · classify"))
