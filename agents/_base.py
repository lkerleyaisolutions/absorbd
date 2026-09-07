"""Shared foundation for Absorbd agents.

Two capabilities every reasoning agent needs:
  - a chat model (gpt-4.1-mini via the Azure OpenAI v1 endpoint, API-key auth)
  - grounded retrieval from the Foundry IQ knowledge base (admin-key auth)

Both use credentials already proven working in .env, so agents run with NO
`az login` required. The agent runtime can later be switched to the hosted MCP
tool, but the retrieval contract (query -> grounded passages + citations) is the
same.
"""

from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# --- model ---
AOAI_ENDPOINT_V1 = os.environ["AZURE_OPENAI_ENDPOINT"]      # .../openai/v1
AOAI_API_KEY = os.environ["AZURE_AI_PROJECT_API_KEY"]
MODEL_DEPLOYMENT = os.environ["MODEL_DEPLOYMENT"]            # gpt-4.1-mini

# --- knowledge base ---
SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
SEARCH_KEY = os.environ["AZURE_SEARCH_KEY"]
KNOWLEDGE_BASE_NAME = os.environ.get("KNOWLEDGE_BASE_NAME", "absorb-iq-kb")
KNOWLEDGE_SOURCE_NAME = "absorb-iq-index-source"

# Clinical output must be deterministic and reproducible.
TEMPERATURE = 0.0
REQUEST_TIMEOUT = 60  # seconds

_model_client = None       # reused across calls (avoids per-call client churn)
_kb_client = None


def model_client():
    """Cached OpenAI client for the Azure OpenAI v1 endpoint."""
    global _model_client
    if _model_client is None:
        from openai import OpenAI

        _model_client = OpenAI(
            base_url=AOAI_ENDPOINT_V1, api_key=AOAI_API_KEY, timeout=REQUEST_TIMEOUT
        )
    return _model_client


def complete_json(system: str, user: str) -> dict:
    """Deterministic model call that returns parsed JSON (best-effort, robust)."""
    resp = model_client().responses.create(
        model=MODEL_DEPLOYMENT,
        instructions=system,
        input=user,
        temperature=TEMPERATURE,
    )
    return _parse_json(resp.output_text)


def complete_text(system: str, user: str) -> str:
    resp = model_client().responses.create(
        model=MODEL_DEPLOYMENT,
        instructions=system,
        input=user,
        temperature=TEMPERATURE,
    )
    return (resp.output_text or "").strip()


def _parse_json(text: str) -> dict:
    """Parse model JSON, tolerating ```json fences and surrounding prose."""
    text = (text or "").strip()
    if "```" in text:
        # take the content of the first fenced block
        parts = text.split("```")
        if len(parts) >= 2:
            block = parts[1]
            if block.lstrip().lower().startswith("json"):
                block = block.lstrip()[4:]
            text = block.strip()
    # fall back to the outermost {...} if there is still surrounding text
    if not text.startswith("{"):
        a, b = text.find("{"), text.rfind("}")
        if a != -1 and b != -1 and b > a:
            text = text[a : b + 1]
    return json.loads(text)


def as_citation_ints(values, max_n: int) -> list[int]:
    """Coerce model-supplied citation numbers to valid ints in [1, max_n].

    LLMs sometimes return citations as strings ("1") or out-of-range numbers;
    this never raises and silently drops anything invalid.
    """
    out: list[int] = []
    for v in values or []:
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= max_n:
            out.append(n)
    return out


@dataclass
class TraceEvent:
    """One step of an agent's visible reasoning, for SSE streaming + demos."""
    agent: str
    step: str
    detail: str


class Trace:
    """Collects (and optionally live-streams) an agent's reasoning steps."""

    def __init__(self, on_event: Optional[Callable[[TraceEvent], None]] = None):
        self.events: list[TraceEvent] = []
        self._on_event = on_event

    def emit(self, agent: str, step: str, detail: str) -> None:
        ev = TraceEvent(agent, step, detail)
        self.events.append(ev)
        if self._on_event:
            self._on_event(ev)


@dataclass
class Passage:
    """One retrieved, citable evidence passage."""
    title: str
    content: str
    source: str
    source_url: str

    def cite(self, n: int) -> str:
        return f"[{n}] {self.title} ({self.source_url})"


