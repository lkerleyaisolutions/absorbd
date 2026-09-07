"""Ingest adversarially-verified IBD correlation studies into the Absorbd KB.

Run: venv/Scripts/python.exe scripts/ingest_studies.py
"""

from __future__ import annotations

import sys

from sources_studies import load_verified_studies
from ingestion import IngestDoc, ingest


def main() -> None:
    print("Loading verified IBD correlation studies from manifest...")
    raw = load_verified_studies()

    if not raw:
        print("No approved studies found in manifest.")
        sys.exit(1)

    docs = [
        IngestDoc(
            content=s["content"],
            title=s["title"],
            source=s["source"],
            source_url=s["source_url"],
            doc_type=s["doc_type"],
            nutrient=s["nutrient"],
            evidence_level=s["evidence_level"],
            key_parts=tuple(s["key_parts"]),
        )
        for s in raw
    ]

    print(f"\nIngesting {len(docs)} studies...")
    ingest(docs)
    print("Studies ingestion COMPLETE.")
    sys.exit(0)


if __name__ == "__main__":
    main()
