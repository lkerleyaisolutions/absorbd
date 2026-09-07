"""Ingest FDA DailyMed drug labels for UC medications into the Absorbd KB.

US government regulatory data — no copyright. See sources_dailymed.py for details.

Run: venv/Scripts/python.exe scripts/ingest_dailymed.py
"""

from __future__ import annotations

import sys

from sources_dailymed import load_uc_labels, LabelSection, UC_DRUGS
from ingestion import IngestDoc, ingest


def section_to_doc(s: LabelSection) -> IngestDoc:
    drug_label = s.drug.replace("_", " ").title()
    return IngestDoc(
        content=s.text,
        title=f"{drug_label}: {s.section_name}",
        source=f"FDA DailyMed - {drug_label} Drug Label",
        source_url=s.source_url,
        doc_type="drug_label",
        nutrient="",
        evidence_level="FDA drug label",
        key_parts=("dailymed", s.drug, s.setid, s.section_code),
    )


def main() -> None:
    print(f"Loading FDA DailyMed labels for {len(UC_DRUGS)} UC drugs...")
    sections = load_uc_labels()
    print(f"\nTotal: {len(sections)} sections extracted from DailyMed labels.")

    if not sections:
        print("Nothing to ingest — check network or search results above.")
        sys.exit(1)

    docs = [section_to_doc(s) for s in sections]
    ingest(docs)
    print("DailyMed ingestion COMPLETE.")
    sys.exit(0)


if __name__ == "__main__":
    main()
