"""Journal Agent — conversational daily health check-in.

Full conversational state machine:
  greeting → symptoms → followups → medications → food → sleep → stool
           → stress → exercise → notes → confirm → done

Each turn: agent sends messages + UI control spec (chips / text / confirm).
Patient responds by clicking chips and/or typing. LLM generates the personalized
greeting and per-symptom follow-up questions; all other logic is deterministic.
"""

from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "data"))

from _base import complete_json, complete_text  # noqa: E402
from journal import (  # noqa: E402
    add_entry,
    get_patient_by_id,
    get_symptom_frequencies,
    get_yesterday_entry,
)
from symptom_advisor import (  # noqa: E402
    build_ordered_symptoms,
    clarify_symptom_text,
    generate_symptom_prompt,
)

# ── Option banks ─────────────────────────────────────────────────────────────

FOOD_TRIGGERS = [
    "Dairy", "Gluten/Wheat", "Spicy Food", "Red Meat",
    "Alcohol", "Caffeine", "Legumes/Beans", "Garlic/Onion",
    "Ultra-processed", "Raw Vegetables",
]

SLEEP_OPTIONS = ["Under 5h", "6h", "7h", "8h", "9h or more"]

STOOL_OPTIONS = ["0", "1", "2", "3", "4", "5+"]

EXERCISE_OPTIONS = ["None", "Light walk", "Moderate", "Intense"]

STRESS_OPTIONS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]

# Slider definitions for numeric-scale questions (rendered as sliders in the UI).
STRESS_SCALE = {
    "min": 1, "max": 10, "step": 1, "default": 5,
    "min_label": "very calm", "max_label": "very stressed",
}
STOOL_SCALE = {
    "min": 0, "max": 5, "step": 1, "default": 0,
    "min_label": "0", "max_label": "5+", "max_value_label": "5+",
}

MAX_FOLLOWUPS = 3

# ── LLM prompts ──────────────────────────────────────────────────────────────

_FOLLOWUP_SYSTEM = """\
You are a warm, concise health assistant for an IBD patient logging app.
The patient just reported a symptom. Ask ONE short, friendly question about how
severe it is today, on a 1 to 5 scale (1 = barely noticeable, 5 = severe).
Keep it brief (under 20 words). Do NOT include the scale options in your output.
Return ONLY JSON: {"question": "..."}"""

_CONFIRM_SYSTEM = """\
You are summarizing a patient's daily health log entry in 2-3 warm, plain-English sentences.
Mention: key symptoms (or 'feeling well' if none), medication adherence, stress level, and
any notable food triggers or sleep issues. No medical advice.
Return ONLY the summary text — no JSON."""


# ── Session storage ──────────────────────────────────────────────────────────

JOURNAL_SESSIONS: dict[str, dict] = {}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _sleep_to_hours(label: str) -> float:
    mapping = {"Under 5h": 4.5, "6h": 6.0, "7h": 7.0, "8h": 8.0, "9h or more": 9.0}
    return mapping.get(label, 7.0)


def _stool_to_int(label: str) -> int:
    return 5 if label == "5+" else int(label)


def _med_label(med) -> str:
    if isinstance(med, dict):
        label = med.get("name", "")
        if med.get("brand"):
            label += f" ({med['brand']})"
        if med.get("dose"):
            label += f" {med['dose']}"
        return label
    return str(med)


def _med_key(med) -> str:
    if isinstance(med, dict):
        return med.get("name", str(med))
    return str(med)


def _sanitize_symptom(text: str) -> str:
    """Strip non-symptom characters and cap length to prevent prompt injection."""
    cleaned = re.sub(r"[^a-zA-Z0-9\s\-/]", "", text).strip()
    return cleaned[:60]


def _stress_label(level: int) -> str:
    if level <= 2:
        return "very calm"
    if level <= 4:
        return "mild"
    if level <= 6:
        return "moderate"
    if level <= 8:
        return "high"
    return "very high"


