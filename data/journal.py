"""SQLite persistence layer for Absorbd.

Five tables:
  doctors           -- one row per clinician (created at setup)
  patients          -- one row per patient (created by doctor)
  journal_entries   -- daily check-in rows (one per patient per day)
  patient_documents -- uploaded lab PDFs / clinical notes
  lab_values        -- individual test results extracted from documents

The DB file lives at the repo root and is gitignored.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import string
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone


def _utcnow_iso() -> str:
    """Naive UTC timestamp in ISO format (matches the historic datetime.utcnow()
    string format, without the deprecation warning)."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "absorb-iq-journal.db"


# ── Connection helper ────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ── Access-code generators ───────────────────────────────────────────────────

def _doctor_code() -> str:
    # secrets, not random: these codes are the only credential in the system.
    chars = string.ascii_uppercase + string.digits
    return "DOC-" + "".join(secrets.choice(chars) for _ in range(5))


def _patient_code() -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(6))


# ── Schema creation ──────────────────────────────────────────────────────────

def init_db() -> None:
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS doctors (
                id          TEXT PRIMARY KEY,
                name        TEXT,
                practice    TEXT,
                access_code TEXT UNIQUE,
                created_at  TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS patients (
                id                   TEXT PRIMARY KEY,
                doctor_id            TEXT REFERENCES doctors(id),
                access_code          TEXT UNIQUE,
                condition            TEXT,
                medications          TEXT,
                symptoms_to_watch    TEXT,
                dietary_restrictions TEXT,
                doctor_notes         TEXT,
                created_at           TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS journal_entries (
                id                TEXT PRIMARY KEY,
                patient_id        TEXT REFERENCES patients(id),
                date              TEXT,
                symptoms_today    TEXT,
                medications_taken TEXT,
                stress_level      INTEGER,
                notes             TEXT,
                created_at        TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS patient_documents (
                id          TEXT PRIMARY KEY,
                patient_id  TEXT REFERENCES patients(id),
                filename    TEXT,
                doc_type    TEXT,
                upload_date TEXT,
                indexed     INTEGER DEFAULT 0,
                summary     TEXT,
                file_hash   TEXT,
                stored_path TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lab_values (
                id              TEXT PRIMARY KEY,
                patient_id      TEXT REFERENCES patients(id),
                document_id     TEXT REFERENCES patient_documents(id),
                test_name       TEXT,
                value           TEXT,
                unit            TEXT,
                reference_range TEXT,
                status          TEXT,
                test_date       TEXT,
                confirmed       INTEGER DEFAULT 0
            )
        """)
        # Deduplicate before creating unique index (keep newest row per patient+date)
        conn.execute("""
            DELETE FROM journal_entries
            WHERE rowid NOT IN (
                SELECT MIN(rowid) FROM journal_entries
                GROUP BY patient_id, date
            )
        """)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_je_patient_date ON journal_entries(patient_id, date)"
        )
        # Idempotent migrations
        try:
            conn.execute("ALTER TABLE journal_entries ADD COLUMN extra TEXT DEFAULT '{}'")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE patient_documents ADD COLUMN file_hash TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE patient_documents ADD COLUMN stored_path TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE patients ADD COLUMN name TEXT")
        except sqlite3.OperationalError:
            pass
        conn.commit()


# ── Doctor functions ─────────────────────────────────────────────────────────

def create_doctor(name: str, practice: str) -> dict:
    doc_id = uuid.uuid4().hex
    code = _doctor_code()
    with _conn() as conn:
        # Retry on unlikely collision
        while True:
            try:
                conn.execute(
                    "INSERT INTO doctors (id, name, practice, access_code, created_at) VALUES (?,?,?,?,?)",
                    (doc_id, name, practice, code, _utcnow_iso()),
                )
                conn.commit()
                break
            except sqlite3.IntegrityError:
                code = _doctor_code()
    return {"id": doc_id, "access_code": code}


def get_doctor_by_code(code: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM doctors WHERE access_code = ?", (code.upper(),)
        ).fetchone()
    if not row:
        return None
    return {"id": row["id"], "name": row["name"], "practice": row["practice"], "access_code": row["access_code"]}


def get_doctor_by_id(doctor_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
    if not row:
        return None
    return {"id": row["id"], "name": row["name"], "practice": row["practice"], "access_code": row["access_code"]}


# ── Patient functions ────────────────────────────────────────────────────────

def create_patient(
    doctor_id: str,
    condition: str,
    medications: list[dict],
    symptoms_to_watch: list[str],
    dietary_restrictions: list[str],
    doctor_notes: str = "",
    name: str = "",
) -> dict:
    patient_id = uuid.uuid4().hex
    code = _patient_code()
    with _conn() as conn:
        while True:
            try:
                conn.execute(
                    """INSERT INTO patients
                       (id, doctor_id, access_code, name, condition, medications,
                        symptoms_to_watch, dietary_restrictions, doctor_notes, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        patient_id,
                        doctor_id,
                        code,
                        name,
                        condition,
                        json.dumps(medications),
                        json.dumps(symptoms_to_watch),
                        json.dumps(dietary_restrictions),
                        doctor_notes,
                        _utcnow_iso(),
                    ),
                )
                conn.commit()
                break
            except sqlite3.IntegrityError:
                code = _patient_code()
    return {"id": patient_id, "access_code": code}


def get_patient_by_code(code: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM patients WHERE access_code = ?", (code.upper(),)
        ).fetchone()
    if not row:
        return None
    return _patient_row_to_dict(row)


def get_patient_by_id(patient_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
    if not row:
        return None
    return _patient_row_to_dict(row)


def _patient_row_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "doctor_id": row["doctor_id"],
        "access_code": row["access_code"],
        "name": (row["name"] or "") if "name" in row.keys() else "",
        "condition": row["condition"],
        "medications": json.loads(row["medications"] or "[]"),
        "symptoms_to_watch": json.loads(row["symptoms_to_watch"] or "[]"),
        "dietary_restrictions": json.loads(row["dietary_restrictions"] or "[]"),
        "doctor_notes": row["doctor_notes"] or "",
        "created_at": row["created_at"],
    }


def get_doctor_patients(doctor_id: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM patients WHERE doctor_id = ? ORDER BY created_at DESC",
            (doctor_id,),
        ).fetchall()
    patients = []
    for row in rows:
        p = _patient_row_to_dict(row)
        stats = get_patient_stats(p["id"], days=7)
        p.update(stats)
        patients.append(p)
    return patients


# ── Journal entry functions ──────────────────────────────────────────────────

def add_entry(
    patient_id: str,
    symptoms_today: list[str],
    medications_taken: dict[str, str],
    stress_level: int,
    notes: str,
    entry_date: str | None = None,
    extra: dict | None = None,
) -> str:
    day = entry_date or date.today().isoformat()
    now = _utcnow_iso()
    extra_json = json.dumps(extra or {})
    with _conn() as conn:
        existing = conn.execute(
            "SELECT id FROM journal_entries WHERE patient_id = ? AND date = ?",
            (patient_id, day),
        ).fetchone()
        if existing:
            entry_id = existing["id"]
            conn.execute(
                """UPDATE journal_entries
                   SET symptoms_today=?, medications_taken=?, stress_level=?, notes=?, extra=?, created_at=?
                   WHERE id=?""",
                (json.dumps(symptoms_today), json.dumps(medications_taken),
                 int(stress_level), notes or "", extra_json, now, entry_id),
            )
        else:
            entry_id = uuid.uuid4().hex[:16]
            conn.execute(
                """INSERT INTO journal_entries
                   (id, patient_id, date, symptoms_today, medications_taken,
                    stress_level, notes, extra, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (entry_id, patient_id, day,
                 json.dumps(symptoms_today), json.dumps(medications_taken),
                 int(stress_level), notes or "", extra_json, now),
            )
        conn.commit()
    return entry_id


def get_entries(patient_id: str, days: int = 30) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT * FROM journal_entries
               WHERE patient_id = ?
                 AND date >= date('now', '-' || ? || ' days')
               ORDER BY date DESC""",
            (patient_id, days),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "date": r["date"],
            "symptoms_today": json.loads(r["symptoms_today"] or "[]"),
            "medications_taken": json.loads(r["medications_taken"] or "{}"),
            "stress_level": r["stress_level"],
            "notes": r["notes"],
            "extra": json.loads(r["extra"] or "{}") if r["extra"] else {},
        }
        for r in rows
    ]


def has_entry_today(patient_id: str) -> bool:
    today = date.today().isoformat()
    with _conn() as conn:
        row = conn.execute(
            "SELECT id FROM journal_entries WHERE patient_id = ? AND date = ?",
            (patient_id, today),
        ).fetchone()
    return row is not None


def get_yesterday_entry(patient_id: str) -> dict | None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM journal_entries WHERE patient_id = ? AND date = ?",
            (patient_id, yesterday),
        ).fetchone()
    if not row:
        return None
    return {
        "date": row["date"],
        "symptoms_today": json.loads(row["symptoms_today"] or "[]"),
        "medications_taken": json.loads(row["medications_taken"] or "{}"),
        "stress_level": row["stress_level"],
        "notes": row["notes"],
        "extra": json.loads(row["extra"] or "{}") if row["extra"] else {},
    }


# ── Document + lab functions ─────────────────────────────────────────────────

def get_document_by_hash(patient_id: str, file_hash: str) -> dict | None:
    """Return an existing document for this patient if the same file was already uploaded."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM patient_documents WHERE patient_id = ? AND file_hash = ?",
            (patient_id, file_hash),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "filename": row["filename"],
        "doc_type": row["doc_type"],
        "upload_date": row["upload_date"],
        "indexed": bool(row["indexed"]),
        "summary": row["summary"] or "",
    }


def add_document(patient_id: str, filename: str, doc_type: str, file_hash: str = "") -> str:
    doc_id = uuid.uuid4().hex
    with _conn() as conn:
        conn.execute(
            """INSERT INTO patient_documents
               (id, patient_id, filename, doc_type, upload_date, indexed, summary, file_hash)
               VALUES (?,?,?,?,?,0,NULL,?)""",
            (doc_id, patient_id, filename, doc_type, date.today().isoformat(), file_hash or None),
        )
        conn.commit()
    return doc_id


def mark_document_indexed(doc_id: str, summary: str = "") -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE patient_documents SET indexed=1, summary=? WHERE id=?",
            (summary, doc_id),
        )
        conn.commit()


def set_document_path(doc_id: str, stored_path: str) -> None:
    """Record where the original uploaded PDF is persisted on disk."""
    with _conn() as conn:
        conn.execute(
            "UPDATE patient_documents SET stored_path=? WHERE id=?",
            (stored_path, doc_id),
        )
        conn.commit()


def get_document_by_id(doc_id: str) -> dict | None:
    """Return a single document row (used to serve the stored PDF)."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM patient_documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "filename": row["filename"],
        "doc_type": row["doc_type"],
        "upload_date": row["upload_date"],
        "indexed": bool(row["indexed"]),
        "summary": row["summary"] or "",
        "stored_path": row["stored_path"] or "",
    }


