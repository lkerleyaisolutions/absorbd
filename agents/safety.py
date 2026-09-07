"""Safety Agent (#8) - the guardrail. Hybrid design.

Three independent safety checks over the drafted protocol:

  1. RED-FLAG ESCALATION (deterministic): if the patient reported a red-flag symptom
     (e.g. palpitations -> possible electrolyte disturbance), surface an urgent
     "seek medical care" message ABOVE all nutrition advice. Uses the tested
     has_red_flag() from symptom_deficiency_map.

  2. DOSE-CEILING ENFORCEMENT (grounded LLM): for each proposed dose, retrieve the
     Tolerable Upper Limit (UL) from the knowledge base and confirm the dose is at or
     below it; cap and flag anything that exceeds. The hard limits Protocol left to us.

  3. GROUNDEDNESS CHECK (deterministic): any recommendation lacking a citation or built
     on "insufficient evidence" is flagged as needing clinician confirmation, never
     presented as settled advice.

Input  : protocol result {"protocol":[entries]} + profile (symptoms, condition)
Output : {"escalation": {...}, "checked_protocol": [...], "trace": [...]}
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "data" / "intake"))

from _base import Trace, retrieve, grounded_context, complete_json, as_citation_ints  # noqa: E402
from symptom_deficiency_map import has_red_flag  # noqa: E402

AGENT = "Safety"

NON_ACTIONABLE_MARKERS = ("discuss with clinician", "monitor")

UL_SYSTEM = """You are a dose-safety checker for a clinical nutrition system.
Given a nutrient, a PROPOSED daily dose, and EVIDENCE passages that may state the
Tolerable Upper Intake Level (UL), determine whether the proposed dose is at or below
the UL for a typical adult.

RULES:
- Use ONLY the evidence. If the evidence does not state a UL, set ul_stated=false and
  within_limit=null (unknown) - do not guess.
- If the proposed dose exceeds the UL, set within_limit=false and provide a
  recommended_max at or below the UL.
- Cite the passage number(s) stating the UL.