def kb_client():
    """Cached Foundry IQ retrieval client (reused; closed via close_clients())."""
    global _kb_client
    if _kb_client is None:
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents.knowledgebases import KnowledgeBaseRetrievalClient

        # NOTE (security TODO #3): this uses the SEARCH ADMIN key. Retrieval only
        # needs read access — switch to a query key before any public deployment.
        _kb_client = KnowledgeBaseRetrievalClient(
            endpoint=SEARCH_ENDPOINT,
            credential=AzureKeyCredential(SEARCH_KEY),
            knowledge_base_name=KNOWLEDGE_BASE_NAME,
        )
    return _kb_client


def retrieve(query: str, top: int = 8, patient_id: str | None = None) -> list[Passage]:
    """Ask the Foundry IQ knowledge base and return grounded, citable passages.

    Deduplicates near-identical passages (the KB can return overlapping chunks)
    so the model doesn't reason over the same evidence twice.
    """
    from azure.search.documents.knowledgebases.models import (
        KnowledgeBaseRetrievalRequest,
        KnowledgeRetrievalSemanticIntent,
        SearchIndexKnowledgeSourceParams,
    )

    kb_params_kwargs: dict = {
        "knowledge_source_name": KNOWLEDGE_SOURCE_NAME,
        "include_references": True,
        "include_reference_source_data": True,
    }

    # Per-patient isolation, enforced FAIL-CLOSED. Every retrieval is filtered:
    #   - with a patient_id: that patient's own uploaded chunks (patient_id eq 'X')
    #     blended with the shared general literature (patient_id eq null)
    #   - without a patient_id: general literature ONLY (patient_id eq null)
    # A missing/blank patient_id must NEVER widen the search to the whole index,
    # which would surface ANOTHER patient's uploaded documents. Absence of an id is
    # treated as "no patient context", not "all patients" — security depends on this
    # filter always being present, so it is set unconditionally below.
    if patient_id:
        safe_id = patient_id.replace("'", "''")  # OData single-quote escaping
        kb_params_kwargs["filter_add_on"] = (
            f"patient_id eq '{safe_id}' or patient_id eq null"
        )
    else:
        kb_params_kwargs["filter_add_on"] = "patient_id eq null"

    request = KnowledgeBaseRetrievalRequest(
        intents=[KnowledgeRetrievalSemanticIntent(search=query)],
        knowledge_source_params=[SearchIndexKnowledgeSourceParams(**kb_params_kwargs)],
    )
    resp = kb_client().retrieve(request)

    passages: list[Passage] = []
    seen: set[str] = set()
    for ref in resp.references or []:
        data = getattr(ref, "source_data", None) or {}
        if not isinstance(data, dict):
            continue
        content = data.get("content", "")
        if not content:
            continue
        fingerprint = content[:120].strip().lower()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        passages.append(
            Passage(
                title=data.get("title", ""),
                content=content,
                source=data.get("source", ""),
                source_url=data.get("source_url", ""),
            )
        )
        if len(passages) >= top:
            break
    return passages


def close_clients() -> None:
    """Close cached Azure/OpenAI clients. Call at process shutdown."""
    global _kb_client, _model_client
    if _kb_client is not None:
        _kb_client.close()
        _kb_client = None
    if _model_client is not None:
        try:
            _model_client.close()
        except Exception:
            pass
        _model_client = None


def grounded_context(passages: list[Passage]) -> str:
    """Format passages as a numbered evidence block for a prompt."""
    blocks = []
    for i, p in enumerate(passages, 1):
        blocks.append(f"[{i}] {p.title}\nSource: {p.source_url}\n{p.content}")
    return "\n\n".join(blocks)


# --- Shared multi-step grounded reasoning (PLAN -> RETRIEVE -> ANALYZE -> VERIFY) ---
#
# Every reasoning agent (medication interaction, deficiency hypothesis, dietary gap)
# follows the same shape: reason about what to look for, retrieve evidence, extract
# candidate findings grounded ONLY in that evidence, then adversarially verify each
# finding against its citation. This helper implements that once so each agent is a
# thin wrapper supplying only its domain prompts. Every finding the agent emits is
# verified and carries a source URL + the exact supporting quote.

