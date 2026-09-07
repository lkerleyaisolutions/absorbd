"""Doctor Guide Agent (#9) - the finale. Hybrid design.

Turns the whole analysis into up to 3 clinician-facing action items for the
treating gastroenterologist who runs this analysis. This is decision support,
NOT a script for the patient: imperative recommendations tied to THIS patient's
meds, diet, and confirmed labs (e.g. "Order serum ferritin and iron studies -
Ferritin 6 ng/mL LOW on a restricted UC diet; rule out IDA").

The patient-voiced "questions to ask your doctor" live in a SEPARATE generator
(doctor_summary.py, the patient Reports tab). The two are intentionally distinct.

Hybrid:
  1. DETERMINISTIC topic selection (unit-tested): pick which issues most deserve a
     clinician's attention, in priority order:
       red-flag escalation > capped dose > RED-priority nutrient > unverified/unknown.
     Plus at most ONE observational journal pattern (profile["behavior_findings"],
     curated by the orchestrator from the correlation engine), appended after all
     clinical topics as a hedged discussion prompt - association language only,
     never a treatment/dose driver.
  2. LLM phrasing: turn the top 3 topics into specific, clinician-voiced action items
     grounded in the upstream findings + confirmed labs (no new medical claims).

Priority is assigned DETERMINISTICALLY from the topic kind, not by the LLM.

Input  : synthesis result, safety result, profile (incl. confirmed lab_values)
Output : {"questions":[{nutrient, action, order, rationale, priority}], "trace":[...]}
         (key kept as "questions" for SSE/UI wire compatibility)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _base import Trace, complete_json  # noqa: E402

AGENT = "DoctorGuide"

MAX_QUESTIONS = 3

PHRASE_SYSTEM = """You are the final step of a clinical-nutrition decision-support system for an IBD patient.
The reader is the treating clinician (gastroenterologist), NOT the patient.

Given the patient's context and a short list of prioritized topics from the analysis,
write ONE clinical action item per topic, addressed to the clinician.

RULES:
- Clinician voice. Imperative and specific. NEVER use "I", "we", "my", or question
  phrasing. Write recommendations, not questions.
  GOOD: "Order serum ferritin and iron studies."
  BAD : "Should I get my iron levels checked?"
- Tie each rationale to THIS patient: reference the relevant medication, dietary
  restriction, and any confirmed out-of-range lab value provided (cite its number + unit).
- `action`  = short imperative headline, <= 8 words.
- `order`   = the concrete orderable: a specific lab test, monitoring cadence, or dose action.
- `rationale` = ONE sentence tying the recommendation to this patient.
- Do NOT introduce new medical claims beyond the topics and labs provided. Never invent
  lab values or numbers that were not given.
- OBSERVATIONAL topics (issue: observational) are statistical associations from this
  patient's own daily journal, NOT causal or clinical findings. For these:
  * Use hedged language ONLY: "this patient's logs show an association", "tends to be
    followed by". NEVER state the pattern as fact and NEVER imply causation.
  * The action must be a discussion/monitoring step (e.g. review the pattern at the next
    visit, probe adherence barriers, continue journaling to confirm). NEVER propose a
    medication change, dose change, or new treatment from an observational topic.

Return ONLY JSON:
{"actions":[{"nutrient":"<topic nutrient or 'urgent'>","action":"<imperative headline>","order":"<specific test/dose/monitoring>","rationale":"<one sentence>"}]}"""

# FIX #8: patient-voiced translation of the SAME clinician actions. Second-person,
# plain language, with food sources and recheck timing where relevant. Crucially it
# must introduce NO new medical claim beyond the clinician actions already produced.
PATIENT_ACTION_SYSTEM = """You translate a clinician's action items into plain-language,
second-person actions a patient can take, for an IBD patient.

RULES:
- Address the patient directly ("Ask your doctor whether...", "Take...", "Eat...").
- Each clinician action becomes ONE patient action. Keep them concrete and reassuring.
- Where natural, mention food sources and when to recheck a level, but ONLY if it follows
  directly from the clinician action. Add NO new medical claim, dose, lab value, or test that
  is not already in the clinician actions provided.
