"""Seed EXTRA demo patients for richer, more detailed demos.

Adds 5 more patients under the existing doctor (DOC-DEMO1, Dr. Elena Hartley)
and a SECOND doctor (DOC-DEMO2, Dr. Marcus Chen) with 4 patients of his own.

Every patient is a distinct clinical story: different disease subtype, different
medications, different lab panels, different symptom patterns, different
adherence, and DIFFERENT planted behavioral correlations that the correlation
engine can legitimately recover (food triggers, missed-med lags, stress lags,
sleep, exercise).

Design notes that match the rest of the system:
  - Conditions are limited to the three the app supports: "ulcerative colitis",
    "Crohn's disease", "celiac disease" (see CONDITIONS in App.jsx).
  - Symptom strings are drawn from the UI checklist in App.jsx so chips render.
  - medications_taken keys are each med's NAME (matches the journal agent's
    _med_key and what get_patient_stats / the correlation engine read).
  - sleep_hours and exercise are INDEPENDENT draws, never derived from
    stress/flare, so the correlation engine cannot "rediscover" the stress
    signal laundered through a formula (the same honesty rule seed_demo.py uses).
  - Planted correlation signs all match the engine's _EXPECTED_SIGN map
    (trigger food / missed med / stress / bm_count -> +symptoms; more sleep /
    more exercise -> fewer symptoms), so findings are not demoted as
    "unexpected".

Safe to re-run: skips a patient that already has data (entries + confirmed
labs); back-fills entries or labs if a prior run only got part way.

Run:  venv/Scripts/python.exe scripts/seed_demo_extra.py
"""

from __future__ import annotations

import json
import math
import random
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data"))
sys.path.insert(0, str(ROOT / "scripts"))

from journal import init_db, _conn  # noqa: E402
from lab_pdf import title_from_filename, write_lab_report_pdf  # noqa: E402


# ── Deterministic factor helpers ─────────────────────────────────────────────
# Each draw is keyed by (day_offset, patient salt, purpose) so a value computed
# for "yesterday" while generating today matches the value generated when
# yesterday was "today". That consistency is what makes the planted lag
# correlations real instead of noise.

def _rng(offset: int, salt: int, kind: int) -> random.Random:
    seed = (offset + 100_000) * 1_000_003 + salt * 9_973 + kind
    return random.Random(seed)


def _name_kind(name: str, base: int, mult: int) -> int:
    return base + mult * sum(ord(c) for c in name)


def flare_for(offset: int, story: dict) -> float:
    """Disease-activity envelope in [0,1]. A Gaussian bump centered on `peak`
    (a day offset). Improving stories peak in the past; worsening stories peak
    near today; relapse/recover stories peak in the middle."""
    f = story["flare"]
    val = f["base"] + f["amp"] * math.exp(-(((offset - f["peak"]) / f["width"]) ** 2))
    return max(0.0, min(1.0, val))


def stress_for(offset: int, story: dict) -> int:
    s = story["stress"]
    rng = _rng(offset, story["salt"], 1)
    val = s["base"] + s["amp"] * flare_for(offset, story) + rng.gauss(0, s["noise"])
    return max(1, min(10, round(val)))


def sleep_for(offset: int, story: dict) -> float:
    s = story["sleep"]
    rng = _rng(offset, story["salt"], 2)
    return round(max(4.0, min(9.8, rng.gauss(s["mean"], s["sd"]))), 1)


def exercise_for(offset: int, story: dict) -> str:
    rng = _rng(offset, story["salt"], 3)
    return rng.choices(
        ["None", "Light walk", "Moderate", "Intense"],
        weights=story["exercise_weights"],
    )[0]


def _food_prob(offset: int, story: dict, food: str) -> float:
    """A food's daily probability. Supports a learning/decline curve via
    prob_old + prob_new (interpolated across the logged window) so e.g. a newly
    diagnosed celiac eats gluten by accident more often early on."""
    for f in story["foods"]:
        if f["name"] == food:
            if "prob_old" in f and "prob_new" in f:
                t = (offset + story["days"]) / max(1, story["days"])  # 0 oldest .. 1 today
                t = max(0.0, min(1.0, t))
                return f["prob_old"] + (f["prob_new"] - f["prob_old"]) * t
            return f.get("prob", 0.0)
    return 0.0


def ate_food_for(offset: int, story: dict, food: str) -> bool:
    rng = _rng(offset, story["salt"], _name_kind(food, 1000, 13))
    return rng.random() < _food_prob(offset, story, food)


def missed_med_for(offset: int, story: dict, med: str) -> bool:
    taken_prob = next((m["taken_prob"] for m in story["meds"] if m["name"] == med), 1.0)
    rng = _rng(offset, story["salt"], _name_kind(med, 50_000, 17))
    return rng.random() > taken_prob


# ── Generic daily-entry generator ────────────────────────────────────────────

def make_entry(offset: int, story: dict) -> dict:
    rng = _rng(offset, story["salt"], 0)
    flare = flare_for(offset, story)
    stress = stress_for(offset, story)
    sleep_hours = sleep_for(offset, story)
    exercise = exercise_for(offset, story)

    symptoms: list[str] = []

    # Baseline (flare-driven) symptoms.
    for sym in story["symptoms"]:
        p = sym["base"] + sym["flare_coef"] * flare
        if rng.random() < p and sym["name"] not in symptoms:
            symptoms.append(sym["name"])

    # Planted behavioral correlations.
    for pl in story["planted"]:
        target = pl["target"]
        fire = False
        kind = pl["kind"]
        if kind == "stress_lag1":
            prev = stress_for(offset - 1, story)
            fire = rng.random() < (pl["hi"] if prev >= pl["thresh"] else pl["lo"])
        elif kind == "food_lag1":
            ate = ate_food_for(offset - 1, story, pl["food"])
            fire = rng.random() < (pl["hi"] if ate else pl["lo"])
        elif kind == "food_same_day":
            ate = ate_food_for(offset, story, pl["food"])
            fire = rng.random() < (pl["hi"] if ate else pl["lo"])
        elif kind == "missed_med_lag2":
            missed = missed_med_for(offset - 2, story, pl["med"])
            fire = rng.random() < (pl["hi"] if missed else pl["lo"])
        elif kind == "missed_med_lag1":
            missed = missed_med_for(offset - 1, story, pl["med"])
            fire = rng.random() < (pl["hi"] if missed else pl["lo"])
        elif kind == "sleep_lag1":
            prev_sleep = sleep_for(offset - 1, story)
            fire = rng.random() < (pl["hi"] if prev_sleep < pl["thresh"] else pl["lo"])
        elif kind == "exercise_neg_lag1":
            active = exercise_for(offset - 1, story) in ("Moderate", "Intense")
            fire = rng.random() < (pl["active"] if active else pl["inactive"])
        if fire and target not in symptoms:
            symptoms.append(target)

    # Medication adherence (name keys, matching the journal agent).
    meds_taken = {
        m["name"]: ("missed" if missed_med_for(offset, story, m["name"]) else "taken")
        for m in story["meds"]
    }

    # Foods logged today.
    food_today = [f["name"] for f in story["foods"] if ate_food_for(offset, story, f["name"])]

    # Bowel movement count (flare-driven, with its own noise).
    b = story["bm"]
    rng_bm = _rng(offset, story["salt"], 5)
    bm_count = max(0, round(b["base"] + b["flare_coef"] * flare + rng_bm.gauss(0, b["noise"])))

    notes = rng.choice(story["notes"]) if rng.random() < 0.45 else ""

    return {
        "symptoms_today": symptoms,
        "medications_taken": meds_taken,
        "stress_level": stress,
        "notes": notes,
        "extra": {
            "food_today": food_today,
            "sleep_hours": sleep_hours,
            "bm_count": bm_count,
            "exercise": exercise,
        },
    }