def _turn(session_id: str, agent_msgs, kind: str, *, stage: str,
          options=None, placeholder: str = "", allow_text: bool = False,
          scale=None, done: bool = False, entry_id: str | None = None) -> dict:
    if isinstance(agent_msgs, str):
        agent_msgs = [agent_msgs]
    return {
        "session_id": session_id,
        "agent": agent_msgs,
        "input": {
            "kind": kind, "stage": stage, "options": options or [],
            "placeholder": placeholder, "allow_text": allow_text,
            "scale": scale,
        },
        "done": done,
        "entry_id": entry_id,
        "profile": None,
    }


# Fixed 1-5 severity scale shown for every symptom follow-up, so the patient
# always sees 1, 2, 3, 4, 5 (the LLM only personalizes the question wording).
SEVERITY_OPTIONS = ["1", "2", "3", "4", "5"]


def _generate_followup(symptom: str, condition: str) -> dict:
    """Generate one follow-up question; options are always a 1-5 severity scale."""
    static_question = f"How severe is your {symptom} today? (1 = mild, 5 = severe)"
    try:
        result = complete_json(
            _FOLLOWUP_SYSTEM,
            f"Patient condition: {condition}\nSymptom reported: {symptom}"
        )
        question = result.get("question") or static_question
    except Exception:
        question = static_question
    return {"question": question, "options": list(SEVERITY_OPTIONS)}


# ── Public API ────────────────────────────────────────────────────────────────

def start_journal_session(patient_id: str) -> dict:
    patient = get_patient_by_id(patient_id)
    if not patient:
        return {"error": "unknown patient"}

    freq_scores = get_symptom_frequencies(patient_id, days=30)
    ordered = build_ordered_symptoms(patient, freq_scores)

    yesterday = get_yesterday_entry(patient_id)
    yesterday_symptoms = (
        yesterday["symptoms_today"][:2]
        if yesterday and yesterday.get("symptoms_today")
        else []
    )
    # One coherent greeting: the model folds in yesterday's context itself, so we no
    # longer prepend a separate "Yesterday you had X." line that double-listed symptoms.
    greeting_data = generate_symptom_prompt(patient, freq_scores, yesterday_symptoms)

    session_id = "j_" + uuid.uuid4().hex[:12]
    JOURNAL_SESSIONS[session_id] = {
        "patient_id": patient_id,
        "patient": patient,
        "stage": "symptoms",
        "ordered_symptoms": ordered,
        "collected": {
            "symptoms_today": [],
            "symptom_details": {},
            "medications_taken": {},
            "food_today": [],
            "sleep_hours": None,
            "bm_count": None,
            "exercise": None,
            "stress_level": 5,
            "notes": "",
        },
        "pending_followups": [],
    }

    chip_options = ["Feeling well today"] + [s["name"] for s in ordered]

    return _turn(
        session_id,
        [greeting_data.get("message", "How are you feeling today?"),
         "Tap all symptoms you're experiencing, or 'Feeling well today' if you're doing great."],
        "chips_multi",
        stage="symptoms",
        options=chip_options,
        allow_text=True,
        placeholder="Describe anything else...",
    )


