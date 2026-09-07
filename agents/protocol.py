"""Protocol Agent (#7).

Turns the Synthesis Agent's prioritized nutrients into an actionable supplement
protocol: form, dose, timing, evidence level, and cautions - grounded in the
recommended-intake / upper-limit evidence in the Foundry IQ knowledge base.

Separation of concerns: this agent PROPOSES doses grounded in cited intake
evidence and is told not to exceed any upper limit it finds. The Safety Agent (#8)
independently ENFORCES dose ceilings and red-flag escalation. Protocol proposes;
Safety disposes.

Input  : synthesis result {"nutrients":[{nutrient, priority, rationale, origins...}]}
         + profile (for medication context)
Output : {"protocol":[entries], "trace":[TraceEvent...]}
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _base import Trace, retrieve, grounded_context, complete_json, as_citation_ints  # noqa: E402

AGENT = "Protocol"

# Only RED/YELLOW get a supplement plan; GREEN is monitor-only.
ACTIONABLE = {"RED", "YELLOW"}


def _provenance(nutrient_obj: dict) -> dict:
    """Carry the Synthesis 'why' (rationale + converging pathways + lab anchor +
    time-aware lab recency note) onto the protocol entry so the card is
    self-describing and need not be re-joined."""
    return {
        "rationale": nutrient_obj.get("rationale", ""),
        "convergence": nutrient_obj.get("convergence", 0),
        "origins": nutrient_obj.get("origins", []),
        "lab_confirmed": nutrient_obj.get("lab_confirmed"),
        "lab_recent": nutrient_obj.get("lab_recent"),
        "lab_note": nutrient_obj.get("lab_note"),
    }

PLAN_SYSTEM = """You are the planning step of a supplement-protocol design for an IBD patient.
Given a nutrient and why it was prioritized, produce ONE focused search query to find
its recommended intake, supplement forms, and tolerable upper limit.
Return ONLY JSON: {"reasoning":"<1-2 sentences>","search_query":"<query>"}"""

DRAFT_SYSTEM = """You are the drafting step of a supplement-protocol design for an IBD patient.
From the EVIDENCE passages, propose a supplementation entry for the nutrient.

RULES:
- The reader is the treating clinician, NOT the patient. Write form/dose/timing/caution in
  third-person clinical voice about "the patient"; never address the reader as "you"/"your".
- Base the dose on the recommended intake in the evidence. NEVER propose a dose above any
  tolerable upper limit (UL) stated in the evidence.
- Cite the passage number(s) supporting the dose.
- If the evidence contains no intake/dose information, set dose to "Discuss with clinician"
  and evidence_level to "insufficient evidence".
- Prefer the better-supported supplement form if the evidence distinguishes forms.
- Keep timing/form guidance consistent with the evidence; do not invent specifics.
- caution: note any relevant interaction for this patient (e.g., a medication effect), briefly.
- If a CONFIRMED LAB VALUE is provided, anchor the dose to the patient's actual number, not a
  generic RDA. When the nutrient is iron AND ferritin is severely low (value < 15 ng/mL or LOW)
  AND inflammation is active, note in `caution` that oral iron is poorly absorbed during a flare
  and IV iron repletion should be considered.

Return ONLY JSON:
{"form":"<form or 'general'>","dose":"<dose with units, or guidance>","timing":"<when to take>","evidence_level":"<RDA-based|cited guidance|insufficient evidence>","caution":"<short or ''>","citations":[<passage numbers>]}"""

# FIX #7: adversarial groundedness gate for the drafted dose. A valid-looking citation
# index is not enough; the cited passage must actually STATE the dose/RDA/UL.
DOSE_VERIFY_SYSTEM = """You are an adversarial dose verifier for a clinical nutrition system.
Given a nutrient, a PROPOSED dose, and the exact CITED evidence passages, decide whether those
passages EXPLICITLY state a recommended intake / RDA / dose / upper limit that supports the
proposed dose. Be strict: if the passages do not clearly state a number that backs this dose,
mark supported=false. Default to false when uncertain.

