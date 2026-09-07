"""Synthesis & Prioritization Agent (#6) - hybrid design.

Two layers:
  1. DETERMINISTIC MERGE (pure code, unit-tested): group every verified upstream
     finding by canonical nutrient, aggregate its origins + sources, and count how
     many independent pathways converge on it. This layer CANNOT invent a nutrient
     - every synthesized item traces back to a verified trio finding.
  2. LLM CLINICAL TRIAGE (grounded): reason over the merged data to assign
     RED / YELLOW / GREEN priority with a rationale. Constrained to the merged
     nutrients only; if it returns anything off-list or invalid, we fall back to a
     deterministic convergence-based priority.

Hard safety limits (dose ceilings, red-flag escalation) are NOT done here - that is
the Safety Agent (#8). This agent prioritizes; it does not set clinical limits.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _base import Trace, complete_json  # noqa: E402

AGENT = "Synthesis"

# A confirmed lab read NORMAL within this many days is "recent" enough to monitor
# only (downgrade to GREEN). Older than this is "stale": we keep the nutrient's
# computed priority but note the in-range reading may no longer reflect current status.
LAB_RECENT_DAYS = 120

# Canonical display names so the same nutrient from different agents merges cleanly.
_CANON = {
    "vitamin d": "Vitamin D", "vit d": "Vitamin D",
    "calcium": "Calcium", "iron": "Iron",
    "vitamin b12": "Vitamin B12", "b12": "Vitamin B12", "cobalamin": "Vitamin B12",
    "folate": "Folate", "folic acid": "Folate", "vitamin b9": "Folate",
    "vitamin b6": "Vitamin B6", "vitamin a": "Vitamin A", "vitamin k": "Vitamin K",
    "vitamin c": "Vitamin C", "vitamin e": "Vitamin E",
    "zinc": "Zinc", "magnesium": "Magnesium", "potassium": "Potassium",
    "omega 3": "Omega-3", "omega-3": "Omega-3",
}

VALID_PRIORITIES = {"RED", "YELLOW", "GREEN"}


def canonicalize(name: str) -> str:
    """Map a nutrient name to a canonical display form; unknowns are title-cased."""
    key = re.sub(r"[\s_]+", " ", (name or "").strip().lower())
    if key in _CANON:
        return _CANON[key]
    return name.strip().title() if name else ""


@dataclass
class Contribution:
    nutrient: str          # canonical
    origin_type: str       # "condition" | "medication" | "diet"
    origin: str            # e.g. "ulcerative colitis" | "prednisone" | "vegan"
    detail: str
    sources: list[str] = field(default_factory=list)
    quote: str = ""


@dataclass
class MergedNutrient:
    nutrient: str
    contributions: list[Contribution] = field(default_factory=list)

    @property
    def sources(self) -> list[str]:
        return sorted({s for c in self.contributions for s in c.sources})

    @property
    def convergence(self) -> int:
        # distinct (origin_type, origin) pathways implicating this nutrient
        return len({(c.origin_type, c.origin) for c in self.contributions})

    def default_priority(self) -> str:
        if self.convergence >= 2:
            return "RED"
        if any(c.origin_type == "medication" for c in self.contributions):
            return "YELLOW"
        return "YELLOW" if self.convergence == 1 else "GREEN"


def _detail_for(finding: dict) -> str:
    if finding.get("mechanism") or finding.get("effect"):
        return f"{finding.get('effect', '')}: {finding.get('mechanism', '')}".strip(": ")
    return finding.get("rationale", "")


def normalize_contributions(med_out: dict, defc_out: dict, diet_out: dict) -> list[Contribution]:
    """Flatten the three agents' verified findings into uniform Contributions."""
    contribs: list[Contribution] = []

    def add(blocks, origin_type, origin_key):
        for b in blocks or []:
            origin = b.get(origin_key, "")
            for f in b.get("findings", []):
                nut = canonicalize(f.get("nutrient", ""))
                if not nut:
                    continue
                contribs.append(
                    Contribution(
                        nutrient=nut, origin_type=origin_type, origin=origin,
                        detail=_detail_for(f), sources=list(f.get("sources", [])),
                        quote=f.get("verified_quote", ""),
                    )
                )

    add((defc_out or {}).get("results"), "condition", "focus")
    add((med_out or {}).get("results"), "medication", "medication")
    add((diet_out or {}).get("results"), "diet", "restriction")
    return contribs


