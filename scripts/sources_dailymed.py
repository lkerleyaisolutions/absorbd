"""Fetch + parse FDA DailyMed drug labels (SPL XML) for UC medications.

DailyMed is US government regulatory data — no copyright. Cleanest possible license.
Raw XML is cached under data/raw/dailymed/ so re-runs don't re-fetch.

Flow:
  1. Search DailyMed REST API for each drug name -> get the SPL set ID
  2. Download the SPL XML for that set ID
  3. Walk the XML, extract sections by LOINC code (drug interactions,
     warnings, adverse reactions, etc.)
  4. Return LabelSection records -> caller converts to IngestDoc
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET

import requests

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "raw" / "dailymed"

USER_AGENT = "Absorbd-research/1.0 (research project; contact lkerley03@gmail.com)"

SEARCH_API = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json"
SPL_XML_URL = "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/{setid}.xml"
DRUG_INFO_BASE = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}"

# SPL default XML namespace
NS = "urn:hl7-org:v3"

# LOINC codes for label sections we care about clinically.
# Nutrient depletion signals live in warnings, interactions, and adverse reactions.
WANTED_CODES = {
    "34066-1": "Boxed Warning",
    "43685-7": "Warnings and Precautions",
    "34073-7": "Drug Interactions",
    "34084-4": "Adverse Reactions",
    "42232-9": "Precautions",
    "34076-0": "Information for Patients",
    "34068-7": "Dosage and Administration",
}

# UC drugs in our medication_map, ordered by clinical priority for nutrient interactions.
# Corticosteroids and immunomodulators have the richest depletion profiles;
# biologics matter for safety context even if direct nutrient effects are smaller.
UC_DRUGS = [
    "prednisone",
    "budesonide",
    "methylprednisolone",
    "mesalamine",
    "sulfasalazine",
    "azathioprine",
    "mercaptopurine",
    "methotrexate",
    "adalimumab",
    "infliximab",
    "vedolizumab",
    "ustekinumab",
    "tofacitinib",
    "upadacitinib",
    "cholestyramine",
]


@dataclass
class LabelSection:
    drug: str
    setid: str
    section_code: str
    section_name: str
    text: str
    source_url: str


def _find_setid(drug_name: str) -> tuple[str, str] | None:
    """Search DailyMed for drug_name; return (setid, title) of the best label."""
    resp = requests.get(
        SEARCH_API,
        params={"drug_name": drug_name, "pagesize": 10},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    items = resp.json().get("data", [])
    if not items:
        return None
    for item in items:
        title = item.get("title", "").lower()
        if "veterinary" in title or "animal" in title:
            continue
        return item["setid"], item.get("title", drug_name)
    return items[0]["setid"], items[0].get("title", drug_name)


def _fetch_xml(setid: str, refresh: bool = False) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{setid}.xml"
    if cache.exists() and not refresh:
        return cache.read_text(encoding="utf-8")
    url = SPL_XML_URL.format(setid=setid)
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    cache.write_text(resp.text, encoding="utf-8")
    return resp.text


def _extract_text(el: ET.Element) -> str:
    """Recursively pull plain text out of an SPL XML element."""
    parts: list[str] = []
    if el.text and el.text.strip():
        parts.append(el.text.strip())
    for child in el:
        child_text = _extract_text(child)
        if child_text:
            parts.append(child_text)
        if child.tail and child.tail.strip():
            parts.append(child.tail.strip())
    return " ".join(parts)


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_label(drug: str, setid: str, refresh: bool = False) -> list[LabelSection]:
    source_url = DRUG_INFO_BASE.format(setid=setid)
    xml_text = _fetch_xml(setid, refresh=refresh)

    ET.register_namespace("", NS)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        # Strip XML declaration if present and retry
        xml_text = re.sub(r"<\?xml[^>]*\?>", "", xml_text, count=1).strip()
        root = ET.fromstring(xml_text)

    sections: list[LabelSection] = []

    def walk(element: ET.Element) -> None:
        local = element.tag.replace(f"{{{NS}}}", "")
        if local == "section":
            code_el = element.find(f"{{{NS}}}code")
            if code_el is not None:
                code = code_el.get("code", "")
                if code in WANTED_CODES:
                    section_name = WANTED_CODES[code]
                    title_el = element.find(f"{{{NS}}}title")
                    if title_el is not None:
                        extracted = _clean(_extract_text(title_el))
                        if extracted:
                            section_name = extracted
                    text_el = element.find(f"{{{NS}}}text")
                    if text_el is not None:
                        text = _clean(_extract_text(text_el))
                        if len(text) >= 80:
                            sections.append(LabelSection(
                                drug=drug,
                                setid=setid,
                                section_code=code,
                                section_name=section_name,
                                text=text,
                                source_url=source_url,
                            ))
        for child in element:
            walk(child)

    walk(root)
    return sections


def load_uc_labels(refresh: bool = False) -> list[LabelSection]:
    out: list[LabelSection] = []
    for drug in UC_DRUGS:
        print(f"  {drug}: searching DailyMed...", end=" ", flush=True)
        result = _find_setid(drug)
        if not result:
            print("NOT FOUND — skipping.")
            continue
        setid, title = result
        print(f"found setid={setid[:8]}...")
        secs = parse_label(drug, setid, refresh=refresh)
        print(f"    -> {len(secs)} sections")
        out.extend(secs)
    return out


if __name__ == "__main__":
    secs = load_uc_labels()
    print(f"\nTotal sections: {len(secs)}")
    for s in secs[:6]:
        print(f"  [{s.drug}] {s.section_name[:60]}  ({len(s.text)}c)")