# ── Doctors ──────────────────────────────────────────────────────────────────

DOCTORS = {
    "hartley": {"code": "DOC-DEMO1", "name": "Dr. Elena Hartley", "practice": "GI Associates of Boston"},
    "chen": {"code": "DOC-DEMO2", "name": "Dr. Marcus Chen", "practice": "Pacific Digestive Health"},
}


# ── Common pools ─────────────────────────────────────────────────────────────

NOTES_CROHNS = [
    "Cramping woke me up around 4am.", "Appetite low, only managed soup.",
    "Joints ached this morning.", "Felt a bit stronger today.",
    "Skipped lunch, too nauseous.", "Walked the dog, energy a little better.", "", "",
]
NOTES_UC = [
    "Urgency made the commute stressful.", "Plain rice and chicken all day.",
    "Better than yesterday.", "Up twice overnight.",
    "Work deadline had me wound up.", "Felt almost normal this afternoon.", "", "",
]
NOTES_CELIAC = [
    "Ate out, worried about cross-contamination.", "Bloated and gassy after dinner.",
    "Read every label today.", "Energy finally coming back.",
    "Skin itchy on elbows again.", "Stuck to safe foods, felt fine.", "", "",
]


# ── Patient catalogue ────────────────────────────────────────────────────────
# Each patient: identity + medications (full list, also tracked daily) +
# symptoms_to_watch + dietary_restrictions + doctor_notes + a lab panel + a
# `story` driving 6-9 weeks of journal entries with planted correlations.

