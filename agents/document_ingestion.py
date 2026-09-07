"""Document ingestion pipeline for patient-uploaded PDFs.

Flow:
  1. pdfplumber  -> page-aware text + table extraction
  2. LLM         -> structured extraction (doc-type aware: labs vs clinical narrative)
  3. DB          -> patient_documents + lab_values rows
  4. ingestion   -> chunk + embed + upload to Azure Search (patient_id tagged)
  5. DB          -> mark document indexed

Exposes: ingest_document(patient_id, filepath, doc_type) -> dict
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "data"))

from _base import complete_json  # noqa: E402
from ingestion import IngestDoc, ingest  # noqa: E402
from journal import add_document, add_lab_values, mark_document_indexed  # noqa: E402

# Doc types that contain numeric lab values worth extracting
_LAB_DOC_TYPES = {"lab_results", "stool_test", "bone_density", "pathology"}

# How many pages to send for LLM extraction (labs rarely span > 8 pages)
_MAX_EXTRACTION_PAGES = 8
# Max chars of prose text per page in the extraction payload
_MAX_TEXT_PER_PAGE = 3500
# Max chars of table content per page in the extraction payload
_MAX_TABLE_PER_PAGE = 2000


# ---------------------------------------------------------------------------
# Extraction prompts
# ---------------------------------------------------------------------------

_LAB_EXTRACTION_SYSTEM = """You are a medical document parser specializing in extracting laboratory results from clinical PDFs.

The document is presented page-by-page. Tables are rendered as pipe-delimited rows inside [TABLE] markers — pay close attention to these because labs are almost always in table format.

Extract ALL numeric lab values you can find. Return ONLY valid JSON:
{
  "lab_values": [
    {
      "test_name": "Ferritin",
      "value": "8",
      "unit": "ng/mL",
      "reference_range": "20-250",
      "status": "LOW",
      "test_date": "2026-05-01"
    }
  ],
  "summary": "Brief 1-2 sentence description of the document content"
}

Rules:
- status must be exactly "LOW", "NORMAL", or "HIGH"
  - Infer from a flag in the row (H/HH/High = HIGH, L/LL/Low/A = LOW, or compare value to reference range)
  - If genuinely unclear, use "NORMAL"
- test_date: ISO format YYYY-MM-DD; use "" if not determinable
- reference_range: use "" if not shown in the document
- value: numeric string only, no units (e.g. "8.2" not "8.2 ng/mL")
- Normalize test names to standard form:
    Hgb / Hb -> Hemoglobin
    Hct -> Hematocrit
    25-OH Vit D / 25(OH)D -> Vitamin D
    Fe / Serum Iron -> Iron
    TIBC / Total Iron Binding Capacity -> TIBC
    Plt -> Platelets
    CRP / hsCRP -> CRP
    Calprotectin / Fecal Calprotectin -> Calprotectin
- Only include values where you can read a clear numeric result
- IBD-priority tests: Ferritin, Hemoglobin, Hematocrit, Vitamin D, B12, Folate, CRP, ESR,
  Albumin, Iron, TIBC, Zinc, Magnesium, Calcium, Potassium, Calprotectin, Platelets, WBC
"""

_CLINICAL_EXTRACTION_SYSTEM = """You are a medical document parser. This document is a clinical note, colonoscopy/endoscopy report, pathology report, operative note, prescription, or similar narrative record.

