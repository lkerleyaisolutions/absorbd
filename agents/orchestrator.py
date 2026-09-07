"""Orchestrator - runs the full Absorbd pipeline for a patient profile.

  Intake-normalized profile
    -> [Deficiency | Medication | Dietary]   (parallel via threads)
    -> Synthesis -> Protocol -> Safety -> Doctor Guide

Every agent's TraceEvents are forwarded to an injected `emit` callback as they
happen, so a server can stream them (SSE) while the pipeline runs. The trio runs
concurrently with asyncio.to_thread (the agents make blocking Azure/OpenAI calls),
so emit MUST be thread-safe - the FastAPI layer enqueues onto an asyncio queue via
loop.call_soon_threadsafe.

Callers own client lifecycle: call _base.close_clients() at shutdown, NOT per run.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "data" / "intake"))
sys.path.insert(0, str(ROOT.parent / "data"))

from _base import Trace  # noqa: E402
from deficiency_hypothesis import hypothesize  # noqa: E402
from medication_interaction import analyze as medication_analyze  # noqa: E402
from dietary_gap import analyze as dietary_analyze  # noqa: E402
from synthesis import synthesize  # noqa: E402
from protocol import build_protocol  # noqa: E402
from safety import run_safety  # noqa: E402
from doctor_guide import run_doctor_guide  # noqa: E402
from medication_map import normalize_medication  # noqa: E402

# Behavioral correlation engine (data/correlations.py). Guarded import: the
# observational axis is an enhancement for the Doctor Guide; if it cannot load,
# the clinical pipeline must run exactly as before.
try:
    from correlations import compute_lag_correlations  # noqa: E402
except ImportError:
    compute_lag_correlations = None

Emit = Callable[[dict], None]


def _noop(_ev: dict) -> None:
    pass


def _med_to_str(m) -> str:
    """Coerce a medication entry to a string. Doctor-created patients store meds as
    {name, brand, dose, frequency} dicts; intake/analyze callers pass plain strings.
    The downstream pipeline assumes list[str], so flatten here at the boundary."""
    if isinstance(m, dict):
        name = (m.get("name") or m.get("brand") or "").strip()
        return name
    return str(m).strip()


# Inflammatory-marker tests whose HIGH status indicates an active flare. A flare
# changes how some nutrients are absorbed (e.g. oral iron is poorly absorbed during
# inflammation), so this is computed deterministically and attached to the profile.
_INFLAMMATION_TESTS = ("crp", "calprotectin", "fecal calprotectin")


def compute_active_inflammation(lab_values: list[dict]) -> bool:
    """Deterministic: True if any confirmed inflammatory-marker lab reads HIGH.

    Matches CRP, Calprotectin, and Fecal Calprotectin by test_name (case-insensitive
    substring) with status HIGH. Pure code, no LLM.
    """
    for lv in lab_values or []:
        name = str(lv.get("test_name", "")).strip().lower()
        status = str(lv.get("status", "")).strip().upper()
        if status != "HIGH":
            continue
        if any(t in name for t in _INFLAMMATION_TESTS):
            return True
    return False


def iron_route(labs: list[dict], active_inflammation: bool) -> tuple[str, str | None]:
    """Deterministic iron-route recommendation (pure code, no LLM).

    Returns ("iv_preferred", rationale) when ferritin is severely low (value < 15
    ng/mL) or its status is LOW AND inflammation is active, because oral iron is
    poorly absorbed during a flare. Otherwise ("oral", None).
    """
    if not active_inflammation:
        return "oral", None
    for lv in labs or []:
        name = str(lv.get("test_name", "")).strip().lower()
        if "ferritin" not in name:
            continue
        status = str(lv.get("status", "")).strip().upper()
        severely_low = status == "LOW"
        try:
            if float(lv.get("value")) < 15:
                severely_low = True
        except (TypeError, ValueError):
            pass
        if severely_low:
            return (
                "iv_preferred",
                "Oral iron is poorly absorbed during an active flare; "
                "consider IV iron repletion.",
            )
    return "oral", None


def prepare_profile(raw: dict) -> dict:
    """Normalize a raw profile: brand drug names -> generic (keeps unknowns as-is)."""
    meds = []
    for raw_med in raw.get("medications", []):
        m = _med_to_str(raw_med)
        if not m:
            continue
        meds.append(normalize_medication(m) or m)
    labs = raw.get("lab_values", []) or []
    return {
        "condition": raw.get("condition", "IBD"),
        "medications": meds,
        "symptoms": raw.get("symptoms", []),
        "reported_symptoms": raw.get("reported_symptoms", []),
        "dietary_restrictions": raw.get("dietary_restrictions", []),
        "lab_values": labs,
        "active_inflammation": compute_active_inflammation(labs),
        "patient_id": raw.get("patient_id", ""),
    }


# Map a canonical nutrient to the lab test names that measure its status, so a
# nutrient card can be anchored to a confirmed low lab even when the names differ
# (e.g. Iron status is read from Ferritin / Hemoglobin, not a test called "Iron").
_LAB_SYNONYMS = {
    "iron": ("ferritin", "hemoglobin", "hgb", "iron", "transferrin", "tibc"),
    "vitamin d": ("vitamin d", "25-oh", "25 oh", "calcidiol"),
    "vitamin b12": ("b12", "cobalamin", "vitamin b12"),
    "folate": ("folate", "folic"),
}


def _lab_matches(nutrient: str, test_name: str) -> bool:
    n, t = nutrient.lower(), test_name.lower()
    syns = _LAB_SYNONYMS.get(n, (n,))
    return any(s in t or t in s for s in syns)


def _annotate_lab_confirmed(nutrients: list[dict], profile: dict) -> None:
    """Tag each synthesized nutrient with the confirmed LOW lab value that anchors it.

    Mutates in place. Adds a structured `lab_confirmed` field (or leaves it absent)
    so the UI can render a LAB-CONFIRMED badge from real data instead of parsing
    trace text. Does NOT change convergence: a lab is an evidence anchor, not a
    counted condition/medication/diet pathway.
    """
    lows = [lv for lv in (profile.get("lab_values") or [])
            if str(lv.get("status", "")).upper() == "LOW"]
    if not lows:
        return
    for n in nutrients:
        name = (n.get("nutrient") or "").strip()
        if not name:
            continue
        match = next((lv for lv in lows if _lab_matches(name, lv.get("test_name", ""))), None)
        if match:
            n["lab_confirmed"] = {
                "test_name": match.get("test_name", ""),
                "value": match.get("value", ""),
                "unit": match.get("unit", ""),
                "status": match.get("status", ""),
            }


# Maximum observational journal patterns handed to the Doctor Guide. Kept small:
# they are discussion prompts for the clinician, not findings of the pipeline.
MAX_BEHAVIOR_FINDINGS = 3


def behavior_findings(patient_id: str) -> list[dict]:
    """Curated behavioral lag-correlations for the Doctor Guide (observational axis).

    Same statistical gate as the patient nudges (tier significant, mechanistically
    expected direction, not confound-flagged, deduped per factor/symptom pair, kept
    strongest-first) but WITHOUT the patient-safety exclusions: missed-medication
    patterns are exactly what a clinician should probe. These never touch deficiency
    reasoning, doses, or safety checks; they only feed hedged discussion prompts.
    Degrades to [] on any failure - the clinical pipeline must not depend on this.
    """
    if not patient_id or compute_lag_correlations is None:
        return []
    try:
        findings = compute_lag_correlations(patient_id)
    except Exception:
        return []
    out: list[dict] = []
    seen: set = set()
    for f in sorted(findings, key=lambda x: abs(getattr(x, "correlation", 0.0)),
                    reverse=True):
        if getattr(f, "tier", None) != "significant":
            continue
        if getattr(f, "direction_flag", "expected") != "expected":
            continue
        if getattr(f, "confound_flag", False):
            continue
        key = (f.factor, f.symptom)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "factor": f.factor,
            "symptom": f.symptom,
            "lag_label": f.lag_label,
            "strength": f.strength,
            "confidence": f.confidence,
            "n": f.n,
        })
        if len(out) >= MAX_BEHAVIOR_FINDINGS:
            break
    return out


async def run_pipeline(raw_profile: dict, emit: Emit = _noop) -> dict:
    """Run the full pipeline, streaming events via emit. Returns the final result."""
    profile = prepare_profile(raw_profile)
    # Observational journal patterns (statistical, doctor-facing). Computed in a
    # thread because the correlation engine reads SQLite.
    profile["behavior_findings"] = await asyncio.to_thread(
        behavior_findings, profile.get("patient_id", "")
    )
    trace = Trace(on_event=lambda ev: emit(
        {"type": "trace", "agent": ev.agent, "step": ev.step, "detail": ev.detail}
    ))

    emit({"type": "stage", "stage": "start", "profile": profile})

    # --- parallel reasoning trio ---
    defc, meds, diet = await asyncio.gather(
        asyncio.to_thread(hypothesize, profile, trace),
        asyncio.to_thread(medication_analyze, profile, trace),
        asyncio.to_thread(dietary_analyze, profile, trace),
    )
    emit({"type": "stage", "stage": "reasoning_complete"})

    # --- synthesis ---
    syn = await asyncio.to_thread(synthesize, meds, defc, diet, trace, profile)
    _annotate_lab_confirmed(syn["nutrients"], profile)
    emit({"type": "result", "stage": "synthesis", "data": syn["nutrients"]})

    # --- protocol ---
    proto = await asyncio.to_thread(build_protocol, syn, profile, trace)

    # --- safety ---
    safety = await asyncio.to_thread(run_safety, proto, profile, trace)
    emit({"type": "result", "stage": "safety",
          "data": {"escalation": safety["escalation"], "protocol": safety["checked_protocol"]}})

    # --- doctor guide ---
    guide = await asyncio.to_thread(run_doctor_guide, syn, safety, profile, trace)
    emit({"type": "result", "stage": "doctor_guide",
          "data": {"questions": guide["questions"],
                   "patient_actions": guide.get("patient_actions", [])}})

    emit({"type": "stage", "stage": "complete"})
    return {
        "profile": profile,
        "synthesis": syn["nutrients"],
        "escalation": safety["escalation"],
        "protocol": safety["checked_protocol"],
        "questions": guide["questions"],
        "patient_actions": guide.get("patient_actions", []),
    }
