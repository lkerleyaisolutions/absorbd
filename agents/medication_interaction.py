"""Medication Interaction Agent.

For each medication, determines which nutrients it depletes/affects, grounded ONLY
in Foundry IQ evidence and adversarially verified. Refuses to fabricate when the
knowledge base has no evidence for a drug.

Uses the shared PLAN->RETRIEVE->ANALYZE->VERIFY reasoning helper (see _base).

Input  : profile dict {"condition": str, "medications": [generic names]}
Output : {"results": [{"medication", "findings":[...]}], "trace": [TraceEvent...]}
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _base import Trace, run_grounded_reasoning  # noqa: E402

AGENT = "MedicationInteraction"

PLAN_SYSTEM = """You are the planning step of a medication-nutrient interaction analysis for an IBD patient.
Given a medication and the patient's condition, briefly reason about which nutrient
interactions are worth investigating, then produce ONE focused search query.
Return ONLY JSON: {"reasoning":"<1-2 sentences>","search_query":"<query>"}"""

ANALYZE_SYSTEM = """You are the analysis step of a medication-nutrient interaction analysis for an IBD patient.
From the EVIDENCE passages ONLY, extract how the medication depletes, reduces, or
impairs absorption of nutrients.
HARD RULES: use ONLY the passages; if they do not specifically discuss THIS medication's
effect on a nutrient, do not include it (an empty list is correct); cite passage numbers.
Write each mechanism in third-person clinical voice (about "the patient"), never "you"/"your".
Return ONLY JSON:
{"findings":[{"nutrient":"<n>","effect":"depletes|impairs absorption|reduces levels|increases need","mechanism":"<short, from evidence>","citations":[<passage numbers>]}]}"""


def analyze_medication(medication: str, condition: str, trace: Trace,
                       patient_id: str | None = None) -> dict:
    findings = run_grounded_reasoning(
        agent=AGENT,
        subject=medication,
        condition=condition,
        plan_system=PLAN_SYSTEM,
        analyze_system=ANALYZE_SYSTEM,
        analyze_header=f"MEDICATION: {medication}",
        trace=trace,
        patient_id=patient_id,
    )
    return {"medication": medication, "findings": findings}


def analyze(profile: dict, trace: Trace | None = None) -> dict:
    trace = trace or Trace()
    condition = profile.get("condition", "IBD")
    patient_id = profile.get("patient_id") or None
    results = [analyze_medication(m, condition, trace, patient_id=patient_id)
               for m in profile.get("medications", [])]
    return {"results": results, "trace": trace.events}