def merge(contribs: list[Contribution]) -> list[MergedNutrient]:
    """Group contributions by canonical nutrient, ordered by convergence desc."""
    by_nutrient: dict[str, MergedNutrient] = {}
    for c in contribs:
        by_nutrient.setdefault(c.nutrient, MergedNutrient(c.nutrient)).contributions.append(c)
    return sorted(by_nutrient.values(), key=lambda m: (-m.convergence, m.nutrient))


TRIAGE_SYSTEM = """You are the prioritization step of a clinical nutrition system for IBD patients.
You are given nutrients, each with the pathways (condition, medications, diet) that
implicate it and how many independent pathways converge on it.

Assign each nutrient a priority and a one-sentence rationale:
- RED: multiple converging pathways, or an active medication depletion combined with
  condition/diet risk; warrants prompt attention.
- YELLOW: a single moderate pathway; address and monitor.
- GREEN: minor or low-concern; routine monitoring.

RULES: Use ONLY the nutrients and evidence provided. Do NOT add nutrients. Do NOT set
doses or hard limits (a separate Safety agent does that). The rationale is read by the
treating clinician: write it in third-person clinical voice about "the patient"; never
address the reader as "you" or "your".

Return ONLY JSON: {"triage":[{"nutrient":"<exact name>","priority":"RED|YELLOW|GREEN","rationale":"<one sentence>"}]}"""


def _triage_payload(merged: list[MergedNutrient]) -> str:
    lines = []
    for m in merged:
        lines.append(f"NUTRIENT: {m.nutrient} (converging pathways: {m.convergence})")
        for c in m.contributions:
            lines.append(f"  - {c.origin_type}: {c.origin} — {c.detail}")
    return "\n".join(lines)


# Lab test names (lowercased substrings) that read a given canonical nutrient's
# status. Mirrors the orchestrator's lab-synonym map but kept local so synthesis has
# no import dependency on the orchestrator (which imports synthesize).
_LAB_SYNONYMS = {
    "Iron": ("ferritin", "hemoglobin", "hgb", "iron", "transferrin", "tibc"),
    "Vitamin D": ("vitamin d", "25-oh", "25 oh", "calcidiol"),
    "Vitamin B12": ("b12", "cobalamin"),
    "Folate": ("folate", "folic"),
    "Calcium": ("calcium",),
    "Zinc": ("zinc",),
    "Magnesium": ("magnesium",),
    "Potassium": ("potassium",),
}


def _lab_matches_nutrient(nutrient: str, test_name: str) -> bool:
    t = (test_name or "").lower()
    syns = _LAB_SYNONYMS.get(nutrient, (nutrient.lower(),))
    return any(s in t for s in syns)


def _days_since(test_date: str) -> int | None:
    """Whole days between test_date (ISO) and today; None if unparseable."""
    if not test_date:
        return None
    try:
        d = datetime.fromisoformat(str(test_date)[:10]).date()
    except ValueError:
        return None
    return (date.today() - d).days


def _normal_lab_for(nutrient: str, lab_values: list[dict]) -> dict | None:
    """Most recent confirmed NORMAL lab anchoring this nutrient, or None."""
    candidates = []
    for lv in lab_values or []:
        if str(lv.get("status", "")).strip().upper() != "NORMAL":
            continue
        if not _lab_matches_nutrient(nutrient, lv.get("test_name", "")):
            continue
        candidates.append(lv)
    if not candidates:
        return None
    # Prefer the most recent NORMAL reading = smallest days-since-test. Labs with an
    # unparseable date sort last (treated as effectively oldest).
    def _key(lv):
        days = _days_since(lv.get("test_date", ""))
        return days if days is not None else float("inf")
    return min(candidates, key=_key)