def add_lab_values(patient_id: str, doc_id: str, values: list[dict]) -> None:
    rows = [
        (
            uuid.uuid4().hex,
            patient_id,
            doc_id,
            v.get("test_name", ""),
            v.get("value", ""),
            v.get("unit", ""),
            v.get("reference_range", ""),
            v.get("status", ""),
            v.get("test_date", ""),
            0,
        )
        for v in values
    ]
    with _conn() as conn:
        conn.executemany(
            """INSERT OR IGNORE INTO lab_values
               (id, patient_id, document_id, test_name, value, unit,
                reference_range, status, test_date, confirmed)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        conn.commit()


def confirm_lab_values(doc_id: str, values: list[dict]) -> None:
    """Atomically replace lab values for a document with the doctor-confirmed list.

    All three operations (DELETE, patient_id lookup, INSERT) run in a single
    connection so there is no window where a crash could leave the table empty.
    Guard against empty values list to prevent silent erasure.
    """
    if not values:
        return
    with _conn() as conn:
        row = conn.execute(
            "SELECT patient_id FROM patient_documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if not row:
            return
        patient_id = row["patient_id"]
        conn.execute("DELETE FROM lab_values WHERE document_id = ?", (doc_id,))
        rows = [
            (
                uuid.uuid4().hex,
                patient_id,
                doc_id,
                v.get("test_name", ""),
                v.get("value", ""),
                v.get("unit", ""),
                v.get("reference_range", ""),
                v.get("status", ""),
                v.get("test_date", ""),
                1,
            )
            for v in values
        ]
        conn.executemany(
            """INSERT INTO lab_values
               (id, patient_id, document_id, test_name, value, unit,
                reference_range, status, test_date, confirmed)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        conn.commit()


def get_lab_values(
    patient_id: str,
    confirmed_only: bool = False,
    dedup_latest: bool = False,
) -> list[dict]:
    """Return lab values for a patient.

    dedup_latest: when True (used for analysis), return only one value per test
    name — the most recent by test_date, falling back to the document upload_date.
    This prevents double-counting when the same test appears in multiple reports.
    """
    if dedup_latest:
        # Join with patient_documents to use upload_date as a fallback sort key.
        query = """
            SELECT lv.*, pd.upload_date AS doc_upload_date
            FROM lab_values lv
            JOIN patient_documents pd ON pd.id = lv.document_id
            WHERE lv.patient_id = ? AND lv.confirmed = 1
            ORDER BY
                CASE WHEN lv.test_date != '' THEN lv.test_date ELSE pd.upload_date END DESC,
                lv.rowid DESC
        """
        with _conn() as conn:
            rows = conn.execute(query, (patient_id,)).fetchall()
        seen: set[str] = set()
        result = []
        for r in rows:
            key = r["test_name"].strip().lower()
            if key in seen:
                continue
            seen.add(key)
            result.append({
                "id": r["id"],
                "document_id": r["document_id"],
                "test_name": r["test_name"],
                "value": r["value"],
                "unit": r["unit"],
                "reference_range": r["reference_range"],
                "status": r["status"],
                "test_date": r["test_date"],
                "confirmed": True,
            })
        return result

    query = "SELECT * FROM lab_values WHERE patient_id = ?"
    if confirmed_only:
        query += " AND confirmed = 1"
    query += " ORDER BY test_date DESC"
    with _conn() as conn:
        rows = conn.execute(query, (patient_id,)).fetchall()
    return [
        {
            "id": r["id"],
            "document_id": r["document_id"],
            "test_name": r["test_name"],
            "value": r["value"],
            "unit": r["unit"],
            "reference_range": r["reference_range"],
            "status": r["status"],
            "test_date": r["test_date"],
            "confirmed": bool(r["confirmed"]),
        }
        for r in rows
    ]


def get_patient_documents(patient_id: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM patient_documents WHERE patient_id = ? ORDER BY upload_date DESC",
            (patient_id,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "filename": r["filename"],
            "doc_type": r["doc_type"],
            "upload_date": r["upload_date"],
            "indexed": bool(r["indexed"]),
            "summary": r["summary"] or "",
            "file_hash": r["file_hash"] or "",
            "has_file": bool(r["stored_path"]),
        }
        for r in rows
    ]


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_patient_stats(patient_id: str, days: int = 7) -> dict:
    # days_logged counts entries in the `days` window (recent activity); total_logged
    # is the patient's entire journaling history. The two differ a lot — the doctor
    # dashboard shows a 7-day window while the correlation engine looks back 60 days —
    # so both are returned to keep the views reconciled.
    with _conn() as conn:
        total_logged = conn.execute(
            "SELECT COUNT(*) AS c FROM journal_entries WHERE patient_id = ?",
            (patient_id,),
        ).fetchone()["c"]

    entries = get_entries(patient_id, days)
    if not entries:
        return {
            "days_logged": 0,
            "total_logged": total_logged,
            "adherence_by_med": {},
            "overall_adherence_pct": 0,
            "avg_stress": None,
            "top_symptoms": [],
            "last_entry_date": None,
            "streak": 0,
        }

    last_date = entries[0]["date"] if entries else None
    stress_vals = [e["stress_level"] for e in entries if e["stress_level"] is not None]
    avg_stress = round(sum(stress_vals) / len(stress_vals), 1) if stress_vals else None

    symptom_counts: dict[str, int] = defaultdict(int)
    for e in entries:
        for s in e["symptoms_today"]:
            symptom_counts[s] += 1
    top_symptoms = sorted(symptom_counts.items(), key=lambda x: -x[1])[:5]

    med_taken: dict[str, list[str]] = defaultdict(list)
    for e in entries:
        for med, status in e["medications_taken"].items():
            med_taken[med].append(status)

    adherence_by_med: dict[str, float] = {}
    for med, statuses in med_taken.items():
        taken = sum(1 for s in statuses if s == "taken")
        adherence_by_med[med] = round(100 * taken / len(statuses)) if statuses else 0

    overall = (
        round(sum(adherence_by_med.values()) / len(adherence_by_med))
        if adherence_by_med
        else 0
    )

    streak = _compute_streak(patient_id)

    return {
        "days_logged": len(entries),
        "total_logged": total_logged,
        "adherence_by_med": adherence_by_med,
        "overall_adherence_pct": overall,
        "avg_stress": avg_stress,
        "top_symptoms": [{"symptom": s, "count": c} for s, c in top_symptoms],
        "last_entry_date": last_date,
        "streak": streak,
    }


def get_symptom_frequencies(patient_id: str, days: int = 30) -> dict[str, float]:
    """Time-weighted symptom frequency scores using exponential decay.

    score(symptom) = sum(exp(-0.1 * days_ago)) for each logged occurrence.
    A symptom reported today weighs 1.0; one reported 10 days ago weighs ~0.37.
    Returns {symptom_name: weighted_score} sorted descending by score.
    """
    from math import exp
    entries = get_entries(patient_id, days)
    if not entries:
        return {}
    today = date.today()
    scores: dict[str, float] = defaultdict(float)
    for entry in entries:
        try:
            entry_date = date.fromisoformat(entry["date"])
        except ValueError:
            continue
        days_ago = (today - entry_date).days
        weight = exp(-0.1 * days_ago)
        for symptom in entry["symptoms_today"]:
            scores[symptom] += weight
    return dict(sorted(scores.items(), key=lambda x: -x[1]))


def update_patient(patient_id: str, updates: dict) -> bool:
    """Update editable patient fields. Returns True if a row was updated."""
    allowed = {"name", "doctor_notes", "symptoms_to_watch", "medications", "dietary_restrictions"}
    json_fields = {"symptoms_to_watch", "medications", "dietary_restrictions"}
    fields = {k: v for k, v in updates.items() if k in allowed}
    if not fields:
        return False
    set_parts = []
    values = []
    for k, v in fields.items():
        set_parts.append(f"{k} = ?")
        values.append(json.dumps(v) if k in json_fields else v)
    values.append(patient_id)
    with _conn() as conn:
        cursor = conn.execute(
            f"UPDATE patients SET {', '.join(set_parts)} WHERE id = ?",
            values,
        )
        conn.commit()
        return cursor.rowcount > 0


def delete_patient(patient_id: str) -> dict | None:
    """Permanently delete a patient and ALL their data (journal entries, documents,
    lab values). Returns a summary dict with counts and the stored PDF paths the
    caller should unlink from disk, or None if the patient does not exist.
    """
    with _conn() as conn:
        patient = conn.execute(
            "SELECT id FROM patients WHERE id = ?", (patient_id,)
        ).fetchone()
        if not patient:
            return None

        # Capture stored PDF paths before deleting the document rows so the caller
        # can remove the files from disk (PHI must not be left behind).
        stored_paths = [
            r["stored_path"]
            for r in conn.execute(
                "SELECT stored_path FROM patient_documents WHERE patient_id = ? AND stored_path IS NOT NULL",
                (patient_id,),
            ).fetchall()
        ]
        n_entries = conn.execute(
            "SELECT COUNT(*) AS c FROM journal_entries WHERE patient_id = ?", (patient_id,)
        ).fetchone()["c"]
        n_docs = conn.execute(
            "SELECT COUNT(*) AS c FROM patient_documents WHERE patient_id = ?", (patient_id,)
        ).fetchone()["c"]
        n_labs = conn.execute(
            "SELECT COUNT(*) AS c FROM lab_values WHERE patient_id = ?", (patient_id,)
        ).fetchone()["c"]

        # Delete children first (no ON DELETE CASCADE in the schema), then the patient.
        conn.execute("DELETE FROM lab_values WHERE patient_id = ?", (patient_id,))
        conn.execute("DELETE FROM journal_entries WHERE patient_id = ?", (patient_id,))
        conn.execute("DELETE FROM patient_documents WHERE patient_id = ?", (patient_id,))
        conn.execute("DELETE FROM patients WHERE id = ?", (patient_id,))
        conn.commit()

    return {
        "entries_deleted": n_entries,
        "documents_deleted": n_docs,
        "lab_values_deleted": n_labs,
        "stored_paths": stored_paths,
    }


def _compute_streak(patient_id: str) -> int:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT date FROM journal_entries WHERE patient_id = ? ORDER BY date DESC",
            (patient_id,),
        ).fetchall()
    if not rows:
        return 0
    dates = {r["date"] for r in rows}
    today = date.today()
    # Start from today if already logged, otherwise start from yesterday
    cursor = today if today.isoformat() in dates else today - timedelta(days=1)
    streak = 0
    while cursor.isoformat() in dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak
