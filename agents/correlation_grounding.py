"""Literature grounding for patient-data correlations (Foundry IQ).

The statistical engine (data/correlations.py) finds candidate factor->symptom
correlations in ONE patient's journal history. Those signals are personal and,
for "potential" findings, statistically weak. This module asks a separate
question for each finding: has anyone documented this relationship before?

For every finding we retrieve from the Foundry IQ knowledge base and then run a
grounded LLM verification that refuses to claim support the passages do not
actually contain. A confirmed-in-literature finding is kept and badged even when
our own sample is still small, because the relationship is shown to be real; more
patient data will later confirm it statistically.

This does NOT upgrade statistical confidence. Statistical tier and literature
support are two independent axes: "what this patient's data shows" vs. "what the
field has documented."
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _base import retrieve, grounded_context, complete_json, as_citation_ints  # noqa: E402

# Cap LLM verifications per request so a noisy patient cannot fan out unbounded
# model calls. Findings beyond this keep literature=None (not checked). Potential
# findings are grounded first (see ground_findings) because literature proof is
# what justifies keeping a statistically-weak signal.
MAX_GROUND = 20


def _factor_phrase(factor: str) -> str:
    if factor == "stress_level":
        return "psychological stress"
    if factor == "sleep_hours":
        return "sleep duration"
    if factor == "bm_count":
        return "bowel movement frequency"
    if factor == "exercise_active":
        return "physical activity (exercise)"
    if factor.startswith("missed_"):
        return f"missed doses of {factor[len('missed_'):]}"
    if factor.startswith("ate_"):
        return f"dietary intake of {factor[len('ate_'):]}"
    return factor.replace("_", " ")


def _direction_phrase(factor: str, direction: str) -> str:
    binary = factor.startswith("missed_") or factor.startswith("ate_")
    subject = "the factor being present" if binary else "higher levels of the factor"
    if direction == "positive":
        return f"{subject} coincides with MORE frequent symptoms"
    return f"{subject} coincides with LESS frequent symptoms"


def _query_for(factor: str, symptom: str, condition: str) -> str:
    return f"{_factor_phrase(factor)} association with {symptom} in {condition} inflammatory bowel disease"


def _pmid_from_url(url: str) -> str:
    if not url:
        return ""
    parts = [p for p in url.rstrip("/").split("/") if p]
    return parts[-1] if parts and parts[-1].isdigit() else ""


VERIFY_SYSTEM = """You check whether published evidence shows that a behavioral correlation
seen in ONE IBD patient's journal data is plausible, i.e. documented before in others. You
are given a CANDIDATE relationship (a factor, an observed direction, and a symptom) and
EVIDENCE passages from a medical knowledge base.

The patient's specific symptom (e.g. cramping, urgency, fatigue) is ONE manifestation of
IBD disease activity. So evidence that the factor influences IBD disease activity, flares,
relapse, symptoms, or this specific symptom ALL count as support for the relationship.

Set supported=true when the passages document that this factor affects IBD outcomes in a
direction consistent with the observation. Set supported=false ONLY when the passages do
not link this factor to IBD outcomes at all (off-topic or absent). Do not require the exact
symptom word to appear.

HARD RULES:
- Base the decision ONLY on the passages. Do NOT use any outside knowledge.
- When supported, cite the single best passage and quote from it. Never invent a source.

Return ONLY JSON:
{"supported":true|false,"claim":"<one-sentence paraphrase of what the evidence shows, or ''>","citation":<passage number or null>,"quote":"<short verbatim quote from the passage, or ''>"}"""


def ground_finding(finding, condition: str) -> None:
    """Attach a `literature` dict to one CorrelationFinding (mutates in place).

    literature = {"supported": bool, "claim", "source", "source_url", "pmid", "quote"}
    On any retrieval/parse failure, sets {"supported": False} so the field is always
    populated once checked.
    """
    query = _query_for(finding.factor, finding.symptom, condition)
    try:
        passages = retrieve(query, top=5)
    except Exception:
        finding.literature = {"supported": False}
        return

    if not passages:
        finding.literature = {"supported": False}
        return

    user = (
        "CANDIDATE RELATIONSHIP:\n"
        f"- Factor: {_factor_phrase(finding.factor)}\n"
        f"- Observed direction in patient data: {_direction_phrase(finding.factor, finding.direction)}\n"
        f"- Symptom/outcome: {finding.symptom}\n"
        f"- Timing: {finding.lag_label}\n"
        f"- Patient condition: {condition}\n\n"
        f"Question: does the literature below document that {_factor_phrase(finding.factor)} "
        f"is associated with {finding.symptom} in IBD, in the observed direction?\n\n"
        f"EVIDENCE PASSAGES:\n{grounded_context(passages)}"
    )

    try:
        verdict = complete_json(VERIFY_SYSTEM, user)
    except (json.JSONDecodeError, Exception):
        finding.literature = {"supported": False}
        return

    if not verdict.get("supported"):
        finding.literature = {"supported": False}
        return

    raw_cite = verdict.get("citation")
    cite_list = raw_cite if isinstance(raw_cite, list) else [raw_cite]
    cited = as_citation_ints(cite_list, len(passages))
    if not cited:
        # Claimed support but cited nothing valid -> do not fabricate a source.
        finding.literature = {"supported": False}
        return

    p = passages[cited[0] - 1]
    source = getattr(p, "source", "") or getattr(p, "title", "")
    source_url = getattr(p, "source_url", "") or ""
    finding.literature = {
        "supported": True,
        "claim": verdict.get("claim", ""),
        "quote": verdict.get("quote", ""),
        "source": source,
        "source_url": source_url,
        "pmid": _pmid_from_url(source_url),
    }


def ground_findings(
    findings: list,
    condition: str,
    max_ground: int = MAX_GROUND,
    include_potential: bool = False,
) -> list:
    """Ground findings against Foundry IQ. Returns the same list.

    By default (FIX #9) ONLY findings with tier == "significant" are grounded.
    These are the few that a doctor will act on, so grounding the ~20 "potential"
    signals one-by-one wastes sequential LLM calls. Pass include_potential=True to
    also ground "potential" findings (literature proof can justify keeping a
    statistically-weak signal); in that mode potential findings are grounded first
    so they are not starved by the call cap. MAX_GROUND remains a hard cap.
    """
    if include_potential:
        order = sorted(
            range(len(findings)),
            key=lambda i: 0 if findings[i].tier == "potential" else 1,
        )
    else:
        order = [i for i in range(len(findings)) if findings[i].tier == "significant"]
    for i in order[:max_ground]:
        ground_finding(findings[i], condition)
    return findings
