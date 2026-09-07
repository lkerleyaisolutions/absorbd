"""Seed a demo doctor + patient with 62 days of journal history and confirmed lab values.

Doctor code : DOC-DEMO1
Patient code : DEMO01

Safe to re-run -- skips creation if codes already exist.
62 days gives n >= 30 for confirmed correlations (Spearman BH-FDR).
Planted correlations: high stress (>=7) -> Cramping next day (lag 1, r ~0.5+).

Run:  venv/Scripts/python.exe scripts/seed_demo.py
"""

from __future__ import annotations

import json
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

LAB_FILENAME = "CBC_Metabolic_Panel_2026-05.pdf"
LAB_SUMMARY = "CBC and metabolic panel showing anemia, low ferritin, elevated CRP, low Vitamin D and Zinc."

# ── Fixed identifiers ────────────────────────────────────────────────────────

DOCTOR_CODE = "DOC-DEMO1"
PATIENT_CODE = "DEMO01"

DOCTOR = {
    "name": "Dr. Elena Hartley",
    "practice": "GI Associates of Boston",
}

PATIENT = {
    "name": "Alex Morgan",
    "condition": "ulcerative colitis",
    "medications": [
        {"name": "Mesalamine", "brand": "Lialda", "dose": "2.4g", "frequency": "once daily"},
        {"name": "Prednisone", "brand": "Deltasone", "dose": "10mg", "frequency": "once daily"},
        {"name": "Azathioprine", "brand": "Imuran", "dose": "100mg", "frequency": "once daily"},
    ],
    "symptoms_to_watch": [
        "Diarrhea", "Bloody stools", "Abdominal pain", "Urgency",
        "Fatigue", "Cramping", "Bloating", "Nausea",
    ],
    "dietary_restrictions": ["Gluten-free", "Low-fiber during flares"],
    "doctor_notes": (
        "Patient in moderate flare since April. Monitor bloody stools closely. "
        "Prednisone taper planned if no improvement in 2 weeks. "
        "Ferritin was critically low on last labs -- ensure iron-rich foods."
    ),
}

# ── Lab values (pre-confirmed) ───────────────────────────────────────────────

LAB_DATE = (date.today() - timedelta(days=18)).isoformat()

LABS = [
    {"test_name": "Ferritin",           "value": "6",    "unit": "ng/mL",  "reference_range": "20-250",   "status": "LOW",    "test_date": LAB_DATE},
    {"test_name": "Hemoglobin",         "value": "10.2", "unit": "g/dL",   "reference_range": "12.0-16.0","status": "LOW",    "test_date": LAB_DATE},
    {"test_name": "Vitamin D 25-OH",    "value": "18",   "unit": "ng/mL",  "reference_range": "30-100",   "status": "LOW",    "test_date": LAB_DATE},
    {"test_name": "CRP",                "value": "24.1", "unit": "mg/L",   "reference_range": "0.0-5.0",  "status": "HIGH",   "test_date": LAB_DATE},
    {"test_name": "Albumin",            "value": "3.2",  "unit": "g/dL",   "reference_range": "3.5-5.0",  "status": "LOW",    "test_date": LAB_DATE},
    {"test_name": "Folate",             "value": "4.1",  "unit": "ng/mL",  "reference_range": "3.0-17.0", "status": "NORMAL", "test_date": LAB_DATE},
    {"test_name": "Vitamin B12",        "value": "312",  "unit": "pg/mL",  "reference_range": "200-900",  "status": "NORMAL", "test_date": LAB_DATE},
    {"test_name": "Zinc",               "value": "52",   "unit": "mcg/dL", "reference_range": "60-130",   "status": "LOW",    "test_date": LAB_DATE},
    {"test_name": "Calprotectin (fecal)","value": "890", "unit": "mcg/g",  "reference_range": "<50",      "status": "HIGH",   "test_date": LAB_DATE},
]

