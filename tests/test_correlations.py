"""Unit tests for the statistical lag-correlation engine.

Uses synthetic in-memory data (mocked get_entries) to verify:
  - Planted correlations are detected and classified correctly
  - Random noise data does not produce false positives
  - Observation filter (min_obs=7) gates sparse factors
  - Confidence tiers (confirmed n>=30, emerging n=14-29) are assigned correctly
  - Helper functions (strength, factor_lag_type) return expected values
"""

import sys
import random
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))

from correlations import (
    CorrelationFinding,
    _factor_lag_type,
    _strength,
    _direction_flag,
    _partial_spearman,
    compute_lag_correlations,
    curated_patient_nudges,
)


def _make_finding(**kw):
    """Build a CorrelationFinding with sensible defaults for nudge/gate tests."""
    base = dict(
        factor="stress_level", symptom="Cramping", lag_days=1, correlation=0.5,
        p_adjusted=0.01, p_raw=0.001, n=40, strength="moderate",
        direction="positive", confidence="confirmed", tier="significant",
        lag_label="next day", direction_flag="expected", r_adjusted=0.4,
        confound_flag=False, literature=None,
    )
    base.update(kw)
    return CorrelationFinding(**base)


# ── Synthetic data factories ──────────────────────────────────────────────────

def _make_entry(d: str, stress: int, symptoms: list[str], food: list[str],
                sleep_h: float = 7.0, bm: int = 2, exercise: str = "None",
                missed_meds: list[str] | None = None) -> dict:
    meds = {"Mesalamine": "taken", "Prednisone": "taken"}
    if missed_meds:
        for m in missed_meds:
            meds[m] = "missed"
    return {
        "date": d,
        "symptoms_today": symptoms,
        "medications_taken": meds,
        "stress_level": stress,
        "notes": "",
        "extra": {
            "food_today": food,
            "sleep_hours": sleep_h,
            "bm_count": bm,
            "exercise": exercise,
        },
    }


def _dates(n: int, start_days_ago: int | None = None) -> list[str]:
    if start_days_ago is None:
        start_days_ago = n
    today = date.today()
    return [(today - timedelta(days=start_days_ago - i)).isoformat() for i in range(n)]


def _planted_stress_cramping(n: int = 62) -> list[dict]:
    """62 entries where stress>=7 yesterday -> Cramping today with 90% prob."""
    rng = random.Random(42)
    dates = _dates(n)
    entries = []
    for i, d in enumerate(dates):
        stress = rng.randint(1, 10)
        prev_stress = entries[-1]["stress_level"] if entries else 5
        cramping_prob = 0.90 if prev_stress >= 7 else 0.08
        symptoms = ["Cramping"] if rng.random() < cramping_prob else []
        if rng.random() < 0.7:
            symptoms.append("Fatigue")
        entries.append(_make_entry(d, stress, symptoms, []))
    return entries


def _random_noise(n: int = 62, seed: int = 99) -> list[dict]:
    """Pure random entries with no planted signal."""
    rng = random.Random(seed)
    dates = _dates(n)
    return [
        _make_entry(
            d,
            stress=rng.randint(1, 10),
            symptoms=rng.sample(["Cramping", "Fatigue", "Diarrhea", "Bloating"], k=rng.randint(0, 2)),
            food=rng.sample(["Dairy", "Spicy Food"], k=rng.randint(0, 1)),
            sleep_h=round(rng.uniform(5, 9), 1),
            bm=rng.randint(0, 5),
            exercise=rng.choice(["None", "Light walk", "Moderate"]),
        )
        for d in dates
    ]


# ── Pure helper function tests ────────────────────────────────────────────────

