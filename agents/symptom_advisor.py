"""Symptom advisor for the daily check-in.

Three functions:
  generate_symptom_prompt  -- LLM greeting personalized to patient history
  clarify_symptom_text     -- LLM parse/clarify free-text symptom input
  build_ordered_symptoms   -- pure Python chip ordering with frequency badges
"""
from __future__ import annotations

import re

from _base import complete_json

CONDITION_TYPICAL: dict[str, list[str]] = {
    "ulcerative colitis": [
        "Urgency", "Rectal pain", "Bloody stools", "Cramping", "Mucus in stool",
    ],
    "crohn's disease": [
        "Perianal pain", "Mouth sores", "Fistula symptoms", "Weight loss", "Night sweats",
    ],
    "celiac disease": [
        "Brain fog", "Bone pain", "Dermatitis herpetiformis", "Anemia", "Joint pain",
    ],
}

_FREQ_THRESHOLD = 1.0

_PROMPT_SYSTEM = """\
You are a warm, supportive health assistant helping a patient log their daily GI symptoms.
Write ONE short, friendly check-in sentence (max ~25 words).
If a first name is provided, address the patient by their first name.
If recent or prior symptoms are provided, acknowledge ONLY the single top one by name with brief
encouragement. Never list more than one symptom and never repeat a symptom.
Do NOT ask the patient to describe how they feel, do NOT ask them to report or list symptoms, and
do NOT tell them to tap or select anything; a separate instruction handles that.
Do not use em dashes. If no history is provided, use a friendly generic opener.
Return JSON only: {"message": "..."}
"""

_CLARIFY_SYSTEM = """\
You help patients log symptoms in a GI health journal. When a patient types a free-text description,
determine if it is health-related, then either map it to specific canonical symptom names or ask ONE
brief clarifying question if too vague.

Canonical symptom names: Fatigue, Abdominal pain, Cramping, Bloating, Diarrhea, Constipation,
Nausea, Vomiting, Urgency, Rectal pain, Bloody stools, Mucus in stool, Joint pain, Brain fog,
Loss of appetite, Weight loss, Night sweats, Fever, Mouth sores, Skin rash, Headache, Anxiety.

Rules:
- Set is_relevant=false for: random text, gibberish, greetings, off-topic sentences (e.g. "pizza",
  "hello", "I like dogs", "asdf", profanity, questions about something other than their health).
- Set is_relevant=true for anything describing a physical or mental health experience, even vaguely.
- "tired", "exhausted", "low energy" -> ["Fatigue"] (no clarification)
- "stomach hurts", "stomach is bothering me" -> vague, ask: "Is that more cramping, bloating, or sharp pain?"
- "joint aches", "joints hurt" -> ["Joint pain"] (no clarification)
- "foggy", "can't think straight", "brain fog" -> ["Brain fog"] (no clarification)
- "achy" or "pain" without location -> vague, ask for location
- If clearly mappable or an obvious synonym, return directly without clarification
- Provide 2-4 short option chips when asking for clarification

Return JSON only:
{
  "is_relevant": true or false,
  "needs_clarification": true or false,
  "question": "string or null",
  "options": ["option1", "option2"] or [],
  "parsed_symptoms": ["Canonical Symptom Name"] or []
}
"""


def generate_symptom_prompt(
    patient: dict,
    freq_scores: dict[str, float],
    yesterday_symptoms: list[str] | None = None,
) -> dict:
    """Return {"message": str} -- a single personalized check-in greeting.

    The greeting references at most one symptom (top recent, else yesterday's) so it
    never double-lists with the deterministic "Tap all symptoms" instruction that
    follows it in the chat. A separate prefix listing yesterday's symptoms is no
    longer prepended by the caller, the model folds that context in here.
    """
    full_name = (patient.get("name") or "").strip()
    first_name = full_name.split()[0] if full_name else ""
    GENERIC = (
        f"How are you feeling today, {first_name}?" if first_name
        else "How are you feeling today?"
    )
    condition = patient.get("condition", "GI condition")
    yesterday_symptoms = yesterday_symptoms or []
    if not freq_scores and not yesterday_symptoms:
        return {"message": GENERIC}

    lines = [f"Patient condition: {condition}"]
    if first_name:
        lines.append(f"Patient first name: {first_name}")
    if freq_scores:
        top = sorted(freq_scores.items(), key=lambda x: -x[1])[:3]
        top_str = ", ".join(f"{name} (score {score:.1f})" for name, score in top)
        lines.append(f"Most frequent recent symptoms (exponentially weighted): {top_str}")
    if yesterday_symptoms:
        lines.append(f"Yesterday they reported: {', '.join(yesterday_symptoms)}")
    lines.append("Generate a brief personalized check-in greeting.")

    try:
        result = complete_json(_PROMPT_SYSTEM, "\n".join(lines))
        msg = result.get("message") or GENERIC
    except Exception:
        msg = GENERIC
    # Belt-and-suspenders: strip any em/en dashes the model slips in.
    msg = re.sub(r"\s*[—–]\s*", ", ", msg).strip()
    return {"message": msg}


def clarify_symptom_text(
    text: str,
    condition: str,
    already_selected: list[str],
) -> dict:
    """Return {needs_clarification, question, options, parsed_symptoms}."""
    user_msg = (
        f"Patient condition: {condition}\n"
        f"Already selected today: {', '.join(already_selected) or 'none'}\n"
        f'Patient wrote: "{text}"\n'
        f"Parse or clarify."
    )
    try:
        result = complete_json(_CLARIFY_SYSTEM, user_msg)
    except Exception:
        return {"needs_clarification": False, "question": None, "options": [], "parsed_symptoms": []}
    return {
        "is_relevant": bool(result.get("is_relevant", True)),
        "needs_clarification": bool(result.get("needs_clarification", False)),
        "question": result.get("question") or None,
        "options": result.get("options") or [],
        "parsed_symptoms": result.get("parsed_symptoms") or [],
    }


def build_ordered_symptoms(patient: dict, freq_scores: dict[str, float]) -> list[dict]:
    """Return ordered chip list: frequent -> condition-typical -> other.

    Each item: {name: str, freq_badge: str, group: str}
    group is one of: "frequent", "condition_typical", "other"
    """
    condition = (patient.get("condition") or "").lower()
    symptoms_to_watch: list[str] = patient.get("symptoms_to_watch") or []
    typical_for_condition = CONDITION_TYPICAL.get(condition, [])

    added: set[str] = set()
    frequent: list[dict] = []
    condition_typical: list[dict] = []
    other: list[dict] = []

    # Sort symptoms_to_watch by their frequency score
    sorted_watch = sorted(
        [(s, freq_scores.get(s, 0.0)) for s in symptoms_to_watch],
        key=lambda x: -x[1],
    )
    for name, score in sorted_watch:
        if score >= _FREQ_THRESHOLD:
            badge = f"{max(1, round(score))} recent"
            frequent.append({"name": name, "freq_badge": badge, "group": "frequent"})
        else:
            other.append({"name": name, "freq_badge": "", "group": "other"})
        added.add(name)

    # Condition-typical symptoms not in symptoms_to_watch
    for name in typical_for_condition:
        if name not in added:
            condition_typical.append({"name": name, "freq_badge": "", "group": "condition_typical"})
            added.add(name)

    return frequent + condition_typical + other
