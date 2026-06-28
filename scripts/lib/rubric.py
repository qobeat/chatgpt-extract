"""ADOS Evaluation Rubric scorer (pure, no I/O).

Turns per-coordinate attainment (0..100) plus gate pass/fail results into a
single decision score, applying the rubric's mandatory gates. The whole point of
the gates is that a privacy or coverage failure CANNOT be averaged away by a high
score elsewhere: GATE-PRIVACY / GATE-COVERAGE are `fail` (hard zero), GATE-SCHEMA
is `cap_50` (a model that can't emit valid JSON cannot score above 50 on quality).

Coordinate definitions, scales, and anchors live in the Project Geometry; this
module only consumes the rubric's axes/weights/gates.
"""
from __future__ import annotations

from typing import Mapping

# failure_effect (evaluation-rubric.schema.json) -> numeric cap. "fail" forces 0;
# "indeterminate" yields a None score (not comparable); cap_N clamps the score.
_CAP = {"cap_25": 25.0, "cap_50": 50.0, "cap_75": 75.0}


def score(rubric: dict,
          attainments: Mapping[str, float | None],
          gate_results: Mapping[str, bool]) -> dict:
    """Score one provider/state against the rubric.

    attainments  : coordinate_id -> attainment 0..100 (or None == unknown).
    gate_results : gate_id -> True (passed) / False (failed). A gate absent from
                   the map is treated as passed (no evidence of failure).

    Returns a dict with the base (un-gated) score, the gated score, and the audit
    trail (which axes were excluded as unknown, which gates failed, which caps or
    hard-fails were applied)."""
    unknown_policy = rubric.get("unknown_policy", "exclude_and_report")
    excluded: list[str] = []
    weighted_sum = 0.0
    used_weight = 0.0

    for ax in rubric.get("axes", []):
        cref = ax["coordinate_ref"]
        weight = float(ax["weight"])
        att = attainments.get(cref)
        if att is None:
            excluded.append(cref)
            if unknown_policy == "fail_closed":
                att = 0.0
            elif unknown_policy == "indeterminate_if_material":
                return {
                    "base_score": None, "score": None, "status": "indeterminate",
                    "excluded_axes": excluded, "failed_gates": [],
                    "applied_caps": [], "reason": f"material axis {cref} unknown",
                }
            else:  # exclude_and_report
                continue
        weighted_sum += att * weight / 100.0
        used_weight += weight

    base = round(weighted_sum, 3)

    # Gates apply AFTER aggregation so a high average can't hide a hard failure.
    failed_gates: list[str] = []
    applied_caps: list[dict] = []
    gated = base
    status = "scored"
    for gate in rubric.get("mandatory_gates", []):
        gid = gate["gate_id"]
        if gate_results.get(gid, True):
            continue  # passed (or no evidence of failure)
        failed_gates.append(gid)
        effect = gate["failure_effect"]
        if effect == "fail":
            gated = 0.0
            status = "failed"
            applied_caps.append({"gate": gid, "effect": "fail", "to": 0.0})
        elif effect == "indeterminate":
            applied_caps.append({"gate": gid, "effect": "indeterminate"})
            return {
                "base_score": base, "score": None, "status": "indeterminate",
                "excluded_axes": excluded, "failed_gates": failed_gates,
                "applied_caps": applied_caps,
                "reason": f"gate {gid} indeterminate",
            }
        elif effect in _CAP:
            cap = _CAP[effect]
            if gated > cap:
                gated = cap
                applied_caps.append({"gate": gid, "effect": effect, "to": cap})

    return {
        "base_score": base,
        "score": round(gated, 3),
        "status": status,
        "excluded_axes": excluded,
        "used_weight": used_weight,
        "failed_gates": failed_gates,
        "applied_caps": applied_caps,
    }
