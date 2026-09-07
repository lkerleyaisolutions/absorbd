r"""Validation-batch ingest: NIH ODS fact sheets for vitamin D, B12, iron.

Runs the full pipeline end-to-end and then fires a real clinical query to prove
chunk -> embed -> upload -> retrieve returns cited results.

Run:  venv\Scripts\python.exe scripts\ingest_ods.py
"""

from __future__ import annotations

import sys

from azure.search.documents.models import VectorizableTextQuery

from sources_ods import load_validation_batch, Section, ODS_FACT_SHEETS
from ingestion import IngestDoc, ingest
from _common import search_client

NUTRIENT_LABEL = {
    "vitamin_d": "Vitamin D",
    "vitamin_b12": "Vitamin B12",
    "iron": "Iron",
    "zinc": "Zinc",
    "calcium": "Calcium",
    "magnesium": "Magnesium",
    "folate": "Folate",
    "vitamin_b6": "Vitamin B6",
    "omega3": "Omega-3 Fatty Acids",
    "selenium": "Selenium",
    "vitamin_a": "Vitamin A",
    "vitamin_k": "Vitamin K",
    "probiotics": "Probiotics",
}


def section_to_doc(s: Section) -> IngestDoc:
    label = NUTRIENT_LABEL.get(s.nutrient, s.nutrient)
    return IngestDoc(
        content=s.text,
        title=f"{label}: {s.title}",
        source=f"NIH ODS - {label} Fact Sheet (Health Professional)",
        source_url=s.source_url,
        doc_type="fact_sheet",
        nutrient=s.nutrient,
        evidence_level="NIH ODS",
        key_parts=("ods", s.nutrient, s.section, s.subsection),
    )


def verify_retrieval() -> bool:
    sc = search_client()
    query = "How does fat malabsorption from IBD affect vitamin D, and which medications interact with it?"
    print("\n" + "=" * 70)
    print("VERIFY: hybrid (semantic + vector) retrieval")
    print(f"Query: {query}\n")
    vq = VectorizableTextQuery(text=query, k_nearest_neighbors=5, fields="content_vector")
    results = sc.search(
        search_text=query,
        vector_queries=[vq],
        query_type="semantic",
        semantic_configuration_name="absorb-iq-semantic",
        top=3,
    )
    rows = list(results)
    if not rows:
        print("NO RESULTS — retrieval failed.")
        return False
    for i, r in enumerate(rows, 1):
        reranker = r.get("@search.reranker_score")
        print(f"[{i}] {r['title']}")
        print(f"    source: {r['source']}")
        print(f"    {r['source_url']}")
        print(f"    score={r['@search.score']:.4f} reranker={reranker}")
        print(f"    {r['content'][:220]}...\n")
    return True


def main() -> None:
    print(f"Loading NIH ODS fact sheets ({len(ODS_FACT_SHEETS)} nutrients)...")
    sections = load_validation_batch()
    print(f"Parsed {len(sections)} sections across {len(ODS_FACT_SHEETS)} fact sheets.")
    docs = [section_to_doc(s) for s in sections]
    ingest(docs)
    ok = verify_retrieval()
    print("=" * 70)
    print("VALIDATION BATCH:", "PASSED" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