class TestStrength:
    def test_strong(self):
        assert _strength(0.75) == "strong"
        assert _strength(-0.65) == "strong"
        assert _strength(0.60) == "strong"

    def test_moderate(self):
        assert _strength(0.45) == "moderate"
        assert _strength(-0.30) == "moderate"

    def test_weak(self):
        assert _strength(0.10) == "weak"
        assert _strength(-0.05) == "weak"
        assert _strength(0.0) == "weak"

    def test_boundary_strong(self):
        # 0.6 should be strong (>= 0.6)
        assert _strength(0.6) == "strong"
        # Just below is moderate
        assert _strength(0.59) == "moderate"


class TestFactorLagType:
    def test_stress(self):
        assert _factor_lag_type("stress_level") == "stress"

    def test_missed_med(self):
        assert _factor_lag_type("missed_Mesalamine") == "missed"
        assert _factor_lag_type("missed_Azathioprine") == "missed"

    def test_food(self):
        assert _factor_lag_type("ate_Dairy") == "food"
        assert _factor_lag_type("ate_Spicy Food") == "food"

    def test_sleep(self):
        assert _factor_lag_type("sleep_hours") == "sleep"

    def test_exercise(self):
        assert _factor_lag_type("exercise_active") == "exercise"

    def test_bm(self):
        assert _factor_lag_type("bm_count") == "bm"


# ── Integration tests against synthetic data ──────────────────────────────────

