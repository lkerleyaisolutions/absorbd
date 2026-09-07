"""Tests for the DETERMINISTIC layer of the Synthesis Agent (merge/canonicalize).

The LLM triage layer is not unit-tested here (it's an integration concern); these
tests lock down the parts that must be provably correct: nutrient canonicalization,
grouping, convergence counting, and the fallback priority.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents"))

from synthesis import (  # noqa: E402
    canonicalize,
    normalize_contributions,
    merge,
    Contribution,
)


class TestCanonicalize:
    def test_vitamin_d_variants_merge(self):
        for v in ["Vitamin D", "vitamin d", "vitamin_d", "  VITAMIN  D ", "vit d"]:
            assert canonicalize(v) == "Vitamin D"

    def test_b12_variants(self):
        for v in ["B12", "vitamin b12", "Vitamin B12", "cobalamin"]:
            assert canonicalize(v) == "Vitamin B12"

    def test_folate_synonyms(self):
        for v in ["folate", "folic acid", "vitamin b9"]:
            assert canonicalize(v) == "Folate"

    def test_unknown_nutrient_titlecased_not_dropped(self):
        assert canonicalize("selenium") == "Selenium"

    def test_empty(self):
        assert canonicalize("") == ""
        assert canonicalize(None) == ""


def _finding(nutrient, sources=None, **extra):
    f = {"nutrient": nutrient, "sources": sources or [], "verified_quote": "q"}
    f.update(extra)
    return f


class TestMergeAndConvergence:
    def setup_method(self):
        self.med = {"results": [{"medication": "prednisone", "findings": [
            _finding("vitamin D", ["u1"], effect="impairs absorption", mechanism="x"),
            _finding("calcium", ["u1"], effect="impairs absorption", mechanism="y"),
        ]}]}
        self.defc = {"results": [{"focus": "ulcerative colitis", "findings": [
            _finding("Vitamin D", ["u2"], rationale="malabsorption"),
            _finding("iron", ["u3"], rationale="blood loss"),
        ]}]}
        self.diet = {"results": [{"restriction": "vegan", "findings": [
            _finding("vitamin_d", ["u2"], rationale="no fortified dairy"),
            _finding("Vitamin B12", ["u4"], rationale="animal foods only"),
        ]}]}

    def test_all_findings_flattened(self):
        contribs = normalize_contributions(self.med, self.defc, self.diet)
        assert len(contribs) == 6

    def test_vitamin_d_converges_from_three_pathways(self):
        merged = merge(normalize_contributions(self.med, self.defc, self.diet))
        vd = next(m for m in merged if m.nutrient == "Vitamin D")
        assert vd.convergence == 3  # prednisone + condition + diet
        assert {c.origin_type for c in vd.contributions} == {"medication", "condition", "diet"}

    def test_sorted_by_convergence_desc(self):
        merged = merge(normalize_contributions(self.med, self.defc, self.diet))
        assert merged[0].nutrient == "Vitamin D"  # highest convergence first
        assert merged[0].convergence == 3

    def test_sources_aggregated_and_deduped(self):
        merged = merge(normalize_contributions(self.med, self.defc, self.diet))
        vd = next(m for m in merged if m.nutrient == "Vitamin D")
        assert vd.sources == ["u1", "u2"]  # u2 appears twice, deduped

    def test_default_priority_convergence(self):
        merged = merge(normalize_contributions(self.med, self.defc, self.diet))
        vd = next(m for m in merged if m.nutrient == "Vitamin D")
        assert vd.default_priority() == "RED"  # convergence >= 2

    def test_single_medication_pathway_is_yellow(self):
        merged = merge(normalize_contributions(self.med, {}, {}))
        cal = next(m for m in merged if m.nutrient == "Calcium")
        assert cal.convergence == 1
        assert cal.default_priority() == "YELLOW"

    def test_same_origin_not_double_counted(self):
        # same nutrient from the same medication twice = convergence 1, not 2
        med = {"results": [{"medication": "prednisone", "findings": [
            _finding("vitamin D", ["a"]), _finding("Vitamin D", ["b"]),
        ]}]}
        merged = merge(normalize_contributions(med, {}, {}))
        vd = merged[0]
        assert vd.convergence == 1
        assert len(vd.contributions) == 2


def test_empty_inputs():
    assert merge(normalize_contributions({}, {}, {})) == []
