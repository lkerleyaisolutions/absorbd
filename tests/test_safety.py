"""Tests for the DETERMINISTIC safety-critical logic of the Safety Agent.

The dose-vs-UL check is LLM/integration-tested via the demo; here we lock down the
red-flag escalation and the actionable-dose gate, which must be correct every time.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents"))

from safety import screen_red_flags, _is_actionable  # noqa: E402


class TestRedFlagEscalation:
    def test_palpitations_triggers_urgent(self):
        esc = screen_red_flags(["irregular heartbeat or palpitations"])
        assert esc["urgent"] is True
        assert esc["flags"] == ["irregular heartbeat or palpitations"]
        assert "seek medical care" in esc["message"].lower()

    def test_non_red_flag_symptoms_not_urgent(self):
        esc = screen_red_flags(["extreme fatigue", "bone pain or muscle cramps"])
        assert esc["urgent"] is False
        assert esc["flags"] == []
        assert esc["message"] == ""

    def test_empty_symptoms(self):
        esc = screen_red_flags([])
        assert esc["urgent"] is False

    def test_case_insensitive_red_flag(self):
        esc = screen_red_flags(["Irregular Heartbeat OR Palpitations"])
        assert esc["urgent"] is True


class TestRedFlagSource:
    """FIX #3: reported symptoms drive URGENT; the watch-list is a softer signal."""

    RED = "irregular heartbeat or palpitations"

    def test_reported_red_flag_is_urgent_source_reported(self):
        esc = screen_red_flags(symptoms=[], reported_symptoms=[self.RED])
        assert esc["urgent"] is True
        assert esc["source"] == "reported"
        assert "urgent" in esc["message"].lower()

    def test_watchlist_only_flag_is_not_urgent_source_watchlist(self):
        # On the doctor's watch-list but NOT reported today -> softer flag, not urgent.
        esc = screen_red_flags(symptoms=[self.RED], reported_symptoms=["mild fatigue"])
        assert esc["urgent"] is False
        assert esc["source"] == "watchlist"
        assert esc["flags"] == [self.RED]
        assert "watch-list" in esc["message"].lower()

    def test_reported_takes_precedence_over_watchlist(self):
        esc = screen_red_flags(symptoms=[self.RED], reported_symptoms=[self.RED])
        assert esc["urgent"] is True
        assert esc["source"] == "reported"

    def test_nothing_flagged_with_reported_present(self):
        esc = screen_red_flags(symptoms=["mild fatigue"], reported_symptoms=["mild fatigue"])
        assert esc["urgent"] is False
        assert esc["flags"] == []
        assert esc["source"] == "reported"

    def test_legacy_call_without_reported_defaults_to_reported_source(self):
        # Back-compat: callers that never tracked a watch-list still get urgent.
        esc = screen_red_flags([self.RED])
        assert esc["urgent"] is True
        assert esc["source"] == "reported"


class TestActionableDoseGate:
    def test_real_dose_is_actionable(self):
        assert _is_actionable("600-800 IU daily") is True
        assert _is_actionable("18 mg elemental iron daily") is True

    def test_deferral_phrases_not_actionable(self):
        assert _is_actionable("Discuss with clinician") is False
        assert _is_actionable("Monitor; no supplement unless advised") is False

    def test_empty_not_actionable(self):
        assert _is_actionable("") is False
        assert _is_actionable(None) is False