def handle_journal_message(session_id: str, text: str = "",
                           selected: list[str] | None = None) -> dict:
    s = JOURNAL_SESSIONS.get(session_id)
    if not s:
        return {"error": "unknown session"}
    selected = selected or []
    text = (text or "").strip()
    stage = s["stage"]
    patient = s["patient"]
    col = s["collected"]
    meds = patient.get("medications", [])

    # ── symptoms ──────────────────────────────────────────────────────────────
    if stage == "symptoms":
        if "Feeling well today" in selected:
            col["symptoms_today"] = []
            return _finish_symptoms_stage(session_id, s)

        symptoms = [x for x in selected if x != "Feeling well today"]

        if text:
            condition = patient.get("condition", "IBD")
            try:
                clarify = clarify_symptom_text(text, condition, symptoms)
            except Exception:
                clarify = {"is_relevant": True, "needs_clarification": False,
                           "parsed_symptoms": [], "question": None, "options": []}

            if not clarify.get("is_relevant", True):
                # Irrelevant text — store chips only and tell the user
                col["symptoms_today"] = symptoms
                s["symptom_text_note"] = (
                    "I didn't recognize that as a symptom, so I only logged your selected chips."
                )
            elif clarify.get("needs_clarification"):
                # Vague text — ask a clarifying question before moving on
                col["symptoms_today"] = symptoms  # chips are already valid
                s["stage"] = "symptom_clarify"
                s["symptom_text_note"] = None
                return _turn(
                    session_id,
                    clarify["question"],
                    "chips_single",
                    stage="symptom_clarify",
                    options=(clarify.get("options") or []) + ["None of these"],
                    allow_text=True,
                    placeholder="Or describe in your own words...",
                )
            elif clarify.get("parsed_symptoms"):
                # Clear mapping — use canonical names
                for sym in clarify["parsed_symptoms"]:
                    if sym not in symptoms:
                        symptoms.append(sym)
                col["symptoms_today"] = symptoms
            else:
                # Fallback: sanitize and store raw text
                sanitized = _sanitize_symptom(text)
                if sanitized and sanitized not in symptoms:
                    symptoms.append(sanitized)
                col["symptoms_today"] = symptoms
        else:
            col["symptoms_today"] = symptoms

        return _finish_symptoms_stage(session_id, s)

    # ── symptom_clarify ───────────────────────────────────────────────────────
    if stage == "symptom_clarify":
        if selected and "None of these" not in selected:
            for sym in selected:
                if sym not in col["symptoms_today"]:
                    col["symptoms_today"].append(sym)
        elif text and text != "None of these":
            # "None of these" arrives as text (the UI sends single-select chips as
            # text, not in `selected`); guard against logging it as a symptom.
            sanitized = _sanitize_symptom(text)
            if sanitized and sanitized not in col["symptoms_today"]:
                col["symptoms_today"].append(sanitized)

        return _finish_symptoms_stage(session_id, s)

    # ── followups ─────────────────────────────────────────────────────────────
    if stage == "followups":
        current = s.get("current_followup")
        if current:
            answer = selected[0] if selected else text
            # "Skip" arrives as text from the single-select chip; treat it as no answer.
            if answer and answer != "Skip":
                col["symptom_details"][current["symptom"]] = answer

        if s["pending_followups"]:
            return _next_followup(session_id, s)

        return _go_to_medications(session_id, s)

    # ── medications ───────────────────────────────────────────────────────────
    if stage == "medications":
        if "All taken" in selected:
            col["medications_taken"] = {_med_key(m): "taken" for m in meds}
        elif "All missed" in selected:
            col["medications_taken"] = {_med_key(m): "missed" for m in meds}
        else:
            taken_labels = set(selected)
            for m in meds:
                label = _med_label(m)
                key = _med_key(m)
                if label in taken_labels:
                    col["medications_taken"][key] = "taken"
                elif f"missed:{label}" in taken_labels:
                    col["medications_taken"][key] = "missed"
                elif f"partial:{label}" in taken_labels:
                    col["medications_taken"][key] = "partial"
                # Leave unset (neutral) if not tapped

        taken_count = sum(1 for v in col["medications_taken"].values() if v == "taken")
        total = len(meds)
        ack = f"Got it — {taken_count}/{total} medications taken." if meds else ""

        if s.get("editing"):
            return _return_to_confirm(session_id, s)

        s["stage"] = "food"
        return _turn(
            session_id,
            [x for x in [ack, "Did you eat any of these today? Tap all that apply."] if x],
            "chips_multi",
            stage="food",
            options=["None of these"] + FOOD_TRIGGERS,
            allow_text=True,
            placeholder="Anything else (e.g. gluten-free bread)...",
        )

    # ── food ──────────────────────────────────────────────────────────────────
    if stage == "food":
        if "None of these" in selected:
            col["food_today"] = []
        else:
            foods = [x for x in selected if x != "None of these"]
            if text and text not in foods:
                foods.append(text)
            col["food_today"] = foods

        if s.get("editing"):
            return _return_to_confirm(session_id, s)

        s["stage"] = "sleep"
        return _turn(
            session_id,
            "About how much did you sleep last night?",
            "chips_single",
            stage="sleep",
            options=SLEEP_OPTIONS,
        )

    # ── sleep ─────────────────────────────────────────────────────────────────
    if stage == "sleep":
        if selected:
            col["sleep_hours"] = _sleep_to_hours(selected[0])
        elif text:
            try:
                col["sleep_hours"] = float(text.replace("h", "").strip().split()[0])
            except (ValueError, IndexError):
                col["sleep_hours"] = 7.0

        if s.get("editing"):
            return _return_to_confirm(session_id, s)

        s["stage"] = "stool"
        return _turn(
            session_id,
            "How many bowel movements did you have today?",
            "scale",
            stage="stool",
            options=STOOL_OPTIONS,
            scale=STOOL_SCALE,
        )

    # ── stool ─────────────────────────────────────────────────────────────────
    if stage == "stool":
        if selected:
            col["bm_count"] = _stool_to_int(selected[0])
        elif text:
            try:
                col["bm_count"] = int(text.strip())
            except ValueError:
                col["bm_count"] = 0

        if s.get("editing"):
            return _return_to_confirm(session_id, s)

        s["stage"] = "stress"
        return _turn(
            session_id,
            "How stressed are you today? (1 = very calm, 10 = very stressed)",
            "scale",
            stage="stress",
            options=STRESS_OPTIONS,
            scale=STRESS_SCALE,
        )

    # ── stress ────────────────────────────────────────────────────────────────
    if stage == "stress":
        if selected:
            try:
                col["stress_level"] = int(selected[0])
            except (ValueError, IndexError):
                col["stress_level"] = 5
        elif text:
            try:
                col["stress_level"] = max(1, min(10, int(text)))
            except ValueError:
                col["stress_level"] = 5

        if s.get("editing"):
            return _return_to_confirm(session_id, s)

        s["stage"] = "exercise"
        return _turn(
            session_id,
            "How much did you exercise today?",
            "chips_single",
            stage="exercise",
            options=EXERCISE_OPTIONS,
        )

    # ── exercise ──────────────────────────────────────────────────────────────
    if stage == "exercise":
        if selected:
            col["exercise"] = selected[0]
        elif text:
            col["exercise"] = text
        else:
            col["exercise"] = "None"

        if s.get("editing"):
            return _return_to_confirm(session_id, s)

        s["stage"] = "notes"
        return _turn(
            session_id,
            "Anything else to add? (travel, new symptoms, how you're feeling overall — or tap Skip)",
            "text",
            stage="notes",
            allow_text=True,
            placeholder="Optional notes...",
            options=["Skip"],
        )

    # ── notes ─────────────────────────────────────────────────────────────────
    if stage == "notes":
        # The Skip chip sends "Skip" as text (not in `selected`), so check both.
        if "Skip" not in selected and text != "Skip":
            col["notes"] = text

        # Editing notes (or finishing the normal flow) both land on confirm.
        s.pop("editing", None)
        summary = _build_confirm_summary(s)

        s["stage"] = "confirm"
        return _turn(
            session_id,
            [summary, "Does that look right? Tap \"Looks good, save it\" to save, or \"Edit something\" to make a change."],
            "confirm",
            stage="confirm",
            options=["Confirm"],
            allow_text=True,
        )

    # ── edit_menu ─────────────────────────────────────────────────────────────
    if stage == "edit_menu":
        choice = (selected[0] if selected else text).strip().lower()
        if not choice or choice.startswith("nothing") or "save" in choice:
            s["stage"] = "confirm"
            return handle_journal_message(session_id, "confirm", [])
        return _handle_edit_request(session_id, s, choice)

    # ── confirm ───────────────────────────────────────────────────────────────
    if stage == "confirm":
        if text.lower().startswith("edit"):
            section = text.lower().replace("edit", "").strip()
            if not section:
                # Generic "Edit something" button — offer a tappable section menu
                # instead of telling the user to type an "edit <section>" command.
                s["stage"] = "edit_menu"
                meds = patient.get("medications", [])
                options = ["Symptoms"]
                if meds:
                    options.append("Medications")
                options += ["Food", "Sleep", "Stress", "Exercise", "Notes",
                            "Nothing, save it"]
                return _turn(
                    session_id,
                    "What would you like to change?",
                    "chips_single",
                    stage="edit_menu",
                    options=options,
                )
            return _handle_edit_request(session_id, s, section)

        # Save the entry
        extra = {
            "food_today": col["food_today"],
            "sleep_hours": col["sleep_hours"],
            "bm_count": col["bm_count"],
            "exercise": col["exercise"],
            "symptom_details": col["symptom_details"],
        }
        try:
            entry_id = add_entry(
                patient_id=s["patient_id"],
                symptoms_today=col["symptoms_today"],
                medications_taken=col["medications_taken"],
                stress_level=col["stress_level"],
                notes=col["notes"],
                extra=extra,
            )
        except Exception as exc:
            return {"error": f"Failed to save entry: {exc}"}

        s["stage"] = "done"
        return _turn(
            session_id,
            "Entry saved. Keep it up — the more you log, the clearer the picture for your doctor.",
            "none",
            stage="done",
            done=True,
            entry_id=entry_id,
        )

    return _turn(session_id, "Check-in already complete.", "none", stage="done", done=True)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _finish_symptoms_stage(session_id: str, s: dict) -> dict:
    """Generate follow-ups for the reported symptoms, then move to medications.

    Follow-ups fire for any reported symptom (chips, condition-typical, or canonical
    free-text), not just the patient's `symptoms_to_watch`. Irrelevant free text is
    already filtered upstream by clarify_symptom_text, so anything that reaches here is
    a real symptom worth a quick severity/timing follow-up (capped at MAX_FOLLOWUPS).
    """
    patient = s["patient"]
    col = s["collected"]
    condition = patient.get("condition", "IBD")

    # Editing just the symptoms section: keep the new selection, skip re-asking
    # severity follow-ups, and go straight back to confirm.
    if s.get("editing"):
        return _return_to_confirm(session_id, s)

    for sym in col["symptoms_today"][:MAX_FOLLOWUPS]:
        fq = _generate_followup(sym, condition)
        s["pending_followups"].append({"symptom": sym, **fq})

    if s["pending_followups"]:
        s["stage"] = "followups"
        return _next_followup(session_id, s)

    return _go_to_medications(session_id, s)


