"""Dietary Gap Agent (#5).

For each dietary restriction the patient follows (e.g. lactose-free, vegan,
low-residue), identifies which nutrients that restriction puts at risk, grounded
ONLY in Foundry IQ evidence and adversarially verified.

Input  : profile dict {"condition": str, "dietary_restrictions": [labels]}
Output : {"results": [{"restriction", "findings":[...]}], "trace": [TraceEvent...]}
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _base import Trace, run_grounded_reasoning  # noqa: E402

AGENT = "DietaryGap"

PLAN_SYSTEM = """You are the planning step of a dietary-gap analysis for an IBD patient.
Given a dietary restriction and the patient's condition, briefly reason about which
nutrients that restriction could leave inadequate, then produce ONE focused search query.
Return ONLY JSON: {"reasoning":"<1-2 sentences>","search_query":"<query>"}"""

ANALYZE_SYSTEM = """You are the analysis step of a dietary-gap analysis for an IBD patient.
From the EVIDENCE passages ONLY, identify nutrients that this dietary restriction can
leave inadequate (e.g. avoiding a major food source of a nutrient).
HARD RULES: use ONLY the passages; if a gap is not supported by the passages, do not
include it (an empty list is correct); cite passage numbers. Write each rationale in
third-person clinical voice (about "the patient"), never "you"/"your".
Return ONLY JSON:
{"findings":[{"nutrient":"<n>","rationale":"<short, from evidence>","citations":[<passage numbers>]}]}"""


def analyze_restriction(restriction: str, condition: str, trace: Trace,
                        patient_id: str | None = None) -> dict:
    findings = run_grounded_reasoning(
        agent=AGENT,
        subject=restriction,
        condition=condition,
        plan_system=PLAN_SYSTEM,
        analyze_system=ANALYZE_SYSTEM,
        analyze_header=f"DIETARY RESTRICTION: {restriction}",
        trace=trace,
        patient_id=patient_id,
    )
    return {"restriction": restriction, "findings": findings}


def analyze(profile: dict, trace: Trace | None = None) -> dict:
    trace = trace or Trace()
    condition = profile.get("condition", "IBD")
    patient_id = profile.get("patient_id") or None
    results = [
        analyze_restriction(r, condition, trace, patient_id=patient_id)
        for r in profile.get("dietary_restrictions", [])
    ]
    return {"results": results, "trace": trace.events}