class TestComputeLagCorrelations:
    def test_returns_empty_for_too_few_entries(self):
        entries = _planted_stress_cramping(n=10)
        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")
        assert result == []

    def test_planted_stress_cramping_detected(self):
        entries = _planted_stress_cramping(n=62)
        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")
        factors = [(f.factor, f.symptom, f.lag_days) for f in result]
        assert ("stress_level", "Cramping", 1) in factors, (
            f"Expected stress->Cramping lag-1 in findings: {factors}"
        )

    def test_planted_correlation_is_strong(self):
        entries = _planted_stress_cramping(n=62)
        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")
        hit = next((f for f in result if f.factor == "stress_level"
                    and f.symptom == "Cramping" and f.lag_days == 1), None)
        assert hit is not None
        assert abs(hit.correlation) >= 0.50, f"Expected r >= 0.50, got {hit.correlation}"
        assert hit.strength in ("moderate", "strong")

    def test_planted_correlation_is_confirmed(self):
        entries = _planted_stress_cramping(n=62)
        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")
        hit = next((f for f in result if f.factor == "stress_level"
                    and f.symptom == "Cramping" and f.lag_days == 1), None)
        assert hit is not None
        assert hit.confidence == "confirmed"
        assert hit.n >= 30

    def test_random_noise_produces_few_findings(self):
        entries = _random_noise(n=62, seed=99)
        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")
        # BH-FDR at alpha=0.10 on random data: expect at most ~10% false positives
        # With ~100 tests, that's at most ~10 false findings; realistic should be 0-3.
        assert len(result) <= 10, (
            f"Too many false positives from random data: {len(result)}"
        )

    def test_min_obs_filter_excludes_sparse_factor(self):
        """A food factor present on only 2 days should be skipped (< min_obs=7)."""
        rng = random.Random(1)
        dates = _dates(40)
        entries = []
        for i, d in enumerate(dates):
            food = ["Dairy"] if i in (5, 10) else []  # only 2 days have Dairy
            symptoms = ["Diarrhea"] if i in (6, 11) else []
            entries.append(_make_entry(d, stress=5, symptoms=symptoms, food=food))

        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")
        factors = [f.factor for f in result]
        # ate_Dairy should not appear because it's present only 2 days (< 7)
        assert "ate_Dairy" not in factors

    def test_emerging_confidence_for_small_n(self):
        """With exactly 20 entries and a planted signal, confidence should be 'emerging'."""
        rng = random.Random(7)
        dates = _dates(20)
        entries = []
        for i, d in enumerate(dates):
            stress = rng.randint(1, 10)
            prev_stress = entries[-1]["stress_level"] if entries else 5
            cramping_prob = 0.90 if prev_stress >= 7 else 0.05
            symptoms = ["Cramping"] if rng.random() < cramping_prob else []
            entries.append(_make_entry(d, stress=stress, symptoms=symptoms, food=[]))

        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")

        # If the correlation survived BH, it should be 'emerging' (n < 30)
        for f in result:
            if f.factor == "stress_level" and f.symptom == "Cramping" and f.lag_days == 1:
                assert f.confidence == "emerging", f"Expected emerging, got {f.confidence}"
                assert 14 <= f.n < 30

    def test_direction_positive_and_negative(self):
        """Verify direction field is set correctly."""
        dates = _dates(40)
        rng = random.Random(3)
        entries = []
        for i, d in enumerate(dates):
            stress = 9 if i % 2 == 0 else 2
            # stress and Fatigue are positively correlated same-day
            symptoms = ["Fatigue"] if stress >= 7 else []
            entries.append(_make_entry(d, stress=stress, symptoms=symptoms, food=[],
                                       sleep_h=9.0 if stress < 5 else 5.0))

        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")

        for f in result:
            if f.correlation > 0:
                assert f.direction == "positive"
            else:
                assert f.direction == "negative"

    def test_sorted_by_abs_correlation_descending(self):
        entries = _planted_stress_cramping(n=62)
        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")
        if len(result) >= 2:
            for i in range(len(result) - 1):
                if result[i].confidence == result[i + 1].confidence:
                    assert abs(result[i].correlation) >= abs(result[i + 1].correlation), (
                        f"Not sorted: idx {i} r={result[i].correlation} "
                        f"< idx {i+1} r={result[i+1].correlation}"
                    )

    def test_confirmed_before_emerging_in_sort(self):
        entries = _planted_stress_cramping(n=62)
        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")
        confidences = [f.confidence for f in result]
        # All 'confirmed' should appear before any 'emerging'
        seen_emerging = False
        for c in confidences:
            if c == "emerging":
                seen_emerging = True
            if seen_emerging and c == "confirmed":
                assert False, "Found 'confirmed' after 'emerging' in sort order"

    def test_lag_label_values(self):
        entries = _planted_stress_cramping(n=62)
        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")
        for f in result:
            expected = {0: "same day", 1: "next day", 2: "2 days later"}[f.lag_days]
            assert f.lag_label == expected, (
                f"lag_days={f.lag_days} should have lag_label='{expected}', got '{f.lag_label}'"
            )

    def test_all_findings_have_tier_and_praw(self):
        entries = _planted_stress_cramping(n=62)
        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")
        for f in result:
            assert f.tier in ("significant", "potential")
            assert isinstance(f.p_raw, float)

    def test_potential_findings_meet_floor(self):
        """Any 'potential' finding must clear the nominal-significance floor."""
        entries = _random_noise(n=62, seed=7)
        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")
        for f in result:
            if f.tier == "potential":
                assert abs(f.correlation) >= 0.25
                assert f.p_raw < 0.10

    def test_significant_sorted_before_potential(self):
        entries = _random_noise(n=62, seed=7)
        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")
        seen_potential = False
        for f in result:
            if f.tier == "potential":
                seen_potential = True
            elif seen_potential:
                assert False, "Found 'significant' after 'potential' in sort order"

    def test_strong_planted_signal_is_significant(self):
        entries = _planted_stress_cramping(n=62)
        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")
        hit = next((f for f in result if f.factor == "stress_level"
                    and f.symptom == "Cramping" and f.lag_days == 1), None)
        assert hit is not None
        assert hit.tier == "significant"

    def test_food_lag_is_only_lag1(self):
        """Food factors should only be tested at lag 1, not lag 0 or lag 2."""
        entries = _planted_stress_cramping(n=62)
        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")
        food_findings = [f for f in result if f.factor.startswith("ate_")]
        for f in food_findings:
            assert f.lag_days == 1, f"Food factor {f.factor} tested at lag {f.lag_days}, expected 1"

    def test_missed_med_lags_are_1_or_2(self):
        """Missed medication factors should only be tested at lags 1 and 2."""
        entries = _planted_stress_cramping(n=62)
        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")
        med_findings = [f for f in result if f.factor.startswith("missed_")]
        for f in med_findings:
            assert f.lag_days in (1, 2), (
                f"Missed-med factor {f.factor} tested at lag {f.lag_days}, expected 1 or 2"
            )