# ── Journal entry generator ──────────────────────────────────────────────────
# Planted correlations (for statistical verification):
#   stress >= 7  ->  Cramping on next day         (lag 1, r ~0.55)
#   Dairy eaten  ->  Diarrhea on next day          (lag 1, r ~0.45)
#   Missed Azathioprine -> Bloody stools lag 2    (lag 2, r ~0.40)
#   Short sleep (< 6h) -> Fatigue next day         (lag 1, weak/noisy)
# NOTE: sleep_hours and exercise are INDEPENDENT draws, deliberately NOT derived
# from stress/flare. The only sleep signal is the honest lag-1 Fatigue nudge above.

def _stress_for_day(offset: int) -> int:
    """Deterministic stress value for a given day offset. Used for lag plantings."""
    rng = random.Random(offset + 42)
    flare = max(0.0, min(1.0, 0.85 - abs(offset + 30) * 0.025))
    return max(1, min(10, round(5 + flare * 3 + rng.gauss(0, 1.2))))


def _ate_dairy_on_day(offset: int) -> bool:
    """Deterministic dairy-eating flag for a given day."""
    rng = random.Random(offset + 99)
    return rng.random() < 0.28  # 28% of days


def _missed_aza_on_day(offset: int) -> bool:
    """Deterministic Azathioprine-missed flag for a given day."""
    rng = random.Random(offset + 77)
    return rng.random() > 0.70  # 30% miss rate


def _sleep_for_day(offset: int) -> float:
    """Deterministic sleep_hours for a given day offset.

    Independent of stress/flare -- its own Gaussian draw. Used both as the
    stored value and as a lag-1 input so a clean (noisy) sleep -> Fatigue
    signal can be planted without making sleep a function of stress.
    """
    rng = random.Random(offset + 123)
    return round(max(4.5, min(9.5, rng.gauss(7.0, 1.1))), 1)