VERIFY_SYSTEM = """You are an adversarial verifier for a clinical nutrition system.
For each candidate finding, decide whether the CITED evidence passages EXPLICITLY
support it. Be strict: if the passages do not clearly state the claim, mark
supported=false. Default to false when uncertain.

Return ONLY JSON:
{"verdicts":[{"index":<i>,"supported":true|false,"quote":"<exact supporting sentence or empty>"}]}"""


def _render_claim(finding: dict) -> str:
    return "; ".join(f"{k}: {v}" for k, v in finding.items() if k != "citations")


def verify_findings(agent: str, subject: str, candidates: list[dict],
                    passages: list[Passage], trace: "Trace") -> list[dict]:
    """Adversarial groundedness check. Keeps only findings the evidence supports,
    attaching the source URL(s) and the verifying quote to each survivor."""
    if not candidates:
        return []
    lines = []
    for i, f in enumerate(candidates):
        cited = as_citation_ints(f.get("citations", []), len(passages))
        evidence = "\n".join(f"  [{n}] {passages[n - 1].content}" for n in cited) or "  (no valid citation)"
        lines.append(f"Finding {i}: {_render_claim(f)}\n  cited evidence:\n{evidence}")
    try:
        result = complete_json(VERIFY_SYSTEM, "\n\n".join(lines))
        verdicts = {v["index"]: v for v in result.get("verdicts", []) if "index" in v}
    except Exception:
        # Fail CLOSED: if the verifier errors (bad JSON or a transient model/network
        # failure), no verdicts means every finding is rejected. The system refuses
        # to assert rather than risk an unverified medical claim.
        verdicts = {}

    verified = []
    for i, f in enumerate(candidates):
        v = verdicts.get(i, {})
        label = f.get("nutrient", f"finding {i}")
        if bool(v.get("supported")):
            cited = as_citation_ints(f.get("citations", []), len(passages))
            f["sources"] = sorted({passages[n - 1].source_url for n in cited})
            f["verified_quote"] = v.get("quote", "")
            verified.append(f)
            trace.emit(agent, "verify", f"VERIFIED {subject} -> {label}")
        else:
            trace.emit(agent, "verify", f"REJECTED {subject} -> {label} (evidence insufficient)")
    return verified


def run_grounded_reasoning(agent: str, subject: str, condition: str,
                           plan_system: str, analyze_system: str, analyze_header: str,
                           trace: "Trace", extra: str = "", top: int = 8,
                           patient_id: str | None = None) -> list[dict]:
    """PLAN -> RETRIEVE -> ANALYZE -> VERIFY -> CONCLUDE. Returns verified findings.

    The analyze prompt must return {"findings":[{..., "citations":[ints]}]}.
    When patient_id is provided, retrieval blends patient-specific document chunks
    (uploaded lab PDFs, clinical notes) with general clinical literature.
    """
    # 1. PLAN
    plan_input = f"Subject: {subject}\nPatient condition: {condition}"
    if extra:
        plan_input += f"\n{extra}"
    try:
        plan = complete_json(plan_system, plan_input)
    except Exception:
        # Malformed JSON or a transient model/network error: fall back to a
        # default query rather than killing the whole agent run.
        plan = {}
    query = plan.get("search_query") or f"{subject} {condition} nutrient"
    trace.emit(agent, "plan", f"{subject}: {plan.get('reasoning', query)}")

    # 2. RETRIEVE (blends patient docs + general literature when patient_id is set)
    passages = retrieve(query, top=top, patient_id=patient_id or None)
    trace.emit(agent, "retrieve", f"{subject}: {len(passages)} evidence passages")
    if not passages:
        trace.emit(agent, "conclude", f"{subject}: no grounded evidence; nothing asserted")
        return []

    # 3. ANALYZE
    user = f"{analyze_header}\nCONDITION: {condition}\n"
    if extra:
        user += f"{extra}\n"
    user += f"\nEVIDENCE PASSAGES:\n{grounded_context(passages)}"
    try:
        candidates = complete_json(analyze_system, user).get("findings", [])
    except Exception:
        # Don't let a single bad model response abort the agent; emit nothing
        # rather than fabricating. Empty candidates -> no findings asserted.
        candidates = []
    trace.emit(agent, "analyze", f"{subject}: {len(candidates)} candidate(s) before verification")

    # 4. VERIFY  5. CONCLUDE
    verified = verify_findings(agent, subject, candidates, passages, trace)
    trace.emit(agent, "conclude", f"{subject}: {len(verified)} verified finding(s)")
    return verified