PATIENTS: list[dict] = [
    # ───────────────────────── Dr. Hartley ──────────────────────────────────
    {
        "code": "CROHN1", "doctor": "hartley", "name": "Jordan Avery",
        "condition": "Crohn's disease",
        "medications": [
            {"name": "Adalimumab", "brand": "Humira", "dose": "40mg", "frequency": "every 2 weeks (injection)"},
            {"name": "Methotrexate", "brand": "Trexall", "dose": "15mg", "frequency": "once weekly"},
            {"name": "Folic acid", "brand": "", "dose": "1mg", "frequency": "once daily"},
        ],
        "symptoms_to_watch": ["Abdominal pain", "Diarrhea", "Fatigue", "Joint pain", "Loss of appetite", "Unintended weight loss", "Nausea"],
        "dietary_restrictions": ["Low-fiber / low-residue"],
        "doctor_notes": (
            "Terminal ileal Crohn's, stricturing phenotype. Responding to adalimumab, "
            "flare settling over the last month. B12 critically low from ileal involvement, "
            "started monthly injections. Watch for obstructive symptoms; keep low-residue during narrowing."
        ),
        "lab_offset_days": 22,
        "lab_filename": "Crohns_Panel_Ileal_2026-05.pdf",
        "lab_summary": "Ileal Crohn's panel: macrocytic anemia with very low B12, low ferritin, low vitamin D, low magnesium, low albumin, moderately elevated CRP.",
        "labs": [
            {"test_name": "Vitamin B12", "value": "142", "unit": "pg/mL", "reference_range": "200-900", "status": "LOW"},
            {"test_name": "Ferritin", "value": "11", "unit": "ng/mL", "reference_range": "20-250", "status": "LOW"},
            {"test_name": "Hemoglobin", "value": "11.1", "unit": "g/dL", "reference_range": "13.5-17.5", "status": "LOW"},
            {"test_name": "MCV", "value": "102", "unit": "fL", "reference_range": "80-100", "status": "HIGH"},
            {"test_name": "Vitamin D 25-OH", "value": "21", "unit": "ng/mL", "reference_range": "30-100", "status": "LOW"},
            {"test_name": "Magnesium", "value": "1.5", "unit": "mg/dL", "reference_range": "1.7-2.2", "status": "LOW"},
            {"test_name": "Albumin", "value": "3.4", "unit": "g/dL", "reference_range": "3.5-5.0", "status": "LOW"},
            {"test_name": "CRP", "value": "12.4", "unit": "mg/L", "reference_range": "0.0-5.0", "status": "HIGH"},
            {"test_name": "Folate", "value": "9.0", "unit": "ng/mL", "reference_range": "3.0-17.0", "status": "NORMAL"},
        ],
        "story": {
            "salt": 101, "days": 58,
            "flare": {"base": 0.20, "amp": 0.55, "peak": -42, "width": 16},  # improving
            "stress": {"base": 4.5, "amp": 1.5, "noise": 1.3},
            "sleep": {"mean": 6.8, "sd": 1.1},
            "exercise_weights": [0.45, 0.35, 0.15, 0.05],
            "bm": {"base": 3.0, "flare_coef": 4.0, "noise": 0.8},
            "meds": [
                {"name": "Adalimumab", "taken_prob": 0.97},
                {"name": "Methotrexate", "taken_prob": 0.95},
                {"name": "Folic acid", "taken_prob": 0.80},
            ],
            "foods": [
                {"name": "Fried/Fatty", "prob": 0.26},
                {"name": "Dairy", "prob": 0.14},
                {"name": "Caffeine", "prob": 0.30},
            ],
            "symptoms": [
                {"name": "Fatigue", "base": 0.55, "flare_coef": 0.30},
                {"name": "Diarrhea", "base": 0.30, "flare_coef": 0.45},
                {"name": "Joint pain", "base": 0.18, "flare_coef": 0.25},
                {"name": "Loss of appetite", "base": 0.15, "flare_coef": 0.35},
                {"name": "Unintended weight loss", "base": 0.08, "flare_coef": 0.20},
            ],
            "planted": [
                {"kind": "food_lag1", "food": "Fried/Fatty", "target": "Abdominal pain", "hi": 0.80, "lo": 0.12},
                {"kind": "sleep_lag1", "target": "Fatigue", "thresh": 6.0, "hi": 0.92, "lo": 0.50},
            ],
            "notes": NOTES_CROHNS,
        },
    },
    {
        "code": "CELIA1", "doctor": "hartley", "name": "Sam Rivera",
        "condition": "celiac disease",
        "medications": [
            {"name": "Ferrous sulfate", "brand": "", "dose": "325mg", "frequency": "once daily"},
            {"name": "Vitamin D3", "brand": "", "dose": "2000 IU", "frequency": "once daily"},
            {"name": "Calcium citrate", "brand": "", "dose": "600mg", "frequency": "once daily"},
        ],
        "symptoms_to_watch": ["Bloating", "Diarrhea", "Fatigue", "Abdominal pain", "Skin rash", "Cramping"],
        "dietary_restrictions": ["Gluten-free"],
        "doctor_notes": (
            "Biopsy-confirmed celiac, 14 months gluten-free. Mucosa healing but tTG still "
            "mildly elevated, suspect intermittent cross-contamination. Iron-deficiency anemia "
            "improving on oral iron. Dermatitis herpetiformis flares track accidental exposures. "
            "Reinforce label-reading and dining-out strategy."
        ),
        "lab_offset_days": 16,
        "lab_filename": "Celiac_Followup_Labs_2026-05.pdf",
        "lab_summary": "Celiac follow-up: mildly elevated tTG-IgA, iron-deficiency anemia, low vitamin D, low folate, borderline-low calcium and B6.",
        "labs": [
            {"test_name": "tTG-IgA", "value": "34", "unit": "U/mL", "reference_range": "<15", "status": "HIGH"},
            {"test_name": "Ferritin", "value": "9", "unit": "ng/mL", "reference_range": "20-250", "status": "LOW"},
            {"test_name": "Hemoglobin", "value": "11.6", "unit": "g/dL", "reference_range": "12.0-16.0", "status": "LOW"},
            {"test_name": "Vitamin D 25-OH", "value": "24", "unit": "ng/mL", "reference_range": "30-100", "status": "LOW"},
            {"test_name": "Folate", "value": "2.8", "unit": "ng/mL", "reference_range": "3.0-17.0", "status": "LOW"},
            {"test_name": "Calcium", "value": "8.5", "unit": "mg/dL", "reference_range": "8.6-10.2", "status": "LOW"},
            {"test_name": "Vitamin B6", "value": "3.5", "unit": "ng/mL", "reference_range": "5.0-50.0", "status": "LOW"},
            {"test_name": "Vitamin B12", "value": "455", "unit": "pg/mL", "reference_range": "200-900", "status": "NORMAL"},
        ],
        "story": {
            "salt": 202, "days": 60,
            "flare": {"base": 0.10, "amp": 0.20, "peak": -30, "width": 22},  # mostly quiet, spikes on exposure
            "stress": {"base": 4.0, "amp": 1.0, "noise": 1.3},
            "sleep": {"mean": 7.2, "sd": 1.0},
            "exercise_weights": [0.30, 0.35, 0.25, 0.10],
            "bm": {"base": 2.0, "flare_coef": 3.0, "noise": 0.7},
            "meds": [
                {"name": "Ferrous sulfate", "taken_prob": 0.82},
                {"name": "Vitamin D3", "taken_prob": 0.88},
                {"name": "Calcium citrate", "taken_prob": 0.80},
            ],
            "foods": [
                {"name": "Gluten/Wheat", "prob": 0.18},  # accidental exposures
                {"name": "Dairy", "prob": 0.40},
                {"name": "Caffeine", "prob": 0.35},
            ],
            "symptoms": [
                {"name": "Fatigue", "base": 0.30, "flare_coef": 0.30},
                {"name": "Skin rash", "base": 0.10, "flare_coef": 0.20},
            ],
            "planted": [
                {"kind": "food_lag1", "food": "Gluten/Wheat", "target": "Bloating", "hi": 0.85, "lo": 0.10},
                {"kind": "food_lag1", "food": "Gluten/Wheat", "target": "Diarrhea", "hi": 0.80, "lo": 0.10},
                {"kind": "food_same_day", "food": "Gluten/Wheat", "target": "Abdominal pain", "hi": 0.70, "lo": 0.08},
            ],
            "notes": NOTES_CELIAC,
        },
    },
    {
        "code": "REMIS1", "doctor": "hartley", "name": "Taylor Brooks",
        "condition": "ulcerative colitis",
        "medications": [
            {"name": "Mesalamine", "brand": "Lialda", "dose": "1.2g", "frequency": "once daily"},
            {"name": "Mesalamine suppository", "brand": "Canasa", "dose": "1000mg", "frequency": "nightly"},
        ],
        "symptoms_to_watch": ["Urgency", "Cramping", "Bloody stools", "Fatigue"],
        "dietary_restrictions": ["No restrictions"],
        "doctor_notes": (
            "Ulcerative proctitis in steroid-free clinical remission on mesalamine. "
            "Calprotectin near normal, CRP normal, excellent adherence. Only outstanding issue is "
            "borderline-low vitamin D on recent labs. Continue maintenance; annual surveillance plan."
        ),
        "lab_offset_days": 9,
        "lab_filename": "UC_Maintenance_Labs_2026-06.pdf",
        "lab_summary": "Maintenance labs in remission: calprotectin and CRP within range, hemoglobin and ferritin normal, only vitamin D borderline low (recent).",
        "labs": [
            {"test_name": "Calprotectin (fecal)", "value": "48", "unit": "mcg/g", "reference_range": "<50", "status": "NORMAL"},
            {"test_name": "CRP", "value": "2.1", "unit": "mg/L", "reference_range": "0.0-5.0", "status": "NORMAL"},
            {"test_name": "Hemoglobin", "value": "13.4", "unit": "g/dL", "reference_range": "12.0-16.0", "status": "NORMAL"},
            {"test_name": "Ferritin", "value": "45", "unit": "ng/mL", "reference_range": "20-250", "status": "NORMAL"},
            {"test_name": "Albumin", "value": "4.2", "unit": "g/dL", "reference_range": "3.5-5.0", "status": "NORMAL"},
            {"test_name": "Vitamin D 25-OH", "value": "27", "unit": "ng/mL", "reference_range": "30-100", "status": "LOW"},
        ],
        "story": {
            "salt": 303, "days": 62,
            "flare": {"base": 0.06, "amp": 0.14, "peak": -20, "width": 18},  # remission
            "stress": {"base": 5.0, "amp": 0.8, "noise": 1.5},
            "sleep": {"mean": 7.4, "sd": 0.9},
            "exercise_weights": [0.25, 0.35, 0.28, 0.12],
            "bm": {"base": 1.5, "flare_coef": 2.0, "noise": 0.6},
            "meds": [
                {"name": "Mesalamine", "taken_prob": 0.97},
                {"name": "Mesalamine suppository", "taken_prob": 0.90},
            ],
            "foods": [
                {"name": "Caffeine", "prob": 0.45},
                {"name": "Spicy Food", "prob": 0.20},
                {"name": "Alcohol", "prob": 0.15},
            ],
            "symptoms": [
                {"name": "Fatigue", "base": 0.15, "flare_coef": 0.25},
                {"name": "Cramping", "base": 0.10, "flare_coef": 0.30},
            ],
            "planted": [
                {"kind": "stress_lag1", "target": "Urgency", "thresh": 6, "hi": 0.65, "lo": 0.10},
            ],
            "notes": NOTES_UC,
        },
    },
    {
        "code": "FLARE1", "doctor": "hartley", "name": "Morgan Lee",
        "condition": "Crohn's disease",
        "medications": [
            {"name": "Prednisone", "brand": "Deltasone", "dose": "20mg", "frequency": "once daily"},
            {"name": "Azathioprine", "brand": "Imuran", "dose": "150mg", "frequency": "once daily"},
        ],
        "symptoms_to_watch": ["Abdominal pain", "Diarrhea", "Bloody stools", "Cramping", "Fatigue", "Joint pain", "Night sweats"],
        "dietary_restrictions": ["Lactose intolerant (avoids dairy)"],
        "doctor_notes": (
            "Colonic Crohn's, steroid-dependent and currently flaring. Adherence to azathioprine "
            "has been poor, which tracks with bleeding episodes. CRP and calprotectin markedly elevated. "
            "Steroid side effects emerging: fasting glucose up, potassium low. Plan: discuss biologic "
            "step-up and steroid taper; counsel on adherence."
        ),
        "lab_offset_days": 12,
        "lab_filename": "Crohns_Flare_Panel_2026-05.pdf",
        "lab_summary": "Active flare panel: very high CRP and calprotectin, anemia with low ferritin, low vitamin D and calcium, low albumin, plus steroid-related high fasting glucose and low potassium.",
        "labs": [
            {"test_name": "CRP", "value": "38.5", "unit": "mg/L", "reference_range": "0.0-5.0", "status": "HIGH"},
            {"test_name": "Calprotectin (fecal)", "value": "1240", "unit": "mcg/g", "reference_range": "<50", "status": "HIGH"},
            {"test_name": "Hemoglobin", "value": "9.8", "unit": "g/dL", "reference_range": "12.0-16.0", "status": "LOW"},
            {"test_name": "Ferritin", "value": "8", "unit": "ng/mL", "reference_range": "20-250", "status": "LOW"},
            {"test_name": "Vitamin D 25-OH", "value": "14", "unit": "ng/mL", "reference_range": "30-100", "status": "LOW"},
            {"test_name": "Calcium", "value": "8.4", "unit": "mg/dL", "reference_range": "8.6-10.2", "status": "LOW"},
            {"test_name": "Albumin", "value": "2.9", "unit": "g/dL", "reference_range": "3.5-5.0", "status": "LOW"},
            {"test_name": "Glucose (fasting)", "value": "138", "unit": "mg/dL", "reference_range": "70-99", "status": "HIGH"},
            {"test_name": "Potassium", "value": "3.3", "unit": "mEq/L", "reference_range": "3.5-5.1", "status": "LOW"},
        ],
        "story": {
            "salt": 404, "days": 56,
            "flare": {"base": 0.45, "amp": 0.50, "peak": -3, "width": 30},  # worsening toward today
            "stress": {"base": 5.5, "amp": 2.0, "noise": 1.5},
            "sleep": {"mean": 6.2, "sd": 1.2},
            "exercise_weights": [0.60, 0.28, 0.09, 0.03],
            "bm": {"base": 4.0, "flare_coef": 5.0, "noise": 0.9},
            "meds": [
                {"name": "Prednisone", "taken_prob": 0.78},
                {"name": "Azathioprine", "taken_prob": 0.60},
            ],
            "foods": [
                {"name": "Dairy", "prob": 0.18},
                {"name": "Fried/Fatty", "prob": 0.30},
                {"name": "Caffeine", "prob": 0.40},
                {"name": "Alcohol", "prob": 0.12},
            ],
            "symptoms": [
                {"name": "Diarrhea", "base": 0.55, "flare_coef": 0.35},
                {"name": "Abdominal pain", "base": 0.45, "flare_coef": 0.40},
                {"name": "Fatigue", "base": 0.55, "flare_coef": 0.30},
                {"name": "Joint pain", "base": 0.20, "flare_coef": 0.30},
                {"name": "Night sweats", "base": 0.12, "flare_coef": 0.25},
            ],
            "planted": [
                {"kind": "missed_med_lag2", "med": "Azathioprine", "target": "Bloody stools", "hi": 0.78, "lo": 0.15},
                {"kind": "stress_lag1", "target": "Cramping", "thresh": 7, "hi": 0.88, "lo": 0.10},
                {"kind": "sleep_lag1", "target": "Fatigue", "thresh": 6.0, "hi": 0.95, "lo": 0.55},
            ],
            "notes": NOTES_CROHNS,
        },
    },
    {
        "code": "ENTYV1", "doctor": "hartley", "name": "Casey Nguyen",
        "condition": "ulcerative colitis",
        "medications": [
            {"name": "Vedolizumab", "brand": "Entyvio", "dose": "300mg", "frequency": "IV every 8 weeks"},
            {"name": "Mesalamine", "brand": "Lialda", "dose": "2.4g", "frequency": "once daily"},
            {"name": "Ferrous gluconate", "brand": "", "dose": "324mg", "frequency": "once daily"},
        ],
        "symptoms_to_watch": ["Diarrhea", "Urgency", "Cramping", "Fatigue", "Bloating"],
        "dietary_restrictions": ["Low-fiber / low-residue", "Dairy-free"],
        "doctor_notes": (
            "Pancolitis recovering after a severe flare; gut-selective vedolizumab working, "
            "CRP and calprotectin trending down. Received IV iron, ferritin slowly recovering. "
            "Patient reports symptoms ease on days she exercises. Continue maintenance infusions; "
            "encourage gentle regular activity."
        ),
        "lab_offset_days": 14,
        "lab_filename": "UC_Recovery_Labs_2026-05.pdf",
        "lab_summary": "Post-flare recovery: CRP and calprotectin improved but still mildly elevated, ferritin low and recovering post-infusion, hemoglobin low, vitamin D low, albumin normalized.",
        "labs": [
            {"test_name": "CRP", "value": "8.2", "unit": "mg/L", "reference_range": "0.0-5.0", "status": "HIGH"},
            {"test_name": "Calprotectin (fecal)", "value": "210", "unit": "mcg/g", "reference_range": "<50", "status": "HIGH"},
            {"test_name": "Ferritin", "value": "16", "unit": "ng/mL", "reference_range": "20-250", "status": "LOW"},
            {"test_name": "Hemoglobin", "value": "11.9", "unit": "g/dL", "reference_range": "12.0-16.0", "status": "LOW"},
            {"test_name": "Vitamin D 25-OH", "value": "23", "unit": "ng/mL", "reference_range": "30-100", "status": "LOW"},
            {"test_name": "Albumin", "value": "3.6", "unit": "g/dL", "reference_range": "3.5-5.0", "status": "NORMAL"},
            {"test_name": "Vitamin B12", "value": "410", "unit": "pg/mL", "reference_range": "200-900", "status": "NORMAL"},
        ],
        "story": {
            "salt": 505, "days": 60,
            "flare": {"base": 0.15, "amp": 0.55, "peak": -48, "width": 18},  # strong improving arc
            "stress": {"base": 4.5, "amp": 1.2, "noise": 1.3},
            "sleep": {"mean": 7.1, "sd": 1.0},
            "exercise_weights": [0.28, 0.32, 0.28, 0.12],
            "bm": {"base": 2.5, "flare_coef": 4.0, "noise": 0.8},
            "meds": [
                {"name": "Vedolizumab", "taken_prob": 0.98},
                {"name": "Mesalamine", "taken_prob": 0.92},
                {"name": "Ferrous gluconate", "taken_prob": 0.85},
            ],
            "foods": [
                {"name": "Caffeine", "prob": 0.38},
                {"name": "Dairy", "prob": 0.10},
                {"name": "Spicy Food", "prob": 0.16},
            ],
            "symptoms": [
                {"name": "Fatigue", "base": 0.35, "flare_coef": 0.35},
                {"name": "Diarrhea", "base": 0.25, "flare_coef": 0.45},
                {"name": "Bloating", "base": 0.18, "flare_coef": 0.25},
            ],
            "planted": [
                {"kind": "exercise_neg_lag1", "target": "Cramping", "active": 0.18, "inactive": 0.55},
                {"kind": "exercise_neg_lag1", "target": "Abdominal pain", "active": 0.15, "inactive": 0.50},
                {"kind": "food_same_day", "food": "Caffeine", "target": "Urgency", "hi": 0.62, "lo": 0.15},
            ],
            "notes": NOTES_UC,
        },
    },

    # ───────────────────────── Dr. Chen ─────────────────────────────────────
    {
        "code": "FIST01", "doctor": "chen", "name": "Riley Patel",
        "condition": "Crohn's disease",
        "medications": [
            {"name": "Infliximab", "brand": "Remicade", "dose": "5mg/kg", "frequency": "IV every 8 weeks"},
            {"name": "Azathioprine", "brand": "Imuran", "dose": "100mg", "frequency": "once daily"},
            {"name": "Metronidazole", "brand": "Flagyl", "dose": "500mg", "frequency": "three times daily"},
            {"name": "Ciprofloxacin", "brand": "Cipro", "dose": "500mg", "frequency": "twice daily"},
        ],
        "symptoms_to_watch": ["Abdominal pain", "Fever", "Night sweats", "Fatigue", "Joint pain", "Loss of appetite"],
        "dietary_restrictions": ["Low-fiber / low-residue"],
        "doctor_notes": (
            "Perianal fistulizing Crohn's with a drained abscess, on infliximab plus combination "
            "antibiotics and azathioprine. CRP and WBC elevated consistent with active perianal sepsis. "
            "Zinc low (impairs wound healing) and vitamin D low. Adherence to azathioprine inconsistent "
            "and correlates with pain flares. Reassess fistula response at next infusion."
        ),
        "lab_offset_days": 11,
        "lab_filename": "Crohns_Perianal_Labs_2026-05.pdf",
        "lab_summary": "Perianal fistulizing Crohn's: high CRP and WBC, anemia with low ferritin, low zinc and vitamin D, low albumin, borderline B12.",
        "labs": [
            {"test_name": "CRP", "value": "28.0", "unit": "mg/L", "reference_range": "0.0-5.0", "status": "HIGH"},
            {"test_name": "WBC", "value": "12.8", "unit": "10^3/uL", "reference_range": "4.0-11.0", "status": "HIGH"},
            {"test_name": "Zinc", "value": "48", "unit": "mcg/dL", "reference_range": "60-130", "status": "LOW"},
            {"test_name": "Vitamin D 25-OH", "value": "19", "unit": "ng/mL", "reference_range": "30-100", "status": "LOW"},
            {"test_name": "Ferritin", "value": "15", "unit": "ng/mL", "reference_range": "20-250", "status": "LOW"},
            {"test_name": "Hemoglobin", "value": "10.6", "unit": "g/dL", "reference_range": "13.5-17.5", "status": "LOW"},
            {"test_name": "Albumin", "value": "3.0", "unit": "g/dL", "reference_range": "3.5-5.0", "status": "LOW"},
            {"test_name": "Vitamin B12", "value": "205", "unit": "pg/mL", "reference_range": "200-900", "status": "NORMAL"},
        ],
        "story": {
            "salt": 606, "days": 54,
            "flare": {"base": 0.28, "amp": 0.32, "peak": -25, "width": 26},  # active, slowly settling
            "stress": {"base": 5.0, "amp": 1.5, "noise": 1.4},
            "sleep": {"mean": 6.3, "sd": 1.2},
            "exercise_weights": [0.55, 0.30, 0.12, 0.03],
            "bm": {"base": 3.5, "flare_coef": 4.0, "noise": 0.9},
            "meds": [
                {"name": "Infliximab", "taken_prob": 0.98},
                {"name": "Azathioprine", "taken_prob": 0.68},
                {"name": "Metronidazole", "taken_prob": 0.88},
                {"name": "Ciprofloxacin", "taken_prob": 0.88},
            ],
            "foods": [
                {"name": "Fried/Fatty", "prob": 0.24},
                {"name": "Caffeine", "prob": 0.30},
                {"name": "Spicy Food", "prob": 0.14},
            ],
            "symptoms": [
                {"name": "Abdominal pain", "base": 0.15, "flare_coef": 0.30},
                {"name": "Fatigue", "base": 0.50, "flare_coef": 0.30},
                {"name": "Fever", "base": 0.10, "flare_coef": 0.25},
                {"name": "Night sweats", "base": 0.15, "flare_coef": 0.25},
                {"name": "Joint pain", "base": 0.18, "flare_coef": 0.22},
                {"name": "Loss of appetite", "base": 0.18, "flare_coef": 0.30},
            ],
            "planted": [
                {"kind": "missed_med_lag2", "med": "Azathioprine", "target": "Abdominal pain", "hi": 0.85, "lo": 0.12},
                {"kind": "sleep_lag1", "target": "Fatigue", "thresh": 6.0, "hi": 0.93, "lo": 0.50},
            ],
            "notes": NOTES_CROHNS,
        },
    },
    {
        "code": "NEWCE1", "doctor": "chen", "name": "Devin Carter",
        "condition": "celiac disease",
        "medications": [
            {"name": "Ferrous sulfate", "brand": "", "dose": "325mg", "frequency": "once daily"},
            {"name": "Vitamin D3", "brand": "", "dose": "4000 IU", "frequency": "once daily"},
            {"name": "Folic acid", "brand": "", "dose": "1mg", "frequency": "once daily"},
            {"name": "Multivitamin", "brand": "", "dose": "1 tablet", "frequency": "once daily"},
        ],
        "symptoms_to_watch": ["Diarrhea", "Bloating", "Unintended weight loss", "Fatigue", "Abdominal pain", "Cramping"],
        "dietary_restrictions": ["Gluten-free"],
        "doctor_notes": (
            "Newly diagnosed celiac (Marsh 3b on biopsy) with severe malabsorption at presentation. "
            "Very high tTG, profound iron and folate deficiency, low vitamin D and calcium, low albumin. "
            "Learning the gluten-free diet; accidental exposures common early but declining as skills improve, "
            "with symptoms easing in parallel. Repeat serology and nutrient panel in 3 months."
        ),
        "lab_offset_days": 20,
        "lab_filename": "Celiac_Diagnosis_Labs_2026-05.pdf",
        "lab_summary": "Newly diagnosed celiac with malabsorption: very high tTG-IgA, severe iron deficiency and anemia, low folate, vitamin D, calcium, zinc, and albumin.",
        "labs": [
            {"test_name": "tTG-IgA", "value": "128", "unit": "U/mL", "reference_range": "<15", "status": "HIGH"},
            {"test_name": "Ferritin", "value": "5", "unit": "ng/mL", "reference_range": "20-250", "status": "LOW"},
            {"test_name": "Hemoglobin", "value": "10.0", "unit": "g/dL", "reference_range": "13.5-17.5", "status": "LOW"},
            {"test_name": "Folate", "value": "2.1", "unit": "ng/mL", "reference_range": "3.0-17.0", "status": "LOW"},
            {"test_name": "Vitamin D 25-OH", "value": "13", "unit": "ng/mL", "reference_range": "30-100", "status": "LOW"},
            {"test_name": "Calcium", "value": "8.3", "unit": "mg/dL", "reference_range": "8.6-10.2", "status": "LOW"},
            {"test_name": "Zinc", "value": "51", "unit": "mcg/dL", "reference_range": "60-130", "status": "LOW"},
            {"test_name": "Albumin", "value": "3.3", "unit": "g/dL", "reference_range": "3.5-5.0", "status": "LOW"},
        ],
        "story": {
            "salt": 707, "days": 48,
            "flare": {"base": 0.15, "amp": 0.50, "peak": -46, "width": 16},  # improving as GF adherence grows
            "stress": {"base": 4.8, "amp": 1.2, "noise": 1.4},
            "sleep": {"mean": 6.9, "sd": 1.1},
            "exercise_weights": [0.40, 0.35, 0.18, 0.07],
            "bm": {"base": 3.0, "flare_coef": 4.5, "noise": 0.8},
            "meds": [
                {"name": "Ferrous sulfate", "taken_prob": 0.85},
                {"name": "Vitamin D3", "taken_prob": 0.88},
                {"name": "Folic acid", "taken_prob": 0.85},
                {"name": "Multivitamin", "taken_prob": 0.80},
            ],
            "foods": [
                # accidental gluten high at first, declining as the patient learns
                {"name": "Gluten/Wheat", "prob_old": 0.45, "prob_new": 0.08},
                {"name": "Dairy", "prob": 0.30},
                {"name": "Caffeine", "prob": 0.28},
            ],
            "symptoms": [
                {"name": "Fatigue", "base": 0.40, "flare_coef": 0.35},
                {"name": "Unintended weight loss", "base": 0.15, "flare_coef": 0.30},
                {"name": "Cramping", "base": 0.18, "flare_coef": 0.30},
            ],
            "planted": [
                {"kind": "food_lag1", "food": "Gluten/Wheat", "target": "Diarrhea", "hi": 0.85, "lo": 0.12},
                {"kind": "food_lag1", "food": "Gluten/Wheat", "target": "Bloating", "hi": 0.82, "lo": 0.12},
                {"kind": "food_same_day", "food": "Gluten/Wheat", "target": "Abdominal pain", "hi": 0.72, "lo": 0.10},
            ],
            "notes": NOTES_CELIAC,
        },
    },
    {
        "code": "JAKUC1", "doctor": "chen", "name": "Quinn Foster",
        "condition": "ulcerative colitis",
        "medications": [
            {"name": "Tofacitinib", "brand": "Xeljanz", "dose": "10mg", "frequency": "twice daily"},
            {"name": "Mesalamine", "brand": "Lialda", "dose": "2.4g", "frequency": "once daily"},
        ],
        "symptoms_to_watch": ["Urgency", "Cramping", "Diarrhea", "Fatigue"],
        "dietary_restrictions": ["No restrictions"],
        "doctor_notes": (
            "Left-sided UC well-controlled on tofacitinib after failing a TNF inhibitor. "
            "Disease markers near normal, but JAK-inhibitor lipid effect is showing: total cholesterol, "
            "LDL, and triglycerides all elevated on the latest panel. Vitamin D mildly low. "
            "Plan: lipid recheck in 8 weeks, discuss diet and possible statin if persistent."
        ),
        "lab_offset_days": 13,
        "lab_filename": "UC_JAK_Lipid_Panel_2026-05.pdf",
        "lab_summary": "Controlled UC on a JAK inhibitor: CRP and calprotectin near normal, but elevated total cholesterol, LDL, and triglycerides (JAK lipid effect); vitamin D mildly low.",
        "labs": [
            {"test_name": "Total Cholesterol", "value": "248", "unit": "mg/dL", "reference_range": "<200", "status": "HIGH"},
            {"test_name": "LDL Cholesterol", "value": "165", "unit": "mg/dL", "reference_range": "<100", "status": "HIGH"},
            {"test_name": "HDL Cholesterol", "value": "52", "unit": "mg/dL", "reference_range": ">40", "status": "NORMAL"},
            {"test_name": "Triglycerides", "value": "180", "unit": "mg/dL", "reference_range": "<150", "status": "HIGH"},
            {"test_name": "CRP", "value": "3.2", "unit": "mg/L", "reference_range": "0.0-5.0", "status": "NORMAL"},
            {"test_name": "Calprotectin (fecal)", "value": "88", "unit": "mcg/g", "reference_range": "<50", "status": "HIGH"},
            {"test_name": "Vitamin D 25-OH", "value": "26", "unit": "ng/mL", "reference_range": "30-100", "status": "LOW"},
            {"test_name": "Ferritin", "value": "60", "unit": "ng/mL", "reference_range": "20-250", "status": "NORMAL"},
            {"test_name": "Hemoglobin", "value": "13.8", "unit": "g/dL", "reference_range": "12.0-16.0", "status": "NORMAL"},
        ],
        "story": {
            "salt": 808, "days": 60,
            "flare": {"base": 0.08, "amp": 0.16, "peak": -22, "width": 20},  # mild, controlled
            "stress": {"base": 5.2, "amp": 1.0, "noise": 1.6},
            "sleep": {"mean": 6.7, "sd": 1.2},
            "exercise_weights": [0.32, 0.34, 0.24, 0.10],
            "bm": {"base": 1.8, "flare_coef": 2.5, "noise": 0.7},
            "meds": [
                {"name": "Tofacitinib", "taken_prob": 0.95},
                {"name": "Mesalamine", "taken_prob": 0.93},
            ],
            "foods": [
                {"name": "Caffeine", "prob": 0.50},
                {"name": "Fried/Fatty", "prob": 0.28},
                {"name": "Alcohol", "prob": 0.18},
            ],
            "symptoms": [
                {"name": "Cramping", "base": 0.12, "flare_coef": 0.25},
                {"name": "Diarrhea", "base": 0.15, "flare_coef": 0.30},
            ],
            "planted": [
                {"kind": "stress_lag1", "target": "Urgency", "thresh": 6, "hi": 0.70, "lo": 0.12},
                {"kind": "sleep_lag1", "target": "Fatigue", "thresh": 6.0, "hi": 0.85, "lo": 0.35},
            ],
            "notes": NOTES_UC,
        },
    },
    {
        "code": "MALNU1", "doctor": "chen", "name": "Avery Sullivan",
        "condition": "Crohn's disease",
        "medications": [
            {"name": "Ustekinumab", "brand": "Stelara", "dose": "90mg", "frequency": "SC every 8 weeks"},
            {"name": "Pantoprazole", "brand": "Protonix", "dose": "40mg", "frequency": "once daily"},
            {"name": "Oral nutrition supplement", "brand": "Ensure", "dose": "2 servings", "frequency": "daily"},
            {"name": "Vitamin B12 injection", "brand": "", "dose": "1000mcg", "frequency": "monthly"},
        ],
        "symptoms_to_watch": ["Nausea", "Vomiting", "Loss of appetite", "Unintended weight loss", "Fatigue", "Abdominal pain"],
        "dietary_restrictions": ["Lactose intolerant (avoids dairy)", "Low-fiber / low-residue"],
        "doctor_notes": (
            "Gastroduodenal Crohn's with protein-calorie malnutrition and significant weight loss. "
            "On ustekinumab with oral nutrition support and a PPI for upper-GI symptoms. "
            "Albumin and prealbumin low; multiple micronutrient deficiencies (B12, D, iron, magnesium, "
            "zinc, vitamin A). Nausea eases on days the PPI is taken. Dietitian co-managing; "
            "monitor weight weekly."
        ),
        "lab_offset_days": 17,
        "lab_filename": "Crohns_Malnutrition_Panel_2026-05.pdf",
        "lab_summary": "Malnutrition panel: low albumin and prealbumin, anemia, and broad micronutrient deficiency (B12, vitamin D, iron, magnesium, zinc, vitamin A).",
        "labs": [
            {"test_name": "Albumin", "value": "2.7", "unit": "g/dL", "reference_range": "3.5-5.0", "status": "LOW"},
            {"test_name": "Prealbumin", "value": "11", "unit": "mg/dL", "reference_range": "18-45", "status": "LOW"},
            {"test_name": "Vitamin B12", "value": "180", "unit": "pg/mL", "reference_range": "200-900", "status": "LOW"},
            {"test_name": "Vitamin D 25-OH", "value": "16", "unit": "ng/mL", "reference_range": "30-100", "status": "LOW"},
            {"test_name": "Ferritin", "value": "12", "unit": "ng/mL", "reference_range": "20-250", "status": "LOW"},
            {"test_name": "Magnesium", "value": "1.4", "unit": "mg/dL", "reference_range": "1.7-2.2", "status": "LOW"},
            {"test_name": "Zinc", "value": "46", "unit": "mcg/dL", "reference_range": "60-130", "status": "LOW"},
            {"test_name": "Vitamin A", "value": "0.18", "unit": "mg/L", "reference_range": "0.30-0.70", "status": "LOW"},
            {"test_name": "Hemoglobin", "value": "10.4", "unit": "g/dL", "reference_range": "13.5-17.5", "status": "LOW"},
        ],
        "story": {
            "salt": 909, "days": 52,
            "flare": {"base": 0.30, "amp": 0.40, "peak": -40, "width": 18},  # slowly improving on Stelara
            "stress": {"base": 4.8, "amp": 1.3, "noise": 1.4},
            "sleep": {"mean": 6.6, "sd": 1.1},
            "exercise_weights": [0.62, 0.28, 0.08, 0.02],
            "bm": {"base": 2.5, "flare_coef": 3.5, "noise": 0.8},
            "meds": [
                {"name": "Ustekinumab", "taken_prob": 0.98},
                {"name": "Pantoprazole", "taken_prob": 0.78},
                {"name": "Oral nutrition supplement", "taken_prob": 0.75},
                {"name": "Vitamin B12 injection", "taken_prob": 0.97},
            ],
            "foods": [
                {"name": "Dairy", "prob": 0.12},
                {"name": "Fried/Fatty", "prob": 0.20},
                {"name": "Caffeine", "prob": 0.22},
            ],
            "symptoms": [
                {"name": "Loss of appetite", "base": 0.45, "flare_coef": 0.30},
                {"name": "Unintended weight loss", "base": 0.30, "flare_coef": 0.25},
                {"name": "Fatigue", "base": 0.55, "flare_coef": 0.25},
                {"name": "Abdominal pain", "base": 0.25, "flare_coef": 0.30},
                {"name": "Vomiting", "base": 0.08, "flare_coef": 0.20},
            ],
            "planted": [
                {"kind": "missed_med_lag1", "med": "Pantoprazole", "target": "Nausea", "hi": 0.80, "lo": 0.18},
                {"kind": "stress_lag1", "target": "Abdominal pain", "thresh": 6, "hi": 0.70, "lo": 0.18},
            ],
            "notes": NOTES_CROHNS,
        },
    },
]


