"""Fetch + parse NIH ODS 'Health Professional' fact sheets into clean sections.

ODS fact sheets have a stable structure inside <main id="main">:
    h1 = nutrient name
    h2 = major sections (Deficiency, Groups at Risk, Interactions with Medications, ...)
    h3 = subsections
We walk that structure into (section, subsection, text) units that become
citable chunks. Boilerplate sections (Table of Contents, References, Disclaimer)
are skipped.

Raw HTML is cached under data/raw/ods/ so re-runs don't re-hit the server.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "raw" / "ods"

USER_AGENT = "Absorbd-research/1.0 (research project; contact lkerley03@gmail.com)"

# Sections that carry no clinical value as retrievable chunks.
SKIP_SECTIONS = {
    "table of contents",
    "references",
    "disclaimer",
    "",  # untitled lead-in before the first h2
}

# ODS fact sheets relevant to IBD/UC nutrition.
ODS_FACT_SHEETS = {
    # Original validation batch
    "vitamin_d": "https://ods.od.nih.gov/factsheets/VitaminD-HealthProfessional/",
    "vitamin_b12": "https://ods.od.nih.gov/factsheets/VitaminB12-HealthProfessional/",
    "iron": "https://ods.od.nih.gov/factsheets/Iron-HealthProfessional/",
    # Phase 1 expansion — IBD-critical nutrients
    "zinc": "https://ods.od.nih.gov/factsheets/Zinc-HealthProfessional/",
    "calcium": "https://ods.od.nih.gov/factsheets/Calcium-HealthProfessional/",
    "magnesium": "https://ods.od.nih.gov/factsheets/Magnesium-HealthProfessional/",
    "folate": "https://ods.od.nih.gov/factsheets/Folate-HealthProfessional/",
    "vitamin_b6": "https://ods.od.nih.gov/factsheets/VitaminB6-HealthProfessional/",
    "omega3": "https://ods.od.nih.gov/factsheets/Omega3FattyAcids-HealthProfessional/",
    "selenium": "https://ods.od.nih.gov/factsheets/Selenium-HealthProfessional/",
    "vitamin_a": "https://ods.od.nih.gov/factsheets/VitaminA-HealthProfessional/",
    "vitamin_k": "https://ods.od.nih.gov/factsheets/VitaminK-HealthProfessional/",
    "probiotics": "https://ods.od.nih.gov/factsheets/Probiotics-HealthProfessional/",
}


@dataclass
class Section:
    nutrient: str
    section: str       # h2
    subsection: str     # h3 (may be "")
    text: str
    source_url: str

    @property
    def title(self) -> str:
        parts = [p for p in (self.section, self.subsection) if p]
        return " - ".join(parts)


def _fetch_html(nutrient: str, url: str, refresh: bool = False) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{nutrient}.html"
    if cache.exists() and not refresh:
        return cache.read_text(encoding="utf-8")
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    cache.write_text(resp.text, encoding="utf-8")
    return resp.text


def _clean(text: str) -> str:
    # drop citation markers: [12], [3,4], [167-170], [1, 3-5]
    text = re.sub(r"\[\d+(?:\s*[,–-]\s*\d+)*\]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_factsheet(nutrient: str, url: str, refresh: bool = False) -> list[Section]:
    html = _fetch_html(nutrient, url, refresh=refresh)
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main") or soup
    for junk in main.find_all(["script", "style", "nav", "aside", "footer", "form"]):
        junk.decompose()

    sections: list[Section] = []
    cur_section = ""
    cur_sub = ""
    buf: list[str] = []

    def flush():
        nonlocal buf
        if cur_section.strip().lower() in SKIP_SECTIONS:
            buf = []
            return
        text = _clean(" ".join(buf))
        if len(text) >= 80:  # drop trivially short fragments
            sections.append(Section(nutrient, cur_section, cur_sub, text, url))
        buf = []

    for el in main.find_all(["h2", "h3", "p", "li"]):
        name = el.name
        if name == "h2":
            flush()
            cur_section = _clean(el.get_text())
            cur_sub = ""
        elif name == "h3":
            flush()
            cur_sub = _clean(el.get_text())
        else:  # p, li
            txt = _clean(el.get_text())
            if txt:
                buf.append(txt)
    flush()
    return sections


def load_validation_batch(refresh: bool = False) -> list[Section]:
    out: list[Section] = []
    for nutrient, url in ODS_FACT_SHEETS.items():
        out.extend(parse_factsheet(nutrient, url, refresh=refresh))
    return out


if __name__ == "__main__":
    secs = parse_factsheet("vitamin_d", ODS_FACT_SHEETS["vitamin_d"])
    print(f"Vitamin D: {len(secs)} sections")
    for s in secs[:12]:
        print(f"  [{len(s.text):5}c] {s.title[:70]}")