def _apply_normal_lab_handling(nutrient_obj: dict, lab_values: list[dict], trace: Trace) -> None:
    """FIX #6: time-aware NORMAL-lab handling. Mutates nutrient_obj in place.

    - NORMAL & recent  -> downgrade to GREEN (monitor only), rationale notes the value.
    - NORMAL & stale   -> keep priority, attach lab_note that the in-range reading is old.
    - No NORMAL lab    -> set lab_recent=None, lab_note=None and leave priority alone.
    LOW/HIGH labs are untouched here (they already drive priority upstream).
    """
    nutrient_obj.setdefault("lab_recent", None)
    nutrient_obj.setdefault("lab_note", None)
    lv = _normal_lab_for(nutrient_obj["nutrient"], lab_values)
    if not lv:
        return
    name = lv.get("test_name") or nutrient_obj["nutrient"]
    value = lv.get("value", "")
    unit = lv.get("unit", "")
    val_str = f"{value} {unit}".strip()
    days = _days_since(lv.get("test_date", ""))
    recent = days is not None and days <= LAB_RECENT_DAYS
    nutrient_obj["lab_recent"] = recent
    if recent:
        age = f"{days} days ago" if days is not None else "recently"
        nutrient_obj["priority"] = "GREEN"
        nutrient_obj["rationale"] = f"Serum level in range ({name} {val_str}, {age})."
        nutrient_obj["lab_note"] = None
        trace.emit(AGENT, "lab", f"{nutrient_obj['nutrient']}: recent NORMAL lab -> GREEN (monitor)")
    else:
        age = f"{days} days ago" if days is not None else "some time ago"
        nutrient_obj["lab_note"] = (
            f"Most recent {name} lab was in range ({val_str}) but that was {age}; "
            "level may have changed since then."
        )
        trace.emit(AGENT, "lab", f"{nutrient_obj['nutrient']}: stale NORMAL lab -> priority kept, noted")


def synthesize(med_out: dict, defc_out: dict, diet_out: dict, trace: Trace | None = None,
               profile: dict | None = None) -> dict:
    trace = trace or Trace()
    lab_values = (profile or {}).get("lab_values") or []
    contribs = normalize_contributions(med_out, defc_out, diet_out)
    merged = merge(contribs)
    trace.emit(AGENT, "merge", f"{len(contribs)} findings merged into {len(merged)} nutrients")

    # LLM triage (grounded in merged data)
    llm: dict[str, dict] = {}
    if merged:
        try:
            result = complete_json(TRIAGE_SYSTEM, _triage_payload(merged))
            for t in result.get("triage", []):
                nut = canonicalize(t.get("nutrient", ""))
                pri = str(t.get("priority", "")).upper()
                if nut and pri in VALID_PRIORITIES:
                    llm[nut] = {"priority": pri, "rationale": t.get("rationale", "")}
        except Exception:
            llm = {}

    nutrients = []
    for m in merged:
        t = llm.get(m.nutrient)
        if t:
            priority, rationale = t["priority"], t["rationale"]
        else:
            priority, rationale = m.default_priority(), "Prioritized by evidence convergence (triage fallback)."
        trace.emit(AGENT, "triage", f"{m.nutrient}: {priority} (convergence {m.convergence})")
        n_obj = {
            "nutrient": m.nutrient,
            "priority": priority,
            "rationale": rationale,
            "convergence": m.convergence,
            "origins": [
                {"type": c.origin_type, "origin": c.origin, "detail": c.detail} for c in m.contributions
            ],
            "sources": m.sources,
        }
        # FIX #6: time-aware NORMAL-lab handling (may downgrade to GREEN or annotate).
        _apply_normal_lab_handling(n_obj, lab_values, trace)
        nutrients.append(n_obj)

    order = {"RED": 0, "YELLOW": 1, "GREEN": 2}
    nutrients.sort(key=lambda n: (order.get(n["priority"], 3), -n["convergence"], n["nutrient"]))
    trace.emit(AGENT, "conclude", f"{len(nutrients)} nutrients prioritized")
    return {"nutrients": nutrients, "trace": trace.events}
