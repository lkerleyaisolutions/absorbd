"""Search PMC Open Access for UC/IBD nutrition articles, filter by license, parse JATS XML.

Uses NCBI E-utilities (free, no account needed, 3 req/s limit).
Only ingests CC0, CC BY, CC BY-SA articles — skips CC BY-ND and CC BY-NC.
Raw XML cached under data/raw/pmc/.

Flow:
  ESearch (PMC, query per topic) -> PMCIDs
  EFetch (XML per article) -> JATS XML
  Parse license field -> drop non-commercial / no-derivatives
  Extract sections (abstract, results, discussion) -> IngestDoc list
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "raw" / "pmc"
USER_AGENT = "Absorbd-research/1.0 (research project; contact lkerley03@gmail.com)"

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# CC licenses we accept for derivative use (chunking = derivative work)
ALLOWED_LICENSE_FRAGMENTS = [
    "creativecommons.org/publicdomain/zero",   # CC0
    "creativecommons.org/licenses/by/",        # CC BY
    "creativecommons.org/licenses/by-sa/",     # CC BY-SA
]
BLOCKED_LICENSE_FRAGMENTS = [
    "by-nd",   # no derivatives
    "by-nc",   # non-commercial
]

# Topic searches: (label, query).
# Each query targets IBD/UC + a nutrient/dietary domain.
# "open access"[filter] restricts to PMC OA subset.
PMC_QUERIES = [
    ("vitamin_d_ibd",   '("ulcerative colitis" OR "inflammatory bowel disease") AND "vitamin D" AND ("supplementation" OR "deficiency") AND "open access"[filter]'),
    ("iron_ibd",        '("ulcerative colitis" OR "inflammatory bowel disease") AND "iron deficiency" AND ("supplementation" OR "anemia") AND "open access"[filter]'),
    ("zinc_ibd",        '("ulcerative colitis" OR "Crohn") AND "zinc" AND ("deficiency" OR "supplementation") AND "open access"[filter]'),
    ("omega3_ibd",      '("inflammatory bowel disease") AND ("omega-3" OR "fish oil" OR "EPA" OR "DHA") AND "open access"[filter]'),
    ("folate_ibd",      '("inflammatory bowel disease" OR "ulcerative colitis") AND ("folate" OR "folic acid") AND ("deficiency" OR "supplementation" OR "methotrexate") AND "open access"[filter]'),
    ("micronutrient_ibd", '("inflammatory bowel disease") AND "micronutrient" AND ("deficiency" OR "malabsorption") AND "open access"[filter]'),
    ("calcium_ibd",     '("ulcerative colitis" OR "Crohn") AND "calcium" AND ("corticosteroid" OR "bone density" OR "supplementation") AND "open access"[filter]'),
    ("magnesium_ibd",   '("inflammatory bowel disease") AND "magnesium" AND ("deficiency" OR "supplementation") AND "open access"[filter]'),
]

MAX_PER_QUERY = 8   # cap per topic to keep the run fast


@dataclass
class PmcSection:
    pmcid: str
    pmid: str
    title: str
    journal: str
    year: int
    license_url: str
    section_name: str
    text: str
    source_url: str


# ── helpers ──────────────────────────────────────────────────────────────────

def _get(url: str, params: dict) -> dict | str:
    time.sleep(0.35)   # stay well under 3 req/s
    resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    if "json" in params.get("retmode", ""):
        return resp.json()
    return resp.text


def _esearch(query: str, retmax: int = MAX_PER_QUERY) -> list[str]:
    data = _get(ESEARCH_URL, {"db": "pmc", "term": query, "retmax": retmax,
                               "retmode": "json", "usehistory": "n"})
    return data.get("esearchresult", {}).get("idlist", [])


def _fetch_xml(pmcid: str, refresh: bool = False) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{pmcid}.xml"
    if cache.exists() and not refresh:
        return cache.read_text(encoding="utf-8")
    xml_text = _get(EFETCH_URL, {"db": "pmc", "id": pmcid, "rettype": "xml", "retmode": "xml"})
    assert isinstance(xml_text, str)
    cache.write_text(xml_text, encoding="utf-8")
    return xml_text


# ── license check ─────────────────────────────────────────────────────────────

def _license_url(root: ET.Element) -> str:
    """Return the first license URL found in the article XML, or ''."""
    for el in root.iter():
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag == "license":
            href = el.get("{http://www.w3.org/1999/xlink}href") or el.get("href") or ""
            if href:
                return href.lower()
            # Some JATS encode the URL in a child <ext-link>
            for child in el.iter():
                child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if child_tag == "ext-link":
                    href = child.get("{http://www.w3.org/1999/xlink}href") or child.get("href") or ""
                    if href:
                        return href.lower()
    return ""


def _license_ok(url: str) -> bool:
    if not url:
        return False
    if any(b in url for b in BLOCKED_LICENSE_FRAGMENTS):
        return False
    return any(a in url for a in ALLOWED_LICENSE_FRAGMENTS)


# ── metadata extraction ───────────────────────────────────────────────────────

def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _inner_text(el: ET.Element) -> str:
    return _clean("".join(el.itertext()))


def _meta(root: ET.Element) -> dict:
    meta = {"pmid": "", "title": "Unknown", "journal": "Unknown", "year": 0}
    for el in root.iter():
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag == "article-title" and meta["title"] == "Unknown":
            meta["title"] = _inner_text(el)
        if tag == "journal-title" and meta["journal"] == "Unknown":
            meta["journal"] = _inner_text(el)
        if tag == "year" and meta["year"] == 0:
            try:
                meta["year"] = int(_inner_text(el))
            except ValueError:
                pass
        if tag == "article-id":
            id_type = el.get("pub-id-type", "")
            if id_type == "pmid":
                meta["pmid"] = _inner_text(el)
    return meta


# ── body text extraction ──────────────────────────────────────────────────────

SKIP_SECTION_TITLES = {
    "references", "acknowledgements", "acknowledgments", "competing interests",
    "conflict of interest", "abbreviations", "author contributions",
    "supplementary", "appendix", "funding",
}

KEEP_SECTION_TITLES = {
    "abstract", "introduction", "background", "results", "findings",
    "discussion", "conclusions", "conclusion",
    "nutritional", "vitamin", "mineral", "supplement", "dietary",
    "deficiency", "treatment", "therapy", "clinical",
}


def _section_title(sec: ET.Element) -> str:
    for child in sec:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag == "title":
            return _inner_text(child).lower()
    return ""


def _want_section(title: str) -> bool:
    if not title:
        return True  # untitled body sections often have content
    if any(s in title for s in SKIP_SECTION_TITLES):
        return False
    # Accept if it matches a keep pattern OR has no skip pattern
    if any(k in title for k in KEEP_SECTION_TITLES):
        return True
    # Default: include unless it's a known skip
    return True


def _extract_sections(root: ET.Element, pmcid: str, meta: dict, lic_url: str) -> list[PmcSection]:
    source_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/"
    sections: list[PmcSection] = []

    # Abstract (from <front>)
    for el in root.iter():
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag == "abstract":
            text = _clean(" ".join(p for p in el.itertext() if p.strip()))
            if len(text) >= 100:
                sections.append(PmcSection(
                    pmcid=pmcid, pmid=meta["pmid"], title=meta["title"],
                    journal=meta["journal"], year=meta["year"],
                    license_url=lic_url, section_name="Abstract",
                    text=text, source_url=source_url,
                ))
            break

    # Body sections
    for el in root.iter():
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag == "body":
            for sec in el:
                sec_tag = sec.tag.split("}")[-1] if "}" in sec.tag else sec.tag
                if sec_tag != "sec":
                    continue
                title = _section_title(sec)
                if not _want_section(title):
                    continue
                text = _clean(" ".join(t for t in sec.itertext() if t.strip()))
                if len(text) >= 150:
                    label = title.title() if title else "Body"
                    sections.append(PmcSection(
                        pmcid=pmcid, pmid=meta["pmid"], title=meta["title"],
                        journal=meta["journal"], year=meta["year"],
                        license_url=lic_url, section_name=label,
                        text=text, source_url=source_url,
                    ))
            break

    return sections


# ── public API ────────────────────────────────────────────────────────────────

def load_pmc_articles(refresh: bool = False) -> list[PmcSection]:
    seen_pmcids: set[str] = set()
    out: list[PmcSection] = []

    for label, query in PMC_QUERIES:
        print(f"\n[{label}] searching PMC...", end=" ", flush=True)
        pmcids = _esearch(query)
        print(f"{len(pmcids)} results")

        for pmcid in pmcids:
            if pmcid in seen_pmcids:
                continue
            seen_pmcids.add(pmcid)

            print(f"  PMC{pmcid}: fetching...", end=" ", flush=True)
            try:
                xml_text = _fetch_xml(pmcid, refresh=refresh)
                root = ET.fromstring(xml_text.encode("utf-8"))
            except Exception as exc:
                print(f"ERROR ({exc}) — skipping")
                continue

            lic_url = _license_url(root)
            if not _license_ok(lic_url):
                lic_short = lic_url[30:60] if lic_url else "no license found"
                print(f"SKIP (license: ...{lic_short})")
                continue

            meta = _meta(root)
            secs = _extract_sections(root, pmcid, meta, lic_url)
            if secs:
                lic_type = "CC0" if "zero" in lic_url else "CC BY-SA" if "by-sa" in lic_url else "CC BY"
                print(f"ok [{lic_type}] — {meta['title'][:50]}... ({len(secs)} sections)")
                out.extend(secs)
            else:
                print("no usable sections — skipping")

    return out


if __name__ == "__main__":
    secs = load_pmc_articles()
    print(f"\nTotal: {len(secs)} sections from PMC articles")
    journals = {s.journal for s in secs}
    print(f"Journals: {journals}")
