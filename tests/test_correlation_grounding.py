"""Unit tests for Foundry IQ literature grounding of correlations.

The KB retrieval and LLM verification are monkeypatched, so these tests are
hermetic (no Azure calls) and assert the grounding/keep logic only.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents"))

from correlations import CorrelationFinding
import correlation_grounding as cg


@dataclass
class FakePassage:
    title: str = ""
    source: str = ""
    source_url: str = ""


def _finding(factor="stress_level", symptom="Cramping", direction="positive"):
    return CorrelationFinding(
        factor=factor, symptom=symptom, lag_days=1, correlation=0.42,
        p_adjusted=0.2, p_raw=0.04, n=20, strength="moderate",
        direction=direction, confidence="emerging", tier="potential",
        lag_label="next day",
    )


def test_supported_attaches_proof(monkeypatch):
    passage = FakePassage(
        title="Perceived stress and disease activity in ulcerative colitis",
        source="Clin Gastroenterol Hepatol 2023 — Sauk et al. (PMID 35952942)",
        source_url="https://pubmed.ncbi.nlm.nih.gov/35952942/",
    )
    monkeypatch.setattr(cg, "retrieve", lambda *a, **k: [passage])
    monkeypatch.setattr(cg, "grounded_context", lambda passages: "P1: stress raises flare odds")
    monkeypatch.setattr(cg, "complete_json", lambda system, user: {
        "supported": True,
        "claim": "Higher perceived stress raises UC flare odds.",
        "citation": 1,
        "quote": "OR 3.6 for flare",
    })

    f = _finding()
    cg.ground_finding(f, "ulcerative colitis")
    assert f.literature["supported"] is True
    assert f.literature["pmid"] == "35952942"
    assert "Sauk" in f.literature["source"]
    assert f.literature["quote"] == "OR 3.6 for flare"


def test_unsupported_sets_false(monkeypatch):
    monkeypatch.setattr(cg, "retrieve", lambda *a, **k: [FakePassage(title="unrelated")])
    monkeypatch.setattr(cg, "grounded_context", lambda passages: "P1: unrelated text")
    monkeypatch.setattr(cg, "complete_json", lambda system, user: {
        "supported": False, "claim": "", "citation": None, "quote": "",
    })

    f = _finding()
    cg.ground_finding(f, "ulcerative colitis")
    assert f.literature == {"supported": False}


def test_no_passages_sets_false(monkeypatch):
    monkeypatch.setattr(cg, "retrieve", lambda *a, **k: [])
    f = _finding()
    cg.ground_finding(f, "ulcerative colitis")
    assert f.literature == {"supported": False}


def test_supported_but_no_valid_citation_does_not_fabricate(monkeypatch):
    monkeypatch.setattr(cg, "retrieve", lambda *a, **k: [FakePassage(title="x")])
    monkeypatch.setattr(cg, "grounded_context", lambda passages: "P1: x")
    # Claims support but cites an out-of-range passage -> must not fabricate a source.
    monkeypatch.setattr(cg, "complete_json", lambda system, user: {
        "supported": True, "claim": "c", "citation": 9, "quote": "q",
    })
    f = _finding()
    cg.ground_finding(f, "ulcerative colitis")
    assert f.literature == {"supported": False}


def test_retrieve_error_is_safe(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kb down")
    monkeypatch.setattr(cg, "retrieve", boom)
    f = _finding()
    cg.ground_finding(f, "ulcerative colitis")
    assert f.literature == {"supported": False}


def _sig_finding(**kw):
    f = _finding(**{k: v for k, v in kw.items() if k in ("factor", "symptom", "direction")})
    f.tier = "significant"
    return f


def test_ground_findings_caps_calls(monkeypatch):
    calls = {"n": 0}

    def counting_retrieve(*a, **k):
        calls["n"] += 1
        return []
    monkeypatch.setattr(cg, "retrieve", counting_retrieve)

    # All significant so the default (significant-only) gate does not filter them.
    findings = [_sig_finding() for _ in range(20)]
    cg.ground_findings(findings, "ulcerative colitis", max_ground=5)
    assert calls["n"] == 5


def test_ground_findings_grounds_only_significant_by_default(monkeypatch):
    """FIX #9: by default only tier=='significant' findings are grounded."""
    calls = {"n": 0}

    def counting_retrieve(*a, **k):
        calls["n"] += 1
        return []
    monkeypatch.setattr(cg, "retrieve", counting_retrieve)

    findings = [_finding() for _ in range(5)]          # all "potential"
    findings += [_sig_finding() for _ in range(3)]     # 3 significant
    cg.ground_findings(findings, "ulcerative colitis")
    assert calls["n"] == 3
    # The potential findings were never checked.
    assert all(f.literature is None for f in findings if f.tier == "potential")


def test_ground_findings_include_potential_flag(monkeypatch):
    """include_potential=True restores grounding of potential findings."""
    calls = {"n": 0}

    def counting_retrieve(*a, **k):
        calls["n"] += 1
        return []
    monkeypatch.setattr(cg, "retrieve", counting_retrieve)

    findings = [_finding() for _ in range(4)] + [_sig_finding() for _ in range(2)]
    cg.ground_findings(findings, "ulcerative colitis", include_potential=True)
    assert calls["n"] == 6