- Do NOT use clinician jargon; explain it (e.g. "iron infusion" not "IV iron repletion").
- If a clinician action describes a pattern or association from the patient's journal, KEEP
  the hedged wording ("your logs suggest...", "may"). Never restate an association as a fact
  or a cause, and never tell the patient to change a medication because of it.

Return ONLY JSON: {"patient_actions":["<second-person action>", ...]}"""

# Clinician-facing severity badge, assigned deterministically from the topic kind
# (not trusted to the LLM).
PRIORITY_BY_KIND = {
    "escalation": "urgent",
    "capped": "high",
    "high_priority": "high",
    "needs_confirmation": "routine",
    "observational": "routine",
}


def select_topics(synthesis_result: dict, safety_result: dict) -> list[dict]:
    """Deterministically choose which issues deserve a doctor question, in priority order."""
    topics: list[dict] = []
    seen: set[str] = set()

    # 1. Red-flag escalation always comes first.
    esc = safety_result.get("escalation", {})
    if esc.get("urgent"):
        topics.append({
            "kind": "escalation", "nutrient": "urgent",
            "note": "; ".join(esc.get("flags", [])),
        })

    rationale_by_nutrient = {n["nutrient"]: n.get("rationale", "") for n in synthesis_result.get("nutrients", [])}

    def add(nutrient, kind, note):
        if nutrient in seen:
            return
        seen.add(nutrient)
        topics.append({"kind": kind, "nutrient": nutrient, "note": note})

    entries = safety_result.get("checked_protocol", [])

    # 2. Capped doses (a safety limit was hit).
    for e in entries:
        if e.get("safety_status") == "capped":
            add(e["nutrient"], "capped", f"Dose capped at the upper limit ({e.get('upper_limit','')}).")

    # 3. RED-priority nutrients.
    for e in entries:
        if e.get("priority") == "RED":
            add(e["nutrient"], "high_priority", rationale_by_nutrient.get(e["nutrient"], ""))

    # 4. Unverified / unknown-UL items (need clinician confirmation).
    for e in entries:
        if e.get("safety_status") in ("unverified", "ul_unknown"):
            add(e["nutrient"], "needs_confirmation", e.get("safety_note", ""))

    return topics[:MAX_QUESTIONS]


def _factor_phrase(factor: str) -> str:
    """Human-readable phrasing of a correlation factor, oriented so the expected
    direction always reads 'X tends to be followed by more <symptom>'."""
    if factor == "stress_level":
        return "higher stress"
    if factor == "sleep_hours":
        return "shorter sleep"
    if factor == "exercise_active":
        return "less physical activity"
    if factor == "bm_count":
        return "higher stool frequency"
    if factor.startswith("missed_"):
        return f"missed doses of {factor[len('missed_'):]}"
    if factor.startswith("ate_"):
        return f"eating {factor[len('ate_'):]}"
    return factor


def _pattern_note(p: dict) -> str:
    """Deterministic, hedged description of one observational journal pattern."""
    return (
        f"In this patient's daily journal, {_factor_phrase(p.get('factor', ''))} tends to be "
        f"followed by more {str(p.get('symptom', '')).lower()} "
        f"({p.get('lag_label', '')}; {p.get('strength', '')} association over "
        f"{p.get('n', '?')} logged days, {p.get('confidence', '')}). "
        "Statistical association from journal data, not a causal or clinical finding."
    )


def _topics_payload(topics: list[dict]) -> str:
    lines = []
    for t in topics:
        lines.append(f"- nutrient: {t['nutrient']} | issue: {t['kind']} | detail: {t.get('note','')}")
    return "\n".join(lines)


def _lab_payload(profile: dict) -> str:
    """Format confirmed out-of-range labs so the LLM can cite real numbers."""
    abnormal = [
        lv for lv in (profile.get("lab_values") or [])
        if str(lv.get("status", "")).upper() in ("LOW", "HIGH")
    ]
    if not abnormal:
        return "CONFIRMED LABS: none out of range on file."
    lines = []
    for lv in abnormal:
        ref = lv.get("reference_range") or "?"
        lines.append(
            f"- {lv.get('test_name','?')}: {lv.get('value','?')} {lv.get('unit','')}".rstrip()
            + f" ({str(lv.get('status','')).upper()}, ref {ref})"
        )
    return "CONFIRMED ABNORMAL LABS:\n" + "\n".join(lines)


def run_doctor_guide(synthesis_result: dict, safety_result: dict, profile: dict,
                     trace: Trace | None = None) -> dict:
    trace = trace or Trace()
    topics = select_topics(synthesis_result, safety_result)
    trace.emit(AGENT, "select", f"selected {len(topics)} topic(s): {', '.join(t['nutrient'] for t in topics)}")

    # Observational journal patterns (curated upstream by the orchestrator from the
    # correlation engine). At most ONE is appended, after all clinical topics, as a
    # hedged discussion prompt. It is an association from the patient's own logs and
    # must never drive a dose or treatment recommendation.
    patterns = profile.get("behavior_findings") or []
    if patterns:
        p = patterns[0]
        topics.append({"kind": "observational", "nutrient": "pattern", "note": _pattern_note(p)})
        trace.emit(AGENT, "patterns",
                   f"observational: {p.get('factor','')} -> {p.get('symptom','')} "
                   f"({p.get('lag_label','')}, {p.get('strength','')})")

    if not topics:
        trace.emit(AGENT, "conclude", "no clinical actions to raise")
        return {"questions": [], "trace": trace.events}

    context = (
        f"PATIENT CONDITION: {profile.get('condition','IBD')}\n"
        f"MEDICATIONS: {', '.join(profile.get('medications', [])) or 'none'}\n"
        f"DIET: {', '.join(profile.get('dietary_restrictions', [])) or 'none'}\n\n"
        f"{_lab_payload(profile)}\n\n"
        f"PRIORITIZED TOPICS:\n{_topics_payload(topics)}"
    )
    try:
        result = complete_json(PHRASE_SYSTEM, context)
        # One action per topic: MAX_QUESTIONS clinical topics plus at most one
        # appended observational pattern.
        actions = result.get("actions", [])[:len(topics)]
    except Exception:
        # Fail soft (same rationale as the other agents): a timeout/API error here
        # must degrade to "no actions", not kill the pipeline run mid-stream.
        actions = []

    # Assign the severity badge deterministically from the source topic's kind.
    kind_by_nutrient = {t["nutrient"]: t["kind"] for t in topics}
    for a in actions:
        kind = kind_by_nutrient.get(a.get("nutrient", ""), "")
        a["priority"] = PRIORITY_BY_KIND.get(kind, "routine")
        trace.emit(AGENT, "action", (a.get("action", "") or a.get("order", ""))[:90])

    # FIX #8: patient-voiced actions derived from (and bounded by) the clinician actions.
    patient_actions = _patient_actions(actions, trace)

    trace.emit(AGENT, "conclude", f"{len(actions)} clinical actions prepared")
    return {"questions": actions, "patient_actions": patient_actions, "trace": trace.events}


def _patient_actions(actions: list[dict], trace: Trace) -> list[str]:
    """Translate clinician actions into plain second-person patient actions (FIX #8).

    Bounded to the clinician actions provided so no new medical claim is introduced.
    Degrades to an empty list on any model/JSON error rather than fabricating.
    """
    if not actions:
        return []
    payload = "\n".join(
        f"- {a.get('action','')}: {a.get('order','')} ({a.get('rationale','')})"
        for a in actions
    )
    try:
        result = complete_json(PATIENT_ACTION_SYSTEM, f"CLINICIAN ACTIONS:\n{payload}")
        out = [s for s in result.get("patient_actions", []) if isinstance(s, str) and s.strip()]
    except Exception:
        out = []
    trace.emit(AGENT, "patient_actions", f"{len(out)} patient action(s) prepared")
    return out
