"""Tests for the DETERMINISTIC topic selection of the Doctor Guide Agent.

Priority order matters (a red flag must outrank a routine nutrient question), so it
is locked down here. The LLM phrasing is integration-tested via the demo.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents"))

from doctor_guide import select_topics, MAX_QUESTIONS  # noqa: E402


def _synth(nutrients):
    return {"nutrients": nutrients}


def _safety(escalation, checked):
    return {"escalation": escalation, "checked_protocol": checked}


NO_ESC = {"urgent": False, "flags": [], "message": ""}
URGENT = {"urgent": True, "flags": ["irregular heartbeat or palpitations"], "message": "x"}


class TestPriorityOrder:
    def test_escalation_comes_first(self):
        synth = _synth([{"nutrient": "Vitamin D", "rationale": "r"}])
        safety = _safety(URGENT, [{"nutrient": "Vitamin D", "priority": "RED", "safety_status": "ok"}])
        topics = select_topics(synth, safety)
        assert topics[0]["kind"] == "escalation"
        assert topics[0]["nutrient"] == "urgent"

    def test_capped_outranks_plain_red(self):
        synth = _synth([{"nutrient": "Iron", "rationale": "r"}, {"nutrient": "Vitamin D", "rationale": "r"}])
        safety = _safety(NO_ESC, [
            {"nutrient": "Vitamin D", "priority": "RED", "safety_status": "ok"},
            {"nutrient": "Iron", "priority": "YELLOW", "safety_status": "capped", "upper_limit": "45 mg"},
        ])
        topics = select_topics(synth, safety)
        assert topics[0]["nutrient"] == "Iron"        # capped first
        assert topics[0]["kind"] == "capped"

    def test_unverified_included_when_room(self):
        synth = _synth([])
        safety = _safety(NO_ESC, [
            {"nutrient": "Vitamin B12", "priority": "YELLOW", "safety_status": "ul_unknown",
             "safety_note": "no UL"},
        ])
        topics = select_topics(synth, safety)
        assert any(t["nutrient"] == "Vitamin B12" and t["kind"] == "needs_confirmation" for t in topics)


class TestDedupAndCap:
    def test_capped_takes_precedence_over_red_for_same_nutrient(self):
        synth = _synth([{"nutrient": "Iron", "rationale": "r"}])
        safety = _safety(NO_ESC, [
            {"nutrient": "Iron", "priority": "RED", "safety_status": "capped", "upper_limit": "45 mg"},
        ])
        topics = select_topics(synth, safety)
        iron_topics = [t for t in topics if t["nutrient"] == "Iron"]
        assert len(iron_topics) == 1            # not duplicated as both capped and high_priority
        assert iron_topics[0]["kind"] == "capped"

    def test_capped_at_most_max_questions(self):
        synth = _synth([])
        checked = [
            {"nutrient": f"N{i}", "priority": "RED", "safety_status": "capped", "upper_limit": "x"}
            for i in range(6)
        ]
        topics = select_topics(synth, _safety(NO_ESC, checked))
        assert len(topics) == MAX_QUESTIONS

    def test_empty_pipeline_no_topics(self):
        assert select_topics(_synth([]), _safety(NO_ESC, [])) == []
