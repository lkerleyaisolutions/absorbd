"""Core ingestion: chunk -> embed -> upload to the Absorbd search index.

Document push API requires the embedding vector to be supplied at upload time
(the index's integrated vectorizer only embeds QUERIES at search time), so we
embed each chunk client-side here with text-embedding-3-small.

Source-specific parsers (e.g. sources_ods.py) produce IngestDoc records and hand
them to ingest(). This module is source-agnostic.
"""

from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass, field

from openai import OpenAI

from _common import (
    AOAI_ENDPOINT_V1,
    AOAI_API_KEY,
    EMBEDDING_DEPLOYMENT,
    search_client,
)

MAX_CHARS = 1400      # ~350 tokens/chunk: precise citations, well under the 8191 limit
OVERLAP_CHARS = 150   # keep context across chunk boundaries
EMBED_BATCH = 64      # embeddings per API call


@dataclass
class IngestDoc:
    """One logical source unit before chunking (e.g. an ODS section)."""
    content: str
    title: str
    source: str
    source_url: str
    doc_type: str
    nutrient: str = ""
    evidence_level: str = ""
    patient_id: str = ""
    key_parts: tuple[str, ...] = field(default_factory=tuple)  # for a stable id


def _slug(s: str, n: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:n] or "x"


def chunk_text(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Split on sentence boundaries into <= max_chars chunks with overlap."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    cur = ""
    for sent in sentences:
        if cur and len(cur) + 1 + len(sent) > max_chars:
            chunks.append(cur.strip())
            tail = cur[-overlap:] if overlap else ""
            cur = (tail + " " + sent).strip()
        else:
            cur = (cur + " " + sent).strip() if cur else sent
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def _doc_id(doc: IngestDoc, idx: int) -> str:
    # Stable id from key_parts only (NOT the display title), so re-ingesting after
    # a title/label tweak overwrites in place instead of orphaning old documents.
    base = "-".join(_slug(p) for p in (doc.key_parts or (doc.source,)))
    h = hashlib.sha1(f"{base}|{idx}".encode()).hexdigest()[:8]
    return f"{_slug(base, 60)}-{idx}-{h}"


def _embed(client: OpenAI, texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = texts[i : i + EMBED_BATCH]
        resp = client.embeddings.create(model=EMBEDDING_DEPLOYMENT, input=batch)
        vectors.extend(d.embedding for d in resp.data)
    return vectors


def build_records(docs: list[IngestDoc]) -> list[dict]:
    """Chunk each IngestDoc and produce search documents WITHOUT vectors yet."""
    records: list[dict] = []
    for doc in docs:
        for idx, chunk in enumerate(chunk_text(doc.content)):
            records.append(
                {
                    "id": _doc_id(doc, idx),
                    "content": chunk,
                    "title": doc.title,
                    "source": doc.source,
                    "source_url": doc.source_url,
                    "doc_type": doc.doc_type,
                    "nutrient": doc.nutrient,
                    "evidence_level": doc.evidence_level,
                    "patient_id": doc.patient_id or None,
                }
            )
    return records


def ingest(docs: list[IngestDoc], dry_run: bool = False) -> list[dict]:
    """Chunk, embed, and upload. Returns the records (with vectors if not dry_run)."""
    records = build_records(docs)
    print(f"Built {len(records)} chunks from {len(docs)} source units.")
    if not records:
        return records

    client = OpenAI(base_url=AOAI_ENDPOINT_V1, api_key=AOAI_API_KEY)
    vectors = _embed(client, [r["content"] for r in records])
    for r, v in zip(records, vectors):
        r["content_vector"] = v
    print(f"Embedded {len(vectors)} chunks ({len(vectors[0])} dims).")

    if dry_run:
        print("dry_run=True — not uploading.")
        return records

    sc = search_client()
    result = sc.merge_or_upload_documents(documents=records)
    ok = sum(1 for r in result if r.succeeded)
    print(f"Uploaded {ok}/{len(records)} chunks to the index.")
    if ok != len(records):
        for r in result:
            if not r.succeeded:
                print(f"  FAILED id={r.key}: {r.error_message}")
    return records
