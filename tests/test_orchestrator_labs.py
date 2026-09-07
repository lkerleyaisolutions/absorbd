"""Tests for the DETERMINISTIC lab-driven logic owned by the analysis pipeline.

These cover the pure-code helpers (no Azure / LLM):
  - active_inflammation computation (FIX #1)
  - iron_route IV-vs-oral decision (FIX #1)
  - prepare_profile surfacing reported_symptoms + active_inflammation
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data" / "intake"))

from orchestrator import (  # noqa: E402
    compute_active_inflammation,
    iron_route,
    prepare_profile,
)


def _lab(test_name, value, status, unit="", days_ago=0):
    return {
        "test_name": test_name,
        "value": value,
        "unit": unit,
        "status": status,
        "test_date": (date.today() - timedelta(days=days_ago)).isoformat(),
        "confirmed": True,
    }


class TestActiveInflammation:
    def test_crp_high_is_active(self):
        assert compute_active_inflammation([_lab("CRP", 12, "HIGH", "mg/L")]) is True

    def test_fecal_calprotectin_high_is_active(self):
        assert compute_active_inflammation([_lab("Fecal Calprotectin", 400, "HIGH")]) is True

    def test_calprotectin_high_is_active(self):
        assert compute_active_inflammation([_lab("Calprotectin", 300, "HIGH")]) is True

    def test_crp_normal_is_not_active(self):
        assert compute_active_inflammation([_lab("CRP", 2, "NORMAL")]) is False

    def test_unrelated_high_lab_is_not_active(self):
        assert compute_active_inflammation([_lab("Ferritin", 6, "HIGH")]) is False

    def test_empty_or_none(self):
        assert compute_active_inflammation([]) is False
        assert compute_active_inflammation(None) is False

    def test_case_insensitive_test_name(self):
        assert compute_active_inflammation([_lab("crp", 9, "high")]) is True


class TestIronRoute:
    def test_iv_preferred_when_ferritin_low_value_and_flare(self):
        labs = [_lab("Ferritin", 8, "LOW", "ng/mL"), _lab("CRP", 12, "HIGH")]
        route, rationale = iron_route(labs, active_inflammation=True)
        assert route == "iv_preferred"
        assert rationale and "iv iron" in rationale.lower()

    def test_iv_preferred_when_ferritin_status_low_and_flare(self):
        # value field present but parseable as >=15, status LOW still triggers.
        labs = [_lab("Ferritin", 20, "LOW", "ng/mL")]
        route, rationale = iron_route(labs, active_inflammation=True)
        assert route == "iv_preferred"

    def test_value_under_15_triggers_even_if_status_blank(self):
        labs = [_lab("Ferritin", 9, "", "ng/mL")]
        route, _ = iron_route(labs, active_inflammation=True)
        assert route == "iv_preferred"

    def test_oral_when_no_flare(self):
        labs = [_lab("Ferritin", 6, "LOW", "ng/mL")]
        route, rationale = iron_route(labs, active_inflammation=False)
        assert route == "oral"
        assert rationale is None

    def test_oral_when_ferritin_adequate_in_flare(self):
        labs = [_lab("Ferritin", 80, "NORMAL", "ng/mL"), _lab("CRP", 12, "HIGH")]
        route, rationale = iron_route(labs, active_inflammation=True)
        assert route == "oral"
        assert rationale is None

    def test_oral_when_no_ferritin_present(self):
        labs = [_lab("CRP", 12, "HIGH")]
        route, _ = iron_route(labs, active_inflammation=True)
        assert route == "oral"


class TestPrepareProfile:
    def test_active_inflammation_attached(self):
        raw = {"condition": "ulcerative colitis", "lab_values": [_lab("CRP", 12, "HIGH")]}
        prof = prepare_profile(raw)
        assert prof["active_inflammation"] is True

    def test_reported_symptoms_passthrough(self):
        raw = {"reported_symptoms": ["palpitations"], "symptoms": ["fatigue"]}
        prof = prepare_profile(raw)
        assert prof["reported_symptoms"] == ["palpitations"]
        assert prof["symptoms"] == ["fatigue"]

    def test_defaults_when_absent(self):
        prof = prepare_profile({})
        assert prof["active_inflammation"] is False
        assert prof["reported_symptoms"] == []
