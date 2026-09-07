"""Tests for medication_map.normalize_medication and the MEDICATION_MAP table."""

import pytest

from medication_map import MEDICATION_MAP, normalize_medication


class TestExactMatch:
    def test_brand_resolves_to_generic(self):
        assert normalize_medication("Humira") == "adalimumab"
        assert normalize_medication("Remicade") == "infliximab"
        assert normalize_medication("Entyvio") == "vedolizumab"

    def test_generic_resolves_to_itself(self):
        assert normalize_medication("adalimumab") == "adalimumab"
        assert normalize_medication("mesalamine") == "mesalamine"

    def test_case_insensitive(self):
        assert normalize_medication("HUMIRA") == "adalimumab"
        assert normalize_medication("hUmIrA") == "adalimumab"

    def test_whitespace_stripped(self):
        assert normalize_medication("  Humira  ") == "adalimumab"

    def test_multiword_brand(self):
        assert normalize_medication("Asacol HD") == "mesalamine"
        assert normalize_medication("Entocort EC") == "budesonide"


class TestFreeformInput:
    def test_dose_suffix_still_resolves(self):
        # The documented use case: "I take Humira 40mg" -> adalimumab
        assert normalize_medication("I take Humira 40mg") == "adalimumab"

    def test_sentence_with_brand(self):
        assert normalize_medication("currently on Stelara injections") == "ustekinumab"


class TestUnknownAndEmpty:
    def test_unknown_returns_none(self):
        assert normalize_medication("aspirin") is None
        assert normalize_medication("tylenol") is None

    def test_empty_returns_none(self):
        assert normalize_medication("") is None

    def test_none_input_returns_none(self):
        assert normalize_medication(None) is None


class TestTableIntegrity:
    def test_all_keys_lowercase(self):
        for key in MEDICATION_MAP:
            assert key == key.lower(), f"key not lowercase: {key!r}"

    def test_every_generic_is_self_mapping(self):
        # Each generic value must itself be a key resolving to itself, so the
        # Medication Interaction Agent can key on it directly.
        for generic in set(MEDICATION_MAP.values()):
            assert generic in MEDICATION_MAP, f"generic missing self-map: {generic!r}"
            assert MEDICATION_MAP[generic] == generic

    def test_no_empty_values(self):
        for key, value in MEDICATION_MAP.items():
            assert value, f"empty mapping for {key!r}"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("xeljanz", "tofacitinib"),
        ("rinvoq", "upadacitinib"),
        ("imuran", "azathioprine"),
        ("6-mp", "mercaptopurine"),
        ("prednisolone", "prednisone"),
        ("questran", "cholestyramine"),
    ],
)
def test_representative_mappings(raw, expected):
    assert normalize_medication(raw) == expected