def _next_followup(session_id: str, s: dict) -> dict:
    current = s["pending_followups"].pop(0)
    s["current_followup"] = current
    return _turn(
        session_id,
        current["question"],
        "chips_single",
        stage="followups",
        options=current["options"] + ["Skip"],
        allow_text=True,
        placeholder="Or describe in your own words...",
    )


def _go_to_medications(session_id: str, s: dict) -> dict:
    patient = s["patient"]
    meds = patient.get("medications", [])
    sym_ack = (
        "Symptoms logged: " + ", ".join(s["collected"]["symptoms_today"]) + "."
        if s["collected"]["symptoms_today"]
        else "Good to hear you're feeling well today."
    )
    note = s.pop("symptom_text_note", None)
    if note:
        sym_ack = sym_ack + " " + note

    if not meds:
        s["stage"] = "food"
        return _turn(
            session_id,
            [sym_ack, "Did you eat any of these today? Tap all that apply."],
            "chips_multi",
            stage="food",
            options=["None of these"] + FOOD_TRIGGERS,
            allow_text=True,
            placeholder="Anything else...",
        )

    s["stage"] = "medications"
    med_chips = [_med_label(m) for m in meds]
    return _turn(
        session_id,
        [sym_ack, "Which medications did you take today? Tap each one you took."],
        "chips_multi",
        stage="medications",
        options=["All taken", "All missed"] + med_chips,
        allow_text=False,
    )