# ── Seeding plumbing ─────────────────────────────────────────────────────────

def _get_or_create_doctor(key: str) -> str:
    d = DOCTORS[key]
    with _conn() as conn:
        row = conn.execute("SELECT id FROM doctors WHERE access_code = ?", (d["code"],)).fetchone()
        if row:
            print(f"Doctor exists: {d['name']} ({d['code']})")
            return row["id"]
        doc_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO doctors (id, name, practice, access_code, created_at) VALUES (?,?,?,?,?)",
            (doc_id, d["name"], d["practice"], d["code"], datetime.utcnow().isoformat()),
        )
        conn.commit()
    print(f"Created doctor: {d['name']} -> {d['code']}")
    return doc_id


def _get_or_create_patient(cfg: dict, doctor_id: str) -> tuple[str, bool]:
    """Return (patient_id, created)."""
    with _conn() as conn:
        row = conn.execute("SELECT id FROM patients WHERE access_code = ?", (cfg["code"],)).fetchone()
        if row:
            print(f"  Patient exists: {cfg['name']} ({cfg['code']})")
            return row["id"], False
        patient_id = uuid.uuid4().hex
        conn.execute(
            """INSERT INTO patients
               (id, doctor_id, access_code, name, condition, medications,
                symptoms_to_watch, dietary_restrictions, doctor_notes, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                patient_id, doctor_id, cfg["code"], cfg["name"], cfg["condition"],
                json.dumps(cfg["medications"]),
                json.dumps(cfg["symptoms_to_watch"]),
                json.dumps(cfg["dietary_restrictions"]),
                cfg["doctor_notes"],
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
    print(f"  Created patient: {cfg['name']} [{cfg['condition']}] -> {cfg['code']}")
    return patient_id, True


def _has_entries(patient_id: str) -> bool:
    with _conn() as conn:
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM journal_entries WHERE patient_id = ?", (patient_id,)
        ).fetchone()["c"]
    return n > 0


def _has_labs(patient_id: str) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT id FROM lab_values WHERE patient_id = ? AND confirmed = 1", (patient_id,)
        ).fetchone()
    return row is not None


def _seed_entries(patient_id: str, story: dict) -> None:
    today = date.today()
    days = story["days"]
    inserted = 0
    with _conn() as conn:
        for offset in range(-days + 1, 0):  # leave today open to log fresh
            d = today + timedelta(days=offset)
            entry = make_entry(offset, story)
            conn.execute(
                """INSERT OR IGNORE INTO journal_entries
                   (id, patient_id, date, symptoms_today, medications_taken,
                    stress_level, notes, extra, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    uuid.uuid4().hex[:16], patient_id, d.isoformat(),
                    json.dumps(entry["symptoms_today"]),
                    json.dumps(entry["medications_taken"]),
                    entry["stress_level"], entry["notes"],
                    json.dumps(entry["extra"]),
                    datetime.utcnow().isoformat(),
                ),
            )
            inserted += 1
        conn.commit()
    print(f"    {inserted} journal entries seeded ({days}-day history).")