# ── FIX #2: direction-plausibility gate ───────────────────────────────────────

class TestDirectionFlag:
    def test_stress_positive_is_expected(self):
        assert _direction_flag("stress_level", 0.4) == "expected"

    def test_stress_negative_is_unexpected(self):
        # "more stress -> less fatigue" contradicts the mechanism
        assert _direction_flag("stress_level", -0.4) == "unexpected"

    def test_missed_med_negative_is_unexpected(self):
        # "missing immunosuppressant -> fewer symptoms" is the dangerous sign-flip
        assert _direction_flag("missed_Azathioprine", -0.42) == "unexpected"

    def test_missed_med_positive_is_expected(self):
        assert _direction_flag("missed_Azathioprine", 0.42) == "expected"

    def test_sleep_negative_is_expected(self):
        # more sleep -> fewer symptoms
        assert _direction_flag("sleep_hours", -0.5) == "expected"

    def test_sleep_positive_is_unexpected(self):
        assert _direction_flag("sleep_hours", 0.5) == "unexpected"

    def test_exercise_negative_is_expected(self):
        assert _direction_flag("exercise_active", -0.5) == "expected"

    def test_food_positive_is_expected(self):
        assert _direction_flag("ate_Dairy", 0.4) == "expected"

    def test_unknown_factor_is_expected(self):
        assert _direction_flag("something_unknown", -0.9) == "expected"

    def test_signflipped_input_is_demoted_out_of_significant(self):
        """A planted sign-flipped 'missing med -> fewer symptoms' relationship
        must never surface in the trustworthy 'significant' tier."""
        rng = random.Random(11)
        dates = _dates(62)
        entries = []
        for i, d in enumerate(dates):
            # On ~half the days the patient misses Azathioprine. We plant the
            # DANGEROUS inverse: when they miss it, they have FEWER symptoms.
            missed = (i % 2 == 0)
            prev_missed = (entries and entries[-1]["medications_taken"].get(
                "Azathioprine") == "missed")
            cramping = [] if prev_missed else (["Cramping"] if rng.random() < 0.9 else [])
            e = _make_entry(d, stress=5, symptoms=cramping, food=[],
                            missed_meds=["Azathioprine"] if missed else None)
            entries.append(e)

        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")

        for f in result:
            if f.factor == "missed_Azathioprine":
                # Either the correlation is in the expected direction, or if it is
                # the dangerous inverse it must be flagged and NOT significant.
                if f.direction_flag == "unexpected":
                    assert f.tier != "significant", (
                        "sign-flipped missed-med finding must not be 'significant'"
                    )

    def test_findings_carry_direction_flag(self):
        entries = _planted_stress_cramping(n=62)
        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")
        assert result, "expected at least one finding"
        for f in result:
            assert f.direction_flag in ("expected", "unexpected")


# ── FIX #5: partial-correlation / activity-confounder fields ───────────────────

