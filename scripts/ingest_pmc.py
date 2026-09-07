"""Ingest PMC open-access IBD/nutrition articles into the Absorbd KB.

Only CC0 / CC BY / CC BY-SA articles are ingested — license checked per article.

Run: venv/Scripts/python.exe scripts/ingest_pmc.py
"""

from __future__ import annotations

import sys

from sources_pmc import load_pmc_articles, PmcSection
from ingestion import IngestDoc, ingest


def section_to_doc(s: PmcSection) -> IngestDoc:
    return IngestDoc(
        content=s.text,
        title=f"{s.title} [{s.section_name}]",
        source=f"{s.journal} {s.year} (PMC{s.pmcid})",
        source_url=s.source_url,
        doc_type="pmc_article",
        nutrient="",
        evidence_level=f"peer-reviewed | license={s.license_url}",
        key_parts=("pmc", s.pmcid, s.section_name.lower().replace(" ", "_")),
    )


def main() -> None:
    print("Fetching PMC open-access IBD/nutrition articles...")
    sections = load_pmc_articles()
    print(f"\nTotal: {len(sections)} sections from license-approved PMC articles.")

    if not sections:
        print("Nothing to ingest.")
        sys.exit(1)

    docs = [section_to_doc(s) for s in sections]
    ingest(docs)
    print("PMC ingestion COMPLETE.")
    sys.exit(0)


if __name__ == "__main__":
    main()