def _make_entry(day_offset: int) -> dict:
    """day_offset=0 is today, negative = past."""
    rng = random.Random(day_offset + 42)  # deterministic per day

    # Flare severity: worse ~30 days ago, improving more recently
    flare = max(0.0, min(1.0, 0.85 - abs(day_offset + 30) * 0.025))

    stress = _stress_for_day(day_offset)
    prev_stress = _stress_for_day(day_offset - 1)
    prev_dairy = _ate_dairy_on_day(day_offset - 1)
    missed_aza_two_days_ago = _missed_aza_on_day(day_offset - 2)
    prev_sleep = _sleep_for_day(day_offset - 1)

    symptoms = []

    # Fatigue: high baseline, with a planted honest lag-1 sleep signal.
    # Short sleep yesterday (< 6h) modestly raises Fatigue today. This is a real
    # but noisy probabilistic nudge (not a deterministic formula), so the engine
    # can legitimately recover a sleep -> Fatigue finding.
    fatigue_prob = 0.95 if prev_sleep < 6.0 else 0.84
    if rng.random() < fatigue_prob:
        symptoms.append("Fatigue")
    if rng.random() < 0.78 + flare * 0.15:
        symptoms.append("Diarrhea")
    # Dairy lag-1 planted: eating dairy yesterday -> higher Diarrhea chance today
    if prev_dairy and rng.random() < 0.65:
        if "Diarrhea" not in symptoms:
            symptoms.append("Diarrhea")

    # Flare-driven symptoms
    if rng.random() < 0.45 + flare * 0.40:
        symptoms.append("Abdominal pain")

    # Cramping: planted lag-1 stress correlation (strong signal for demo)
    # High stress yesterday (>=7) -> 90% cramping today; low stress -> 8%
    cramping_prob = 0.90 if prev_stress >= 7 else 0.08
    if rng.random() < cramping_prob:
        symptoms.append("Cramping")

    if rng.random() < 0.28 + flare * 0.50:
        symptoms.append("Urgency")

    # Bloody stools: planted lag-2 Azathioprine-missed correlation
    # Missed Aza 2 days ago -> 75% bloody stools; otherwise 15% base rate
    bloody_prob = 0.75 if missed_aza_two_days_ago else 0.15
    if rng.random() < bloody_prob:
        symptoms.append("Bloody stools")

    if rng.random() < 0.22 + flare * 0.30:
        symptoms.append("Bloating")
    if rng.random() < 0.12 + flare * 0.20:
        symptoms.append("Nausea")

    # Medication adherence -- use name keys (matching journal agent's _med_key)
    meds_taken = {
        "Mesalamine": "taken",
        "Prednisone": "taken" if rng.random() < 0.88 else "missed",
        "Azathioprine": "missed" if _missed_aza_on_day(day_offset) else "taken",
    }

    # Extra fields for correlation engine.
    # sleep_hours and exercise are INDEPENDENT draws -- deliberately NOT functions
    # of stress or flare. Deriving them from the master signals would let the
    # correlation engine "rediscover" the stress/flare signal laundered through a
    # formula, which is manufactured significance. These get their own noise.
    sleep_hours = _sleep_for_day(day_offset)
    bm_count = max(0, round(2 + flare * 5 + rng.gauss(0, 0.8)))
    # Exercise: independent of flare/stress, drawn from a fixed activity mix.
    exercise = rng.choices(
        ["None", "Light walk", "Moderate", "Intense"],
        weights=[0.40, 0.35, 0.18, 0.07],
    )[0]
    food_today = []
    if _ate_dairy_on_day(day_offset):
        food_today.append("Dairy")
    if rng.random() < 0.12:
        food_today.append("Gluten/Wheat")
    if rng.random() < 0.18:
        food_today.append("Spicy Food")
    if rng.random() < 0.10:
        food_today.append("Caffeine")

    notes_pool = [
        "Rough morning, felt better by evening.",
        "Had to cancel plans because of urgency.",
        "Work was stressful today.",
        "Sleep was poor, up twice overnight.",
        "Feeling slightly better than yesterday.",
        "Diet was plain rice and chicken.",
        "",
        "",
    ]
    notes = rng.choice(notes_pool) if rng.random() < 0.50 else ""

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


# ── Seed logic ───────────────────────────────────────────────────────────────

def _get_or_create_doctor() -> str:
    with _conn() as conn:
        row = conn.execute(
            "SELECT id FROM doctors WHERE access_code = ?", (DOCTOR_CODE,)
        ).fetchone()
        if row:
            print(f"Doctor already exists (code: {DOCTOR_CODE})")
            return row["id"]

        doc_id = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO doctors (id, name, practice, access_code, created_at) VALUES (?,?,?,?,?)",
            (doc_id, DOCTOR["name"], DOCTOR["practice"], DOCTOR_CODE, datetime.utcnow().isoformat()),
        )
        conn.commit()
    print(f"Created doctor '{DOCTOR['name']}' -> {DOCTOR_CODE}")
    return doc_id


