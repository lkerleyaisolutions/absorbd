"""Cross-patient data isolation tests for Foundry IQ retrieval.

The whole privacy guarantee rests on ONE thing: every call to `_base.retrieve()`
must send an OData filter that restricts results to the calling patient's own
uploaded chunks plus the shared general literature, and NEVER the whole index
(which would surface another patient's documents).

Two ways that guarantee can silently break, each covered here:
  1. The filter is omitted when no patient_id is supplied (fail-open).
  2. The `filter_add_on` kwarg name drifts from the SDK's `filterAddOn` REST field
     (the model accepts arbitrary kwargs, so a typo is dropped with no error).

These tests are hermetic: the KB client is monkeypatched, no Azure calls happen.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents"))

import _base


class _CapturingClient:
    """Stands in for the KnowledgeBaseRetrievalClient; records the request."""

    def __init__(self):
        self.request = None

    def retrieve(self, request):
        self.request = request

        class _Resp:
            references = []

        return _Resp()


def _captured_filter(monkeypatch, patient_id):
    """Run retrieve() with the KB client stubbed and return the OData filter that
    was actually placed on the outgoing knowledge-source params."""
    client = _CapturingClient()
    monkeypatch.setattr(_base, "kb_client", lambda: client)

    _base.retrieve("any query", top=4, patient_id=patient_id)

    params = client.request.knowledge_source_params[0]
    # SearchIndexKnowledgeSourceParams serializes to the REST shape; the filter
    # lives under the camelCase `filterAddOn` field. Reading it back through the
    # serialized form is exactly what gets sent on the wire.
    return params.as_dict().get("filterAddOn")


def test_filter_always_present_with_patient(monkeypatch):
    f = _captured_filter(monkeypatch, "patient-abc")
    assert f == "patient_id eq 'patient-abc' or patient_id eq null"


def test_filter_fails_closed_without_patient(monkeypatch):
    # No patient context must mean GENERAL LITERATURE ONLY, never the whole index.
    for pid in (None, ""):
        f = _captured_filter(monkeypatch, pid)
        assert f == "patient_id eq null", f"fail-open leak for patient_id={pid!r}"


def test_one_patient_id_never_appears_in_anothers_filter(monkeypatch):
    f = _captured_filter(monkeypatch, "alice-id")
    assert "alice-id" in f
    assert "bob-id" not in f


def test_odata_single_quote_is_escaped(monkeypatch):
    # A quote in the id must be escaped so it cannot break out of the literal and
    # alter the filter (OData injection that could widen the result set).
    f = _captured_filter(monkeypatch, "o'brien")
    assert f == "patient_id eq 'o''brien' or patient_id eq null"


def test_sdk_filter_field_name_contract():
    """Lock the SDK contract: the `filter_add_on` kwarg must serialize to the
    `filterAddOn` REST field. The model silently accepts unknown kwargs, so if a
    future SDK renames this field the filter would be dropped with no error and
    every patient would see every document. This test fails loudly if that drifts.
    """
    from azure.search.documents.knowledgebases.models import (
        SearchIndexKnowledgeSourceParams,
    )

    p = SearchIndexKnowledgeSourceParams(
        knowledge_source_name="x",
        filter_add_on="patient_id eq null",
    )
    assert p.as_dict().get("filterAddOn") == "patient_id eq null"