def _build_confirm_summary(s: dict) -> str:
    col = s["collected"]
    patient = s["patient"]
    condition = patient.get("condition", "IBD")
    try:
        parts = []
        if col["symptoms_today"]:
            parts.append(f"Symptoms: {', '.join(col['symptoms_today'])}")
        else:
            parts.append("No symptoms today")
        meds = patient.get("medications", [])
        if meds:
            taken = sum(1 for k, v in col["medications_taken"].items() if v == "taken")
            parts.append(f"Medications: {taken}/{len(meds)} taken")
        if col["food_today"]:
            parts.append(f"Food triggers: {', '.join(col['food_today'])}")
        if col["sleep_hours"] is not None:
            parts.append(f"Sleep: {col['sleep_hours']:.0f}h")
        if col["bm_count"] is not None:
            parts.append(f"Bowel movements: {col['bm_count']}")
        parts.append(f"Stress: {col['stress_level']}/10")
        if col["exercise"] and col["exercise"] != "None":
            parts.append(f"Exercise: {col['exercise']}")
        summary_input = (
            f"Patient has {condition}. Today's log: {'; '.join(parts)}. "
            f"Notes: {col['notes'] or 'none'}."
        )
        return complete_text(_CONFIRM_SYSTEM, summary_input)
    except Exception:
        parts = []
        if col["symptoms_today"]:
            parts.append(f"Symptoms: {', '.join(col['symptoms_today'])}")
        else:
            parts.append("No symptoms today")
        parts.append(f"Stress: {col['stress_level']}/10")
        return " | ".join(parts)