Return ONLY JSON:
{"ul_stated":true|false,"upper_limit":"<value with units or ''>","within_limit":true|false|null,"recommended_max":"<dose or ''>","citations":[<passage numbers>]}"""


def screen_red_flags(symptoms: list[str], reported_symptoms: list[str] | None = None) -> dict:
    """Deterministic red-flag escalation.

    FIX #3: when `reported_symptoms` is provided (the patient's actually-logged
    symptoms, e.g. from today's journal), screen THOSE rather than the doctor's
    monitoring watch-list. `source` distinguishes a true patient-reported flag
    ("reported", URGENT) from one that only appears on the watch-list ("watchlist",
    a softer signal). When reported_symptoms is None we fall back to the legacy
    behavior of screening `symptoms` and label the source "reported" for
    compatibility (callers that never tracked a watch-list).
    """
    if reported_symptoms is not None:
        flags = has_red_flag(reported_symptoms or [])
        source = "reported"
        if not flags:
            # Nothing reported today crosses a red line; fall back to the watch-list
            # as a softer signal so a clinician-flagged risk is still surfaced.
            flags = has_red_flag(symptoms or [])
            source = "watchlist"
    else:
        flags = has_red_flag(symptoms or [])
        source = "reported"

    if flags:
        if source == "reported":
            message = (
                "URGENT: The patient reported a symptom that can indicate a serious problem "
                f"({'; '.join(flags)}). Advise the patient to seek medical care promptly. "
                "The nutrition guidance below does not replace urgent evaluation."
            )
        else:
            message = (
                "Watch-list flag: a symptom on this patient's monitoring list "
                f"({'; '.join(flags)}) can indicate a serious problem. Advise the patient "
                "to seek care promptly if it occurs."
            )
        return {
            "urgent": source == "reported",
            "flags": flags,
            "source": source,
            "message": message,
        }
    return {"urgent": False, "flags": [], "source": "reported", "message": ""}


def _is_actionable(dose: str) -> bool:
    d = (dose or "").strip().lower()
    return bool(d) and not any(m in d for m in NON_ACTIONABLE_MARKERS)


def check_dose_ceiling(entry: dict, trace: Trace, patient_id: str | None = None) -> dict:
    """Grounded UL check for one protocol entry. Returns the entry with a safety status."""
    nutrient = entry["nutrient"]
    dose = entry.get("dose", "")
    result = dict(entry)

    # FIX #7: Protocol's adversarial gate already rejected this dose as ungrounded.
    # Respect that verdict rather than re-presenting the number as checkable fact.
    if entry.get("safety_status") == "dose_unverified":
        result.setdefault(
            "safety_note",
            "Dose not supported by the cited evidence; verify the dose before relying on it.",
        )
        trace.emit(AGENT, "check", f"{nutrient}: dose_unverified (ungrounded dose from protocol)")
        return result

    # Groundedness first (deterministic)
    if not _is_actionable(dose):
        result["safety_status"] = "deferred"
        result["safety_note"] = "No active dose proposed; clinician to advise."
        trace.emit(AGENT, "check", f"{nutrient}: deferred (no active dose)")
        return result
    if not entry.get("sources") or entry.get("evidence_level") == "insufficient evidence":
        result["safety_status"] = "unverified"
        result["safety_note"] = "Dose lacks a grounded citation; verify before relying on it."
        trace.emit(AGENT, "check", f"{nutrient}: UNVERIFIED (no grounded citation)")
        return result

    # Dose-vs-UL (grounded LLM, blends patient docs when patient_id is set)
    passages = retrieve(f"{nutrient} tolerable upper intake level UL maximum safe dose toxicity",
                        top=8, patient_id=patient_id)
    if not passages:
        result["safety_status"] = "ul_unknown"
        result["safety_note"] = "Upper limit not found in evidence; keep dosing at or below the recommended intake."
        trace.emit(AGENT, "check", f"{nutrient}: UL unknown (no evidence)")
        return result

    user = f"NUTRIENT: {nutrient}\nPROPOSED DOSE: {dose}\n\nEVIDENCE PASSAGES:\n{grounded_context(passages)}"
    try:
        verdict = complete_json(UL_SYSTEM, user)
    except Exception:
        # Fail CLOSED: a timeout/API error here must degrade to "unverified",
        # not kill the whole pipeline run mid-stream.
        verdict = {}

    cited = as_citation_ints(verdict.get("citations", []), len(passages))
    ul_sources = sorted({passages[n - 1].source_url for n in cited})
    within = verdict.get("within_limit")
    ul = verdict.get("upper_limit", "")

    if not verdict.get("ul_stated"):
        result["safety_status"] = "ul_unknown"
        result["safety_note"] = "No upper limit stated in evidence; keep dosing at or below the recommended intake."
    elif within is False:
        result["safety_status"] = "capped"
        result["dose"] = verdict.get("recommended_max") or dose
        result["safety_note"] = f"Proposed dose exceeded the tolerable upper limit ({ul}); capped."
        result["upper_limit"] = ul
        result["ul_sources"] = ul_sources
    else:
        result["safety_status"] = "ok"
        result["safety_note"] = f"Within the tolerable upper limit ({ul})." if ul else "Within recommended limits."
        result["upper_limit"] = ul
        result["ul_sources"] = ul_sources

    trace.emit(AGENT, "check", f"{nutrient}: {result['safety_status']} (UL {ul or 'n/a'})")
    return result


def run_safety(protocol_result: dict, profile: dict, trace: Trace | None = None) -> dict:
    trace = trace or Trace()

    # FIX #3: screen the patient's actually-reported symptoms when present; the
    # doctor's watch-list (profile.symptoms) becomes a softer fallback signal.
    reported = profile.get("reported_symptoms")
    escalation = screen_red_flags(profile.get("symptoms", []), reported_symptoms=reported)
    if escalation["urgent"]:
        trace.emit(AGENT, "escalate", f"RED FLAG (reported): {'; '.join(escalation['flags'])}")
    elif escalation["flags"]:
        trace.emit(AGENT, "escalate", f"Watch-list flag: {'; '.join(escalation['flags'])}")
    else:
        trace.emit(AGENT, "escalate", "No red-flag symptoms reported")

    patient_id = profile.get("patient_id") or None
    entries = protocol_result.get("protocol", [])

    # FIX #9: the per-entry UL check makes blocking Azure calls; run them concurrently
    # (offload each to a thread and gather). gather preserves input order.
    async def _gather() -> list[dict]:
        return await asyncio.gather(
            *(asyncio.to_thread(check_dose_ceiling, e, trace, patient_id) for e in entries)
        )

    checked = asyncio.run(_gather()) if entries else []
    capped = sum(1 for e in checked if e.get("safety_status") == "capped")
    unverified = sum(1 for e in checked if e.get("safety_status") in ("unverified", "ul_unknown"))
    trace.emit(AGENT, "conclude", f"{len(checked)} entries checked; {capped} capped, {unverified} flagged")

    return {"escalation": escalation, "checked_protocol": checked, "trace": trace.events}
