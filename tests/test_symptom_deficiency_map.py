"""Tests for symptom_deficiency_map: hint aggregation and red-flag detection."""

from symptom_deficiency_map import (
    SYMPTOM_CHECKLIST,
    SYMPTOM_DEFICIENCY_HINTS,
    RED_FLAG_KEYWORDS,
    deficiencies_for_symptoms,
    has_red_flag,
)


class TestDeficiencyAggregation:
    def test_single_symptom(self):
        weights = deficiencies_for_symptoms(["extreme fatigue"])
        assert weights == {"iron": 1, "b12": 1, "folate": 1, "vitamin_d": 1}

    def test_overlapping_symptoms_increment_shared_deficiency(self):
        # both name b12 -> count 2; iron only from fatigue -> count 1
        weights = deficiencies_for_symptoms(
            ["extreme fatigue", "tingling or numbness in hands or feet"]
        )
        assert weights["b12"] == 2
        assert weights["folate"] == 2
        assert weights["iron"] == 1

    def test_case_and_whitespace_insensitive(self):
        assert deficiencies_for_symptoms(["  EXTREME Fatigue "]) == deficiencies_for_symptoms(
            ["extreme fatigue"]
        )

    def test_unknown_symptom_ignored(self):
        assert deficiencies_for_symptoms(["sneezing"]) == {}

    def test_empty_list(self):
        assert deficiencies_for_symptoms([]) == {}


class TestRedFlags:
    def test_detects_checklist_red_flag(self):
        assert has_red_flag(["irregular heartbeat or palpitations"]) == [
            "irregular heartbeat or palpitations"
        ]

    def test_detects_free_text_variant(self):
        # Keyword matching: free-text phrasings escalate, not just the exact label.
        assert has_red_flag(["heart palpitations"]) == ["heart palpitations"]
        assert has_red_flag(["chest pain when walking"]) == ["chest pain when walking"]
        assert has_red_flag(["blood in stool"]) == ["blood in stool"]

    def test_no_red_flag(self):
        assert has_red_flag(["extreme fatigue"]) == []

    def test_red_flag_case_insensitive(self):
        assert has_red_flag(["Irregular Heartbeat OR Palpitations"]) == [
            "Irregular Heartbeat OR Palpitations"
        ]

    def test_empty(self):
        assert has_red_flag([]) == []


class TestDataIntegrity:
    def test_checklist_matches_hint_keys(self):
        assert SYMPTOM_CHECKLIST == list(SYMPTOM_DEFICIENCY_HINTS.keys())

    def test_red_flag_keywords_are_lowercase(self):
        # Matching lowercases the input, so keywords must be lowercase to ever fire.
        for kw in RED_FLAG_KEYWORDS:
            assert kw == kw.lower(), f"red-flag keyword not lowercase: {kw!r}"

    def test_checklist_palpitations_still_triggers(self):
        # The one checklist symptom that is also a red flag must still escalate.
        assert has_red_flag(["irregular heartbeat or palpitations"])

    def test_all_symptom_keys_lowercase(self):
        for key in SYMPTOM_DEFICIENCY_HINTS:
            assert key == key.lower()

    def test_no_empty_deficiency_lists(self):
        for symptom, defs in SYMPTOM_DEFICIENCY_HINTS.items():
            assert defs, f"empty deficiency list for {symptom!r}"