def _seed_labs(patient_id: str, cfg: dict) -> None:
    lab_date = (date.today() - timedelta(days=cfg["lab_offset_days"])).isoformat()
    doc_id = uuid.uuid4().hex
    # Build the panel with a test_date on each row for the report renderer.
    panel = [{**lv, "test_date": lab_date} for lv in cfg["labs"]]
    pdf_path = ROOT / "uploads" / f"{doc_id}.pdf"
    write_lab_report_pdf(
        pdf_path,
        patient_name=cfg["name"],
        condition=cfg["condition"],
        report_title=title_from_filename(cfg["lab_filename"]),
        panel=panel,
        lab_date=lab_date,
        summary=cfg["lab_summary"],
    )
    with _conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO patient_documents
               (id, patient_id, filename, doc_type, upload_date, indexed, summary, stored_path)
               VALUES (?,?,?,?,?,?,?,?)""",
            (doc_id, patient_id, cfg["lab_filename"], "lab_results", lab_date, 1,
             cfg["lab_summary"], str(pdf_path)),
        )
        rows = [
            (
                uuid.uuid4().hex, patient_id, doc_id,
                lv["test_name"], lv["value"], lv["unit"],
                lv["reference_range"], lv["status"], lab_date, 1,
            )
            for lv in cfg["labs"]
        ]
        conn.executemany(
            """INSERT OR IGNORE INTO lab_values
               (id, patient_id, document_id, test_name, value, unit,
                reference_range, status, test_date, confirmed)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        conn.commit()
    print(f"    {len(cfg['labs'])} confirmed lab values seeded.")


def main() -> None:
    init_db()
    doctor_ids = {key: _get_or_create_doctor(key) for key in DOCTORS}

    for cfg in PATIENTS:
        doctor_id = doctor_ids[cfg["doctor"]]
        patient_id, created = _get_or_create_patient(cfg, doctor_id)
        if created or not _has_entries(patient_id):
            _seed_entries(patient_id, cfg["story"])
        else:
            print("    entries already present, skipped.")
        if created or not _has_labs(patient_id):
            _seed_labs(patient_id, cfg)
        else:
            print("    labs already present, skipped.")

    print()
    print("=" * 56)
    print("  Demo logins")
    print("=" * 56)
    for key, d in DOCTORS.items():
        print(f"\n  {d['name']}  ->  {d['code']}  ({d['practice']})")
        for cfg in PATIENTS:
            if cfg["doctor"] == key:
                print(f"      {cfg['code']:<8} {cfg['name']:<16} {cfg['condition']}")
    print("\n  (existing) Dr. Elena Hartley patient: DEMO01  Alex Morgan  ulcerative colitis")
    print("=" * 56)


if __name__ == "__main__":
    main()