def _get_or_create_patient(doctor_id: str) -> str:
    with _conn() as conn:
        row = conn.execute(
            "SELECT id FROM patients WHERE access_code = ?", (PATIENT_CODE,)
        ).fetchone()
        if row:
            # Backfill the name on a demo patient seeded before the name column existed.
            conn.execute(
                "UPDATE patients SET name = ? WHERE access_code = ? AND (name IS NULL OR name = '')",
                (PATIENT["name"], PATIENT_CODE),
            )
            conn.commit()
            print(f"Patient already exists (code: {PATIENT_CODE})")
            return row["id"]

        patient_id = uuid.uuid4().hex
        conn.execute(
            """INSERT INTO patients
               (id, doctor_id, access_code, name, condition, medications,
                symptoms_to_watch, dietary_restrictions, doctor_notes, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                patient_id,
                doctor_id,
                PATIENT_CODE,
                PATIENT["name"],
                PATIENT["condition"],
                json.dumps(PATIENT["medications"]),
                json.dumps(PATIENT["symptoms_to_watch"]),
                json.dumps(PATIENT["dietary_restrictions"]),
                PATIENT["doctor_notes"],
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
    print(f"Created patient (UC) -> {PATIENT_CODE}")
    return patient_id


def _seed_entries(patient_id: str, days: int = 62) -> None:
    """Clear existing entries for this patient and insert fresh seeded data."""
    today = date.today()
    with _conn() as conn:
        deleted = conn.execute(
            "DELETE FROM journal_entries WHERE patient_id = ?", (patient_id,)
        ).rowcount
        conn.commit()
    if deleted:
        print(f"Cleared {deleted} old journal entries.")

    inserted = 0
    with _conn() as conn:
        for offset in range(-days + 1, 0):  # skip today so patient can log it fresh
            d = today + timedelta(days=offset)
            entry = _make_entry(offset)
            entry_id = uuid.uuid4().hex[:16]
            conn.execute(
                """INSERT INTO journal_entries
                   (id, patient_id, date, symptoms_today, medications_taken,
                    stress_level, notes, extra, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    entry_id,
                    patient_id,
                    d.isoformat(),
                    json.dumps(entry["symptoms_today"]),
                    json.dumps(entry["medications_taken"]),
                    entry["stress_level"],
                    entry["notes"],
                    json.dumps(entry.get("extra", {})),
                    datetime.utcnow().isoformat(),
                ),
            )
            inserted += 1
        conn.commit()
    print(f"Journal entries: {inserted} inserted fresh.")


def _seed_labs(patient_id: str) -> None:
    doc_id = uuid.uuid4().hex
    with _conn() as conn:
        existing = conn.execute(
            "SELECT id FROM lab_values WHERE patient_id = ? AND confirmed = 1",
            (patient_id,),
        ).fetchone()
        if existing:
            print("Lab values already seeded.")
            return

        # Generate the backing lab-report PDF so the document is openable.
        pdf_path = ROOT / "uploads" / f"{doc_id}.pdf"
        write_lab_report_pdf(
            pdf_path,
            patient_name=PATIENT["name"],
            condition=PATIENT["condition"],
            report_title=title_from_filename(LAB_FILENAME),
            panel=LABS,
            lab_date=LAB_DATE,
            summary=LAB_SUMMARY,
        )

        # Create the document record, pointing stored_path at the generated PDF.
        conn.execute(
            """INSERT OR IGNORE INTO patient_documents
               (id, patient_id, filename, doc_type, upload_date, indexed, summary, stored_path)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                doc_id,
                patient_id,
                LAB_FILENAME,
                "lab_results",
                LAB_DATE,
                1,
                LAB_SUMMARY,
                str(pdf_path),
            ),
        )
        rows = [
            (
                uuid.uuid4().hex,
                patient_id,
                doc_id,
                lv["test_name"],
                lv["value"],
                lv["unit"],
                lv["reference_range"],
                lv["status"],
                lv["test_date"],
                1,  # confirmed
            )
            for lv in LABS
        ]
        conn.executemany(
            """INSERT OR IGNORE INTO lab_values
               (id, patient_id, document_id, test_name, value, unit,
                reference_range, status, test_date, confirmed)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        conn.commit()
    print(f"Seeded {len(LABS)} confirmed lab values.")


def main() -> None:
    init_db()
    doctor_id = _get_or_create_doctor()
    patient_id = _get_or_create_patient(doctor_id)
    _seed_entries(patient_id)
    _seed_labs(patient_id)
    print()
    print("=" * 40)
    print(f"  Doctor login : {DOCTOR_CODE}")
    print(f"  Patient login: {PATIENT_CODE}")
    print("=" * 40)


if __name__ == "__main__":
    main()