def _return_to_confirm(session_id: str, s: dict) -> dict:
    """After editing a single section, jump straight back to the confirm screen
    instead of walking the patient through the rest of the check-in again."""
    s.pop("editing", None)
    s.pop("current_followup", None)
    s["pending_followups"] = []
    summary = _build_confirm_summary(s)
    s["stage"] = "confirm"
    return _turn(
        session_id,
        [summary,
         "Updated. Does that look right? Tap \"Looks good, save it\" to save, "
         "or \"Edit something\" to change something else."],
        "confirm",
        stage="confirm",
        options=["Confirm"],
        allow_text=True,
    )


def _handle_edit_request(session_id: str, s: dict, section: str) -> dict:
    patient = s["patient"]
    meds = patient.get("medications", [])
    col = s["collected"]
    # Mark this as a targeted edit: once the chosen section is re-collected, the
    # stage handlers route back to confirm rather than continuing the full flow.
    s["editing"] = True

    if "symptom" in section or "how" in section:
        s["stage"] = "symptoms"
        ordered = s.get("ordered_symptoms", [])
        chip_options = ["Feeling well today"] + [x["name"] for x in ordered]
        return _turn(
            session_id,
            "Let's redo symptoms. Tap all that apply.",
            "chips_multi",
            stage="symptoms",
            options=chip_options,
            allow_text=True,
            placeholder="Describe anything else...",
        )
    if "med" in section:
        s["stage"] = "medications"
        if not meds:
            s["stage"] = "food"
            return _turn(session_id, "No medications on file. Let's redo food.", "chips_multi",
                         stage="food", options=["None of these"] + FOOD_TRIGGERS, allow_text=True)
        return _turn(session_id, "Let's redo medications.", "chips_multi",
                     stage="medications",
                     options=["All taken", "All missed"] + [_med_label(m) for m in meds])
    if "food" in section or "eat" in section:
        s["stage"] = "food"
        return _turn(session_id, "Let's redo food triggers.", "chips_multi",
                     stage="food", options=["None of these"] + FOOD_TRIGGERS, allow_text=True)
    if "sleep" in section:
        s["stage"] = "sleep"
        return _turn(session_id, "Let's redo sleep.", "chips_single",
                     stage="sleep", options=SLEEP_OPTIONS)
    if "stress" in section:
        s["stage"] = "stress"
        return _turn(session_id, "Let's redo stress.", "scale",
                     stage="stress", options=STRESS_OPTIONS, scale=STRESS_SCALE)
    if "exercise" in section or "workout" in section:
        s["stage"] = "exercise"
        return _turn(session_id, "Let's redo exercise.", "chips_single",
                     stage="exercise", options=EXERCISE_OPTIONS)
    if "note" in section:
        s["stage"] = "notes"
        return _turn(session_id, "Update your notes:", "text",
                     stage="notes", allow_text=True,
                     placeholder="Optional notes...", options=["Skip"])

    # Unknown section — re-show confirm
    summary = _build_confirm_summary(s)
    return _turn(
        session_id,
        ["I didn't catch which section. Here's your summary again.", summary,
         "Tap \"Looks good, save it\" to save, or \"Edit something\" to make a change."],
        "confirm",
        stage="confirm",
        options=["Confirm"],
        allow_text=True,
    )
