"""Targeted edits to a single section must return to confirm, not re-walk the flow.

Regression test for: clicking Edit -> Symptoms (or any section) used to march the
patient back through medications, food, sleep, stress, etc. all over again.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agents"))
sys.path.insert(0, str(ROOT / "data"))

import journal_agent as ja  # noqa: E402


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    """Stub every LLM call so the test is hermetic and fast."""
    monkeypatch.setattr(ja, "complete_text", lambda *a, **k: "Summary of your day.")
    monkeypatch.setattr(ja, "complete_json", lambda *a, **k: {"question": "How severe?"})
    monkeypatch.setattr(ja, "clarify_symptom_text",
                        lambda *a, **k: {"is_relevant": True, "needs_clarification": False,
                                         "parsed_symptoms": [], "question": None, "options": []})


def _session_at_confirm():
    """Build an in-memory session that already reached the confirm stage."""
    sid = "j_test"
    ja.JOURNAL_SESSIONS[sid] = {
        "patient_id": "p1",
        "patient": {"condition": "ulcerative colitis",
                    "medications": [{"name": "Mesalamine"}, {"name": "Prednisone"}]},
        "stage": "confirm",
        "ordered_symptoms": [{"name": "Diarrhea"}, {"name": "Fatigue"}, {"name": "Abdominal pain"}],
        "collected": {
            "symptoms_today": ["Fatigue"],
            "symptom_details": {},
            "medications_taken": {"Mesalamine": "taken", "Prednisone": "taken"},
            "food_today": ["Dairy"],
            "sleep_hours": 7.0,
            "bm_count": 2,
            "exercise": "Light walk",
            "stress_level": 5,
            "notes": "",
        },
        "pending_followups": [],
    }
    return sid


def _open_edit_menu(sid):
    turn = ja.handle_journal_message(sid, "edit", [])
    assert turn["input"]["stage"] == "edit_menu"
    return turn


# (edit menu label, the chip the UI sends, the answer for that section's input)
CASES = [
    ("Symptoms", ["Diarrhea"], None),
    ("Medications", ["All taken"], None),
    ("Food", ["Spicy Food"], None),
    ("Sleep", ["8h"], None),
    ("Stress", ["8"], None),
    ("Exercise", ["Moderate"], None),
]


@pytest.mark.parametrize("label,answer_selected,_", CASES)
def test_edit_section_returns_to_confirm(label, answer_selected, _):
    sid = _session_at_confirm()
    _open_edit_menu(sid)

    # Pick the section from the edit menu (single-select chip -> sent as text).
    redo = ja.handle_journal_message(sid, label, [])
    assert ja.JOURNAL_SESSIONS[sid].get("editing") is True
    # We should be asked to redo exactly that one section, not be at confirm yet.
    assert redo["input"]["stage"] != "confirm"

    # Answer that one section.
    after = ja.handle_journal_message(sid, "", answer_selected)

    # The whole point: we land straight back on confirm, flow not continued.
    assert after["input"]["stage"] == "confirm", (
        f"editing {label} should return to confirm, got {after['input']['stage']}"
    )
    assert after["input"]["kind"] == "confirm"
    assert ja.JOURNAL_SESSIONS[sid].get("editing") is None


def test_edit_symptoms_keeps_new_selection():
    sid = _session_at_confirm()
    _open_edit_menu(sid)
    ja.handle_journal_message(sid, "Symptoms", [])
    ja.handle_journal_message(sid, "", ["Diarrhea", "Abdominal pain"])
    col = ja.JOURNAL_SESSIONS[sid]["collected"]
    assert set(col["symptoms_today"]) == {"Diarrhea", "Abdominal pain"}


def test_edit_notes_returns_to_confirm():
    sid = _session_at_confirm()
    _open_edit_menu(sid)
    ja.handle_journal_message(sid, "Notes", [])
    after = ja.handle_journal_message(sid, "Felt better after lunch", [])
    assert after["input"]["stage"] == "confirm"
    assert ja.JOURNAL_SESSIONS[sid]["collected"]["notes"] == "Felt better after lunch"
    assert ja.JOURNAL_SESSIONS[sid].get("editing") is None