class TestPartialCorrelationFields:
    def test_fields_exist_on_findings(self):
        entries = _planted_stress_cramping(n=62)
        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")
        assert result
        for f in result:
            assert hasattr(f, "r_adjusted")
            assert hasattr(f, "confound_flag")
            assert f.r_adjusted is None or isinstance(f.r_adjusted, float)
            assert isinstance(f.confound_flag, bool)

    def test_bm_count_has_no_self_adjustment(self):
        """bm_count is the activity proxy, so it must not be partialled on itself."""
        entries = _random_noise(n=62, seed=3)
        with patch("correlations.get_entries", return_value=entries):
            result = compute_lag_correlations("patient_x")
        for f in result:
            if f.factor == "bm_count":
                assert f.r_adjusted is None

    def test_partial_spearman_drops_shared_confound(self):
        """When x and y are correlated only through a shared confounder, the
        partial correlation collapses toward zero."""
        rng = random.Random(5)
        control = [rng.gauss(0, 1) for _ in range(60)]
        # x and y both driven by `control` plus independent noise -> no direct link
        x = [c + rng.gauss(0, 0.3) for c in control]
        y = [c + rng.gauss(0, 0.3) for c in control]
        partial = _partial_spearman(x, y, control)
        assert partial is not None
        assert abs(partial) < 0.4, f"expected near-zero partial, got {partial}"

    def test_partial_spearman_preserves_direct_link(self):
        """A genuine x->y link not explained by the control survives."""
        rng = random.Random(6)
        control = [rng.gauss(0, 1) for _ in range(60)]
        x = [rng.gauss(0, 1) for _ in range(60)]
        y = [xi * 0.9 + rng.gauss(0, 0.2) for xi in x]  # y driven by x, not control
        partial = _partial_spearman(x, y, control)
        assert partial is not None
        assert abs(partial) > 0.6, f"expected strong partial, got {partial}"


# ── FIX #10: curated patient-safe nudges ──────────────────────────────────────

class TestCuratedPatientNudges:
    def test_clean_significant_supported_finding_produces_nudge(self):
        f = _make_finding(factor="stress_level", symptom="Fatigue",
                          literature={"supported": True})
        nudges = curated_patient_nudges([f])
        assert len(nudges) == 1
        n = nudges[0]
        assert set(n.keys()) == {"text", "strength_label", "factor", "symptom"}
        assert n["factor"] == "stress_level"
        assert n["symptom"] == "Fatigue"
        assert n["strength_label"] in ("strong", "moderate", "mild")
        # No raw numbers leak into patient text.
        assert "0." not in n["text"]
        assert "r=" not in n["text"]

    def test_clean_finding_without_literature_still_produces_nudge(self):
        f = _make_finding(factor="stress_level", symptom="Cramping", literature=None)
        assert len(curated_patient_nudges([f])) == 1

    def test_signflipped_finding_never_produces_nudge(self):
        # An "unexpected" direction finding must be excluded.
        f = _make_finding(factor="missed_Azathioprine", symptom="Cramping",
                          correlation=-0.42, direction="negative",
                          direction_flag="unexpected", tier="potential")
        assert curated_patient_nudges([f]) == []

    def test_missed_med_even_if_expected_never_nudges(self):
        # Even a mechanistically-"expected" missed-med finding must not become a
        # patient nudge (no adherence messaging from this engine).
        f = _make_finding(factor="missed_Mesalamine", symptom="Cramping",
                          correlation=0.42, direction="positive",
                          direction_flag="expected", tier="significant",
                          literature={"supported": True})
        assert curated_patient_nudges([f]) == []

    def test_potential_tier_excluded(self):
        f = _make_finding(tier="potential")
        assert curated_patient_nudges([f]) == []

    def test_confounded_finding_excluded(self):
        f = _make_finding(confound_flag=True)
        assert curated_patient_nudges([f]) == []

    def test_unsupported_literature_excluded(self):
        f = _make_finding(literature={"supported": False})
        assert curated_patient_nudges([f]) == []

    def test_strength_label_is_qualitative(self):
        strong = _make_finding(correlation=0.7, symptom="Cramping")
        mild = _make_finding(correlation=0.27, symptom="Cramping")
        assert curated_patient_nudges([strong])[0]["strength_label"] == "strong"
        assert curated_patient_nudges([mild])[0]["strength_label"] == "mild"
