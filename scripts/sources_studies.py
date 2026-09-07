"""Fetch + parse verified IBD correlation studies from PubMed for ingestion.

Reads the adversarially-verified manifest at data/research/ibd_correlation_studies.json,
fetches each study's full abstract from PubMed E-utilities, and combines it with
the verified key finding and quantitative result into rich IngestDoc records.

US-government PubMed abstract text is not copyrighted. The manifest itself was
produced by this project. No license issues.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "research" / "ibd_correlation_studies.json"
CACHE_DIR = ROOT / "data" / "raw" / "pubmed"

USER_AGENT = "Absorbd-research/1.0 (research project; contact lkerley03@gmail.com)"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

DOMAIN_LABELS = {
    "stress_ibd": "Psychological Stress and IBD",
    "adherence_relapse": "Medication Adherence and Relapse",
    "dietary_triggers": "Dietary Triggers and IBD",
    "sleep_ibd": "Sleep and IBD",
    "exercise_ibd": "Exercise and IBD",
}


def _fetch_abstract(pmid: str, refresh: bool = False) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{pmid}.txt"
    if cache.exists() and not refresh:
        return cache.read_text(encoding="utf-8")
    resp = requests.get(
        EFETCH_URL,
        params={"db": "pubmed", "id": pmid, "rettype": "abstract", "retmode": "text"},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    text = resp.text.strip()
    cache.write_text(text, encoding="utf-8")
    time.sleep(0.4)  # stay within 3 req/s without an API key
    return text


def load_verified_studies(refresh: bool = False) -> list[dict]:
    """Return IngestDoc-ready dicts for all approved studies in the manifest."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    out: list[dict] = []

    for domain_key, domain_label in DOMAIN_LABELS.items():
        domain_data = manifest["domains"].get(domain_key, [])
        # Some domains have a note-only dict instead of a list when empty
        if not isinstance(domain_data, list):
            print(f"  {domain_label}: skipped (no confirmed studies)")
            continue

        for study in domain_data:
            if study.get("status") != "approved":
                continue

            pmid = study["pmid"]
            print(f"  [{domain_label}] {study['authors']} {study['year']} (PMID {pmid})...", end=" ", flush=True)
            try:
                abstract = _fetch_abstract(pmid, refresh=refresh)
            except Exception as exc:
                print(f"FETCH ERROR: {exc} — using key_finding only")
                abstract = ""

            # Build rich content: abstract + verified summary
            content_parts = []
            if abstract:
                content_parts.append(abstract)
            content_parts.append(
                f"Verified key finding: {study['key_finding']}\n"
                f"Quantitative result: {study['quantitative_result']}"
            )
            if study.get("lag_or_timing") and study["lag_or_timing"] != "null":
                content_parts.append(f"Study timing: {study['lag_or_timing']}")
            if study.get("flag_reasons"):
                content_parts.append("Caveats: " + " | ".join(study["flag_reasons"]))

            content = "\n\n".join(content_parts)
            print(f"ok ({len(content)}c)")

            out.append({
                "content": content,
                "title": f"{study['title']} [{domain_label}]",
                "source": f"{study['journal']} {study['year']} — {study['authors']} (PMID {pmid})",
                "source_url": study["pubmed_url"],
                "doc_type": "research_study",
                "nutrient": "",
                "evidence_level": f"peer-reviewed study | ingest_priority={study['ingest_priority']}",
                "key_parts": ("study", domain_key, pmid),
            })

    return out


if __name__ == "__main__":
    studies = load_verified_studies()
    print(f"\nTotal: {len(studies)} studies ready to ingest")
    for s in studies:
        print(f"  {s['source'][:80]}")
