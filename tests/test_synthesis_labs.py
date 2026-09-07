"""Tests for FIX #6 time-aware NORMAL-lab handling in the Synthesis Agent.

Pure deterministic logic (no LLM): a recent in-range lab downgrades a nutrient to
GREEN (monitor only); a stale in-range lab does NOT suppress it but attaches a note
that the reading is old. LOW/HIGH labs are untouched here.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents"))

from _base import Trace  # noqa: E402
from synthesis import (  # noqa: E402
    LAB_RECENT_DAYS,
    _apply_normal_lab_handling,
    _normal_lab_for,
    _days_since,
)


def _lab(test_name, value, status, unit="ng/mL", days_ago=0):
    return {
        "test_name": test_name,
        "value": value,
        "unit": unit,
        "status": status,
        "test_date": (date.today() - timedelta(days=days_ago)).isoformat(),
    }


def _nutrient(name, priority="RED"):
    return {"nutrient": name, "priority": priority, "rationale": "converging pathways"}


class TestDaysSince:
    def test_parses_iso(self):
        assert _days_since((date.today() - timedelta(days=30)).isoformat()) == 30

    def test_unparseable_is_none(self):
        assert _days_since("not-a-date") is None
        assert _days_since("") is None


class TestNormalLabMatch:
    def test_matches_folate_to_folate_lab(self):
        labs = [_lab("Folate", 4.1, "NORMAL", days_ago=18)]
        assert _normal_lab_for("Folate", labs) is not None

    def test_matches_iron_to_ferritin(self):
        labs = [_lab("Ferritin", 90, "NORMAL", days_ago=10)]
        assert _normal_lab_for("Iron", labs) is not None

    def test_low_lab_not_returned(self):
        labs = [_lab("Folate", 2.0, "LOW", days_ago=10)]
        assert _normal_lab_for("Folate", labs) is None

    def test_prefers_most_recent_normal(self):
        labs = [
            _lab("Folate", 3.0, "NORMAL", days_ago=200),
            _lab("Folate", 4.1, "NORMAL", days_ago=18),
        ]
        chosen = _normal_lab_for("Folate", labs)
        assert chosen["value"] == 4.1


class TestRecentNormalDowngrade:
    def test_recent_normal_downgrades_to_green(self):
        n = _nutrient("Folate", priority="RED")
        labs = [_lab("Folate", 4.1, "NORMAL", days_ago=18)]
        _apply_normal_lab_handling(n, labs, Trace())
        assert n["priority"] == "GREEN"
        assert n["lab_recent"] is True
        assert n["lab_note"] is None
        assert "in range" in n["rationale"].lower()
        assert "4.1" in n["rationale"]

    def test_boundary_recent(self):
        n = _nutrient("Folate")
        labs = [_lab("Folate", 4.1, "NORMAL", days_ago=LAB_RECENT_DAYS)]
        _apply_normal_lab_handling(n, labs, Trace())
        assert n["priority"] == "GREEN"
        assert n["lab_recent"] is True


class TestStaleNormalKept:
    def test_stale_normal_keeps_priority_and_notes(self):
        n = _nutrient("Folate", priority="RED")
        labs = [_lab("Folate", 4.1, "NORMAL", days_ago=210)]
        _apply_normal_lab_handling(n, labs, Trace())
        assert n["priority"] == "RED"  # NOT suppressed
        assert n["lab_recent"] is False
        assert n["lab_note"] is not None
        assert "4.1" in n["lab_note"]
        assert "210 days ago" in n["lab_note"]

    def test_just_over_boundary_is_stale(self):
        n = _nutrient("Folate", priority="YELLOW")
        labs = [_lab("Folate", 4.1, "NORMAL", days_ago=LAB_RECENT_DAYS + 1)]
        _apply_normal_lab_handling(n, labs, Trace())
        assert n["priority"] == "YELLOW"
        assert n["lab_recent"] is False
        assert n["lab_note"] is not None


class TestNoNormalLab:
    def test_no_matching_lab_leaves_priority_and_nulls(self):
        n = _nutrient("Iron", priority="RED")
        labs = [_lab("Folate", 4.1, "NORMAL", days_ago=10)]
        _apply_normal_lab_handling(n, labs, Trace())
        assert n["priority"] == "RED"
        assert n["lab_recent"] is None
        assert n["lab_note"] is None

    def test_low_lab_does_not_downgrade(self):
        n = _nutrient("Iron", priority="RED")
        labs = [_lab("Ferritin", 6, "LOW", days_ago=5)]
        _apply_normal_lab_handling(n, labs, Trace())
        assert n["priority"] == "RED"
        assert n["lab_recent"] is None