Summarize the key clinical findings. Return ONLY valid JSON:
{
  "lab_values": [],
  "summary": "2-3 sentence summary covering: procedure or document type, key findings or impressions, any relevant grades/scores/measurements (e.g. Mayo score, inflammation extent, biopsy results, medication details)"
}
"""


# ---------------------------------------------------------------------------
# PDF content extraction
# ---------------------------------------------------------------------------

def _format_table(table: list[list]) -> str:
    """Render a pdfplumber table as a pipe-delimited string."""
    rows = []
    for row in table:
        cells = [str(c or "").strip().replace("\n", " ") for c in row]
        rows.append(" | ".join(cells))
    return "\n".join(rows)


def _extract_pages(filepath: str | Path) -> list[dict]:
    """Extract text and tables from each PDF page.

    Returns a list of {page_num, text, tables} dicts.
    Falls back to a single error entry if pdfplumber fails.
    """
    try:
        import pdfplumber
    except ImportError:
        return [{"page_num": 1, "text": "[pdfplumber not installed]", "tables": []}]

    try:
        pages = []
        with pdfplumber.open(str(filepath)) as pdf:
            for i, page in enumerate(pdf.pages):
                text = (page.extract_text() or "").strip()
                raw_tables = page.extract_tables() or []
                tables = [_format_table(t) for t in raw_tables if t]
                pages.append({"page_num": i + 1, "text": text, "tables": tables})
        return pages
    except Exception as e:
        return [{"page_num": 1, "text": f"[PDF extraction failed: {e}]", "tables": []}]


def _build_extraction_payload(pages: list[dict]) -> str:
    """Build the text blob to send to the LLM for structured extraction.

    Includes page markers, prose text, and table blocks.
    Capped to _MAX_EXTRACTION_PAGES to keep the prompt within reason.
    """
    parts = []
    for page in pages[:_MAX_EXTRACTION_PAGES]:
        pn = page["page_num"]
        section = [f"--- PAGE {pn} ---"]
        if page["text"]:
            section.append(page["text"][:_MAX_TEXT_PER_PAGE])
        for t in page["tables"]:
            if t.strip():
                section.append(f"[TABLE]\n{t[:_MAX_TABLE_PER_PAGE]}\n[/TABLE]")
        if len(section) > 1:
            parts.append("\n".join(section))
    return "\n\n".join(parts)


def _build_full_text(pages: list[dict]) -> str:
    """Build the complete document text for Azure Search chunking.

    Includes page markers so each chunk carries page provenance.
    Tables are included inline so retrieval can surface structured values.
    """
    parts = []
    for page in pages:
        pn = page["page_num"]
        lines = [f"[Page {pn}]"]
        if page["text"]:
            lines.append(page["text"])
        for t in page["tables"]:
            if t.strip():
                lines.append(f"[Table]\n{t}\n[/Table]")
        if len(lines) > 1:
            parts.append("\n".join(lines))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------

def _extract_structured(pages: list[dict], doc_type: str) -> tuple[list[dict], str]:
    """Run LLM extraction on the page content.

    Returns (lab_values, summary). lab_values is empty for non-lab doc types.
    """
    system = _LAB_EXTRACTION_SYSTEM if doc_type in _LAB_DOC_TYPES else _CLINICAL_EXTRACTION_SYSTEM
    payload = _build_extraction_payload(pages)
    if not payload.strip():
        return [], ""
    try:
        result = complete_json(system, payload)
        return result.get("lab_values", []), result.get("summary", "")
    except Exception:
        return [], ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_document(
    patient_id: str,
    filepath: str | Path,
    doc_type: str,
    file_hash: str = "",
) -> dict:
    """Full pipeline: PDF -> extracted lab values (unconfirmed) + Azure Search chunks.

    Returns {document_id, lab_values_extracted: list, chunks_indexed: int}.
    The caller (doctor UI) must POST /patient/confirm-lab-values to commit lab values.
    """
    filepath = Path(filepath)
    filename = filepath.name

    # 1. Page-aware text + table extraction
    pages = _extract_pages(filepath)

    # 2. LLM extraction (doc-type aware)
    lab_values, summary = _extract_structured(pages, doc_type)

    # 3. Save document record (indexed=0 until Azure Search upload completes)
    doc_id = add_document(patient_id, filename, doc_type, file_hash=file_hash)

    # 4. Save unconfirmed lab values for doctor review
    if lab_values:
        add_lab_values(patient_id, doc_id, lab_values)

    # 5. Chunk + embed + upload to Azure Search
    chunks_indexed = 0
    extraction_ok = pages and not pages[0]["text"].startswith("[PDF extraction failed")
    if extraction_ok:
        full_text = _build_full_text(pages)
        if full_text.strip():
            doc = IngestDoc(
                content=full_text,
                title=filename,
                source=f"patient_doc:{doc_id}",
                source_url="",
                doc_type=doc_type,
                patient_id=patient_id,
                key_parts=(patient_id, doc_id),
            )
            try:
                records = ingest([doc])
                chunks_indexed = len(records)
            except Exception:
                chunks_indexed = 0

    # 6. Mark indexed in DB
    mark_document_indexed(doc_id, summary)

    return {
        "document_id": doc_id,
        "lab_values_extracted": lab_values,
        "chunks_indexed": chunks_indexed,
    }