Return ONLY JSON: {"supported":true|false,"quote":"<exact supporting sentence or empty>"}"""


def _verify_dose(nutrient: str, dose: str, cited: list[int], passages: list, trace: Trace) -> bool:
    """Run the adversarial gate. Returns True only if the cited passages support the dose."""
    if not cited:
        return False
    evidence = "\n".join(f"[{n}] {passages[n - 1].content}" for n in cited)
    user = f"NUTRIENT: {nutrient}\nPROPOSED DOSE: {dose}\n\nCITED EVIDENCE:\n{evidence}"
    try:
        verdict = complete_json(DOSE_VERIFY_SYSTEM, user)
    except Exception:
        # Fail CLOSED: an unverifiable dose must not be presented as fact.
        return False
    ok = bool(verdict.get("supported"))
    trace.emit(AGENT, "verify_dose", f"{nutrient}: {'VERIFIED' if ok else 'UNVERIFIED'} ({dose})")
    return ok


def _draft_entry(nutrient_obj: dict, condition: str, medications: list[str], trace: Trace,
                 patient_id: str | None = None, active_inflammation: bool = False,
                 labs: list[dict] | None = None) -> dict:
    nutrient = nutrient_obj["nutrient"]
    priority = nutrient_obj.get("priority", "")
    why = nutrient_obj.get("rationale", "")
    lab_confirmed = nutrient_obj.get("lab_confirmed")
    labs = labs or []

    # PLAN
    try:
        plan = complete_json(PLAN_SYSTEM, f"Nutrient: {nutrient}\nWhy prioritized: {why}")
    except Exception:
        # Timeout/API errors degrade to the default query, same as bad JSON.
        plan = {}
    query = plan.get("search_query") or f"{nutrient} recommended intake dose upper limit supplement form"
    trace.emit(AGENT, "plan", f"{nutrient}: {plan.get('reasoning', query)}")

    # Deterministic iron-route modulation (FIX #1): computed in pure code, not the LLM.
    # Local import avoids a module-load cycle (orchestrator imports build_protocol).
    from orchestrator import iron_route  # noqa: E402
    route, route_rationale = (None, None)
    if nutrient.lower() == "iron":
        route, route_rationale = iron_route(labs, active_inflammation)

    # RETRIEVE dosing evidence (blends patient docs + general literature when patient_id is set)
    passages = retrieve(query, top=8, patient_id=patient_id)
    trace.emit(AGENT, "retrieve", f"{nutrient}: {len(passages)} dosing-evidence passages")
    if not passages:
        trace.emit(AGENT, "draft", f"{nutrient}: no dosing evidence; deferring to clinician")
        return {
            "nutrient": nutrient, "priority": priority, "form": "general",
            "dose": "Discuss with clinician", "timing": "", "evidence_level": "insufficient evidence",
            "caution": "", "sources": [], "route": route, "route_rationale": route_rationale,
            **_provenance(nutrient_obj),
        }

    # DRAFT grounded entry (FIX #1: feed the actual lab number + flare state)
    meds = ", ".join(medications) or "none reported"
    lab_line = ""
    if lab_confirmed:
        lab_line = (
            "CONFIRMED LAB VALUE: "
            f"{lab_confirmed.get('test_name','')} {lab_confirmed.get('value','')} "
            f"{lab_confirmed.get('unit','')} ({str(lab_confirmed.get('status','')).upper()})\n"
        )
    user = (
        f"NUTRIENT: {nutrient}\nPRIORITY: {priority}\nPATIENT CONDITION: {condition}\n"
        f"PATIENT MEDICATIONS: {meds}\n{lab_line}"
        f"ACTIVE INFLAMMATION (flare): {active_inflammation}\nWHY PRIORITIZED: {why}\n\n"
        f"EVIDENCE PASSAGES:\n{grounded_context(passages)}"
    )
    try:
        entry = complete_json(DRAFT_SYSTEM, user)
    except Exception:
        # Empty entry falls through to "Discuss with clinician" defaults below.
        entry = {}

    cited = as_citation_ints(entry.get("citations", []), len(passages))
    sources = sorted({passages[n - 1].source_url for n in cited})
    dose = entry.get("dose", "Discuss with clinician")
    result = {
        "nutrient": nutrient,
        "priority": priority,
        "form": entry.get("form", "general"),
        "dose": dose,
        "timing": entry.get("timing", ""),
        "evidence_level": entry.get("evidence_level", "insufficient evidence"),
        "caution": entry.get("caution", ""),
        "sources": sources,
        "route": route,
        "route_rationale": route_rationale,
        **_provenance(nutrient_obj),
    }

    # FIX #7: adversarially verify the dose is actually stated in the cited evidence.
    # Only gate real, actionable doses (deferrals/insufficient-evidence are already flagged).
    dose_lc = (dose or "").strip().lower()
    is_real_dose = bool(dose_lc) and "discuss with clinician" not in dose_lc \
        and result["evidence_level"] != "insufficient evidence"
    if is_real_dose and not _verify_dose(nutrient, dose, cited, passages, trace):
        result["safety_status"] = "dose_unverified"
        result["safety_note"] = (
            "The cited evidence does not clearly state this dose; verify the dose "
            "before relying on it."
        )

    trace.emit(AGENT, "draft", f"{nutrient}: {result['dose']} ({result['evidence_level']})")
    return result


def build_protocol(synthesis_result: dict, profile: dict, trace: Trace | None = None) -> dict:
    trace = trace or Trace()
    condition = profile.get("condition", "IBD")
    medications = profile.get("medications", [])
    patient_id = profile.get("patient_id") or None
    active_inflammation = bool(profile.get("active_inflammation"))
    labs = profile.get("lab_values") or []

    nutrients = synthesis_result.get("nutrients", [])

    def _build_one(n: dict) -> dict:
        if n.get("priority") in ACTIONABLE:
            return _draft_entry(n, condition, medications, trace, patient_id=patient_id,
                                active_inflammation=active_inflammation, labs=labs)
        trace.emit(AGENT, "monitor", f"{n['nutrient']}: GREEN - monitor only, no supplement proposed")
        return {
            "nutrient": n["nutrient"], "priority": n.get("priority", "GREEN"),
            "form": "", "dose": "Monitor; no supplement unless advised",
            "timing": "", "evidence_level": "n/a", "caution": "", "sources": [],
            "route": None, "route_rationale": None,
            **_provenance(n),
        }

    # FIX #9: run the per-nutrient drafts concurrently. The agent calls are blocking
    # (Azure/OpenAI + KB retrieval), so offload each to a thread and gather. Output
    # order is preserved because gather preserves argument order.
    async def _gather() -> list[dict]:
        return await asyncio.gather(*(asyncio.to_thread(_build_one, n) for n in nutrients))

    protocol = asyncio.run(_gather()) if nutrients else []
    trace.emit(AGENT, "conclude", f"{len(protocol)} protocol entries drafted")
    return {"protocol": protocol, "trace": trace.events}
