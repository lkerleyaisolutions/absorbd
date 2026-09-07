"""Deficiency Hypothesis Agent (#3).

From the patient's condition (and reported symptoms as non-diagnostic hints),
proposes which nutrient deficiencies are documented for that condition, grounded
ONLY in Foundry IQ evidence and adversarially verified.

Symptom hints from symptom_deficiency_map raise what to investigate, but NEVER
become assertions without retrieved evidence.

Input  : profile dict {"condition": str, "symptoms": [checklist labels]}
Output : {"results": [{"focus", "findings":[...]}], "trace": [TraceEvent...]}
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "data" / "intake"))

from _base import Trace, run_grounded_reasoning  # noqa: E402
from symptom_deficiency_map import deficiencies_for_symptoms  # noqa: E402

AGENT = "DeficiencyHypothesis"

PLAN_SYSTEM = """You are the planning step of a nutrient-deficiency analysis for an IBD patient.
Given the patient's condition and any symptom-based hints, briefly reason about which
nutrient deficiencies are most worth investigating, then produce ONE focused search query.
Return ONLY JSON: {"reasoning":"<1-2 sentences>","search_query":"<query>"}"""

ANALYZE_SYSTEM = """You are the analysis step of a nutrient-deficiency analysis for an IBD patient.
From the EVIDENCE passages ONLY, identify nutrient deficiencies that are documented to
occur in this condition or in people with its features (e.g. malabsorption).
HARD RULES: use ONLY the passages; if a deficiency is not supported by the passages, do
not include it (an empty list is correct); cite passage numbers. The symptom hints are
context for what to look for, NOT evidence on their own. Write each rationale in
third-person clinical voice (about "the patient"), never "you"/"your".
Return ONLY JSON:
{"findings":[{"nutrient":"<n>","rationale":"<short, from evidence>","citations":[<passage numbers>]}]}"""


def hypothesize(profile: dict, trace: Trace | None = None) -> dict:
    trace = trace or Trace()
    condition = profile.get("condition", "IBD")
    symptoms = profile.get("symptoms", [])
    lab_values = profile.get("lab_values", [])

    hints = deficiencies_for_symptoms(symptoms)
    hint_text = (
        "Symptom-based hints (NOT diagnostic), nutrient: times implicated by reported symptoms: "
        + ", ".join(f"{n}({c})" for n, c in sorted(hints.items(), key=lambda x: -x[1]))
        if hints
        else "No symptom-based hints provided."
    )

    # If confirmed lab values are present, prepend them so the agent reasons from
    # confirmed test results first instead of symptom hints alone.
    extra = hint_text
    if lab_values:
        lab_lines = "\n".join(
            f"  - {lv['test_name']}: {lv['value']} {lv['unit']} "
            f"[ref {lv.get('reference_range','?')}] STATUS={lv['status']}"
            for lv in lab_values
        )
        lab_block = f"CONFIRMED LAB VALUES (doctor-verified — treat as ground truth):\n{lab_lines}"
        extra = f"{lab_block}\n\n{hint_text}"
        trace.emit(AGENT, "lab_context",
                   f"{len(lab_values)} confirmed lab value(s) will anchor analysis")

    findings = run_grounded_reasoning(
        agent=AGENT,
        subject=f"{condition} deficiency risks",
        condition=condition,
        plan_system=PLAN_SYSTEM,
        analyze_system=ANALYZE_SYSTEM,
        analyze_header="TASK: identify documented nutrient deficiencies for this condition",
        trace=trace,
        extra=extra,
        patient_id=profile.get("patient_id") or None,
    )

    # Annotate findings that match confirmed lab values with LAB-CONFIRMED trace
    if lab_values:
        lab_names_low = {lv["test_name"].lower() for lv in lab_values if lv.get("status") == "LOW"}
        for finding in findings:
            nutrient = finding.get("nutrient", "").lower()
            # Match common nutrient synonyms to lab test names
            if any(lab in nutrient or nutrient in lab for lab in lab_names_low):
                matched_lv = next(
                    (lv for lv in lab_values
                     if lv["test_name"].lower() in nutrient or nutrient in lv["test_name"].lower()),
                    None,
                )
                if matched_lv:
                    trace.emit(
                        AGENT, "lab_confirmed",
                        f"LAB-CONFIRMED: {matched_lv['test_name']} {matched_lv['value']} "
                        f"{matched_lv['unit']} ({matched_lv['status']}) — "
                        f"{finding.get('nutrient')} deficiency confirmed, not hypothesized",
                    )

    return {"results": [{"focus": condition, "findings": findings}], "trace": trace.events}
