r"""Absorbd FastAPI backend.

Exposes the orchestrated 9-agent pipeline as a Server-Sent Events (SSE) stream so a
browser can watch each agent reason in real time, then receive the final protocol
and doctor questions.

Run:  venv\Scripts\python.exe -m uvicorn main:app --reload
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
# Persisted patient-uploaded PDFs (PHI — gitignored). One file per document id.
UPLOADS_DIR = ROOT / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB cap on uploaded lab PDFs
sys.path.insert(0, str(ROOT / "agents"))
sys.path.insert(0, str(ROOT / "data" / "intake"))
sys.path.insert(0, str(ROOT / "data"))

from orchestrator import run_pipeline  # noqa: E402
from _base import close_clients  # noqa: E402
from journal import (  # noqa: E402
    init_db,
    create_doctor,
    get_doctor_by_code,
    get_doctor_by_id,
    create_patient,
    get_patient_by_code,
    get_patient_by_id,
    get_doctor_patients,
    add_entry,
    get_entries,
    has_entry_today,
    get_yesterday_entry,
    add_document,
    confirm_lab_values,
    get_lab_values,
    get_patient_documents,
    get_document_by_hash,
    get_document_by_id,
    set_document_path,
    get_patient_stats,
    update_patient,
    delete_patient,
)
from journal_agent import start_journal_session, handle_journal_message  # noqa: E402
from doctor_summary import run_doctor_summary  # noqa: E402
from document_ingestion import ingest_document  # noqa: E402
from correlations import compute_lag_correlations  # noqa: E402
from correlation_grounding import ground_findings  # noqa: E402

# FIX #10: curated_patient_nudges is being added to data/correlations.py by another
# agent in parallel. Import it defensively so a not-yet-present helper degrades to an
# empty nudge list rather than crashing the server import.
try:
    from correlations import curated_patient_nudges  # noqa: E402
except ImportError:
    curated_patient_nudges = None

app = FastAPI(title="Absorbd", version="0.2.0")

# Dev CORS: the React dev server runs on a different port.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── SSE helper ───────────────────────────────────────────────────────────────

def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# ── Analyze (9-agent pipeline) ───────────────────────────────────────────────

class Profile(BaseModel):
    condition: str = "IBD"
    medications: list = []
    symptoms: list[str] = []
    dietary_restrictions: list[str] = []
    patient_id: str = ""


@app.post("/analyze")
async def analyze(profile: Profile) -> StreamingResponse:
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    raw = profile.model_dump()

    # If patient_id is provided, attach confirmed lab values so agents can use them.
    # dedup_latest=True keeps only the most recent result per test name so multiple
    # lab reports for the same patient don't cause double-counting in the analysis.
    if profile.patient_id:
        labs = get_lab_values(profile.patient_id, confirmed_only=True, dedup_latest=True)
        raw["lab_values"] = labs
        # FIX #3: red-flag screening must use what the patient ACTUALLY reported, not
        # the doctor's watch-list. Pull the most recent journal entry's symptoms_today
        # as reported_symptoms. profile.symptoms is left as-is for deficiency reasoning.
        entries = get_entries(profile.patient_id, days=30)
        raw["reported_symptoms"] = entries[0].get("symptoms_today", []) if entries else []

    def emit(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async def run() -> None:
        try:
            await run_pipeline(raw, emit)
        except Exception as exc:
            emit({"type": "error", "detail": str(exc)})
        finally:
            emit({"type": "__end__"})

    async def stream():
        task = asyncio.create_task(run())
        try:
            while True:
                event = await queue.get()
                if event.get("type") == "__end__":
                    break
                yield _sse(event)
        finally:
            # On client disconnect, cancel the producer AND await it so teardown
            # completes (and any cancellation error is swallowed) instead of
            # leaving an orphaned task.
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ── Doctor endpoints ─────────────────────────────────────────────────────────

class DoctorCreate(BaseModel):
    name: str
    practice: str = ""


class DoctorLogin(BaseModel):
    access_code: str


class CreatePatient(BaseModel):
    doctor_id: str
    condition: str
    name: str = ""
    medications: list = []
    symptoms_to_watch: list[str] = []
    dietary_restrictions: list[str] = []
    doctor_notes: str = ""


@app.post("/doctor/create")
def doctor_create(body: DoctorCreate) -> dict:
    return create_doctor(body.name, body.practice)


@app.post("/doctor/login")
def doctor_login(body: DoctorLogin) -> dict:
    doctor = get_doctor_by_code(body.access_code)
    if not doctor:
        raise HTTPException(status_code=401, detail="invalid access code")
    patients = get_doctor_patients(doctor["id"])
    return {**doctor, "patients": patients}


@app.post("/doctor/create-patient")
def doctor_create_patient(body: CreatePatient) -> dict:
    doctor = get_doctor_by_id(body.doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="unknown doctor")
    result = create_patient(
        doctor_id=body.doctor_id,
        condition=body.condition,
        name=body.name,
        medications=body.medications,
        symptoms_to_watch=body.symptoms_to_watch,
        dietary_restrictions=body.dietary_restrictions,
        doctor_notes=body.doctor_notes,
    )
    return result


@app.get("/doctor/patients")
def doctor_patients(doctor_id: str) -> dict:
    doctor = get_doctor_by_id(doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail="unknown doctor")
    patients = get_doctor_patients(doctor_id)
    return {"patients": patients}


@app.get("/doctor/correlations")
def doctor_correlations(patient_id: str, days: int = 60, ground: bool = False) -> dict:
    """Doctor-only: statistical lag-correlations from journal history.

    ground=True additionally checks each finding against the Foundry IQ literature
    base (one grounded LLM verification per finding) and attaches proof when the
    relationship is documented. It is opt-in because it adds model-call latency.
    """
    patient = get_patient_by_id(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="unknown patient")
    findings = compute_lag_correlations(patient_id, days=days)
    if ground and findings:
        ground_findings(findings, patient.get("condition", "IBD"))
    return {
        "patient_id": patient_id,
        "days_analyzed": days,
        "grounded": bool(ground),
        "findings": [
            {
                "factor": f.factor,
                "symptom": f.symptom,
                "lag_days": f.lag_days,
                "lag_label": f.lag_label,
                "correlation": round(f.correlation, 3),
                "p_adjusted": round(f.p_adjusted, 4),
                "p_raw": round(f.p_raw, 4),
                "n": f.n,
                "strength": f.strength,
                "direction": f.direction,
                "confidence": f.confidence,
                "tier": f.tier,
                # FIX #2/#5: surface the direction gate + flare-adjusted correlation
                # so the doctor UI can badge unexpected-direction and confounded rows.
                "direction_flag": getattr(f, "direction_flag", "expected"),
                "r_adjusted": (
                    round(f.r_adjusted, 3)
                    if getattr(f, "r_adjusted", None) is not None
                    else None
                ),
                "confound_flag": getattr(f, "confound_flag", False),
                "literature": f.literature,
            }
            for f in findings
        ],
    }


# ── Patient endpoints ────────────────────────────────────────────────────────

class PatientAccess(BaseModel):
    access_code: str


class ConfirmLabValues(BaseModel):
    document_id: str
    lab_values: list[dict] = []


@app.post("/patient/access")
def patient_access(body: PatientAccess) -> dict:
    patient = get_patient_by_code(body.access_code)
    if not patient:
        raise HTTPException(status_code=401, detail="invalid access code")
    # Include confirmed lab values + document list for rich patient context
    patient["lab_values"] = get_lab_values(patient["id"], confirmed_only=True)
    patient["documents"] = get_patient_documents(patient["id"])
    # Surface the patient's own doctor so the home screen can name them
    doctor = get_doctor_by_id(patient.get("doctor_id"))
    patient["doctor_name"] = doctor["name"] if doctor else ""
    return patient


@app.post("/patient/upload-document")
async def patient_upload_document(
    patient_id: str = Form(...),
    doc_type: str = Form("lab_results"),
    file: UploadFile = File(...),
) -> dict:
    patient = get_patient_by_id(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="unknown patient")

    # Read file bytes, compute SHA-256 for duplicate detection
    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (max 10 MB)")
    # Only PDFs are supported end-to-end (ingestion parses PDF, viewer serves
    # application/pdf). Check the magic bytes, not just the filename.
    if not file_bytes.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="only PDF uploads are supported")
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    existing = get_document_by_hash(patient_id, file_hash)
    if existing:
        return {
            "duplicate": True,
            "document_id": existing["id"],
            "filename": existing["filename"],
            "upload_date": existing["upload_date"],
            "lab_values_extracted": [],
            "chunks_indexed": 0,
            "has_file": True,
        }

    # Write to temp file for ingestion pipeline. Uploads are validated PDFs, so
    # the stored/temp suffix is fixed rather than trusting the client filename.
    suffix = ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        result = ingest_document(patient_id, tmp_path, doc_type, file_hash=file_hash)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    # Persist the original PDF so the doctor can open it later. Keyed by document
    # id so the filename can be anything without collisions.
    doc_id = result.get("document_id")
    if doc_id:
        stored = UPLOADS_DIR / f"{doc_id}{suffix}"
        stored.write_bytes(file_bytes)
        set_document_path(doc_id, str(stored))
        result["has_file"] = True

    return result


@app.get("/patient/document/{document_id}")
def patient_document_file(document_id: str):
    """Serve the original uploaded PDF inline, under its real filename."""
    doc = get_document_by_id(document_id)
    if not doc or not doc.get("stored_path"):
        raise HTTPException(status_code=404, detail="document not found")
    path = Path(doc["stored_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="file missing")
    return FileResponse(
        str(path),
        media_type="application/pdf",
        filename=doc["filename"] or path.name,
        content_disposition_type="inline",
    )


@app.post("/patient/confirm-lab-values")
def patient_confirm_lab_values(body: ConfirmLabValues) -> dict:
    confirm_lab_values(body.document_id, body.lab_values)
    return {"ok": True, "confirmed": len(body.lab_values)}


@app.get("/patient/lab-values")
def patient_lab_values(patient_id: str, confirmed_only: bool = False) -> dict:
    patient = get_patient_by_id(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="unknown patient")
    return {"lab_values": get_lab_values(patient_id, confirmed_only=confirmed_only)}


@app.get("/patient/documents")
def patient_documents(patient_id: str) -> dict:
    patient = get_patient_by_id(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="unknown patient")
    return {"documents": get_patient_documents(patient_id)}


@app.get("/patient/stats")
def patient_stats(patient_id: str, days: int = 7) -> dict:
    patient = get_patient_by_id(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="unknown patient")
    return get_patient_stats(patient_id, days)


@app.get("/patient/nudges")
def patient_nudges(patient_id: str) -> dict:
    """FIX #10: plain-language nudges derived from this patient's lag-correlations.

    Computes the patient's correlations, then passes them through the correlation
    agent's curated_patient_nudges helper. If that helper is not available yet
    (added in parallel) or anything fails, degrades to an empty list rather than
    erroring, so the patient view never breaks.
    """
    patient = get_patient_by_id(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="unknown patient")
    if curated_patient_nudges is None:
        return {"nudges": []}
    try:
        findings = compute_lag_correlations(patient_id)
        nudges = curated_patient_nudges(findings)
    except Exception as exc:  # noqa: BLE001 — a nudge failure must not break the view
        print(f"[patient/nudges] failed for {patient_id}: {exc}")
        return {"nudges": []}
    return {"nudges": nudges or []}


class UpdatePatient(BaseModel):
    name: str | None = None
    doctor_notes: str | None = None
    symptoms_to_watch: list[str] | None = None
    medications: list | None = None
    dietary_restrictions: list[str] | None = None


@app.patch("/patient/{patient_id}")
def patient_update(patient_id: str, body: UpdatePatient) -> dict:
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    success = update_patient(patient_id, updates)
    if not success:
        raise HTTPException(status_code=404, detail="unknown patient or no changes")
    updated = get_patient_by_id(patient_id)
    return updated


def _purge_patient_vectors(patient_id: str) -> int:
    """Best-effort removal of this patient's chunks from the Azure Search index.
    Non-fatal: the index has a hard patient_id filter, so any residual chunks can
    never surface for another patient even if this step fails. Returns count deleted.
    """
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from _common import search_client  # noqa: E402

        sc = search_client()
        # Escape single quotes for the OData filter.
        safe = patient_id.replace("'", "''")
        hits = sc.search(
            search_text="*",
            filter=f"patient_id eq '{safe}'",
            select=["id"],
            top=1000,
        )
        ids = [{"id": h["id"]} for h in hits]
        if not ids:
            return 0
        sc.delete_documents(documents=ids)
        return len(ids)
    except Exception as exc:  # noqa: BLE001 — cleanup must never block the delete
        print(f"[delete_patient] vector purge skipped for {patient_id}: {exc}")
        return 0


@app.delete("/doctor/patient/{patient_id}")
def doctor_delete_patient(patient_id: str, doctor_id: str) -> dict:
    """Permanently delete a patient and all associated data: journal entries,
    uploaded documents (DB rows + stored PDFs), lab values, and indexed vectors.

    Requires the owning doctor_id: deletion is destructive, so knowing a
    patient_id alone must not be enough to wipe a patient's records.
    """
    patient = get_patient_by_id(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="unknown patient")
    if patient.get("doctor_id") != doctor_id:
        raise HTTPException(status_code=403, detail="patient does not belong to this doctor")
    result = delete_patient(patient_id)
    if result is None:
        raise HTTPException(status_code=404, detail="unknown patient")

    # Remove the stored PDF files from disk (PHI must not be left behind).
    files_deleted = 0
    for path in result.get("stored_paths", []):
        with contextlib.suppress(Exception):
            p = Path(path)
            if p.exists():
                p.unlink()
                files_deleted += 1

    vectors_deleted = _purge_patient_vectors(patient_id)

    return {
        "ok": True,
        "entries_deleted": result["entries_deleted"],
        "documents_deleted": result["documents_deleted"],
        "lab_values_deleted": result["lab_values_deleted"],
        "files_deleted": files_deleted,
        "vectors_deleted": vectors_deleted,
    }


# ── Journal endpoints ────────────────────────────────────────────────────────

class JournalStart(BaseModel):
    patient_id: str


class JournalMessage(BaseModel):
    session_id: str
    text: str = ""
    selected: list[str] = []


class JournalEntry(BaseModel):
    patient_id: str
    symptoms_today: list[str] = []
    medications_taken: dict[str, str] = {}
    stress_level: int = 5
    notes: str = ""
    entry_date: str = ""
    extra: dict = {}


class DoctorSummaryBody(BaseModel):
    patient_id: str


# /journal/start and /journal/message are the DEPRECATED conversational journal
# chat. The current UI logs entries in one shot via /journal/entry below. These
# two are kept for backward compatibility / standalone testing only.
@app.post("/journal/start")
def journal_start(body: JournalStart) -> dict:
    return start_journal_session(body.patient_id)


@app.post("/journal/message")
def journal_message(body: JournalMessage) -> dict:
    return handle_journal_message(body.session_id, body.text, body.selected)


@app.post("/journal/entry")
def journal_entry(body: JournalEntry) -> dict:
    """Direct single-call journal entry (replaces 4-turn chat flow)."""
    patient = get_patient_by_id(body.patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="unknown patient")
    entry_id = add_entry(
        patient_id=body.patient_id,
        symptoms_today=body.symptoms_today,
        medications_taken=body.medications_taken,
        stress_level=body.stress_level,
        notes=body.notes,
        entry_date=body.entry_date or None,
        extra=body.extra or {},
    )
    return {"entry_id": entry_id, "ok": True}


@app.get("/journal/entries")
def journal_entries(patient_id: str, days: int = 30) -> dict:
    patient = get_patient_by_id(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="unknown patient")
    return {
        "entries": get_entries(patient_id, days),
        "patient": patient,
        "stats": get_patient_stats(patient_id, days=7),
    }


@app.get("/journal/yesterday")
def journal_yesterday(patient_id: str) -> dict:
    patient = get_patient_by_id(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="unknown patient")
    entry = get_yesterday_entry(patient_id)
    return {"entry": entry}


@app.post("/journal/doctor-summary")
async def journal_doctor_summary(body: DoctorSummaryBody) -> StreamingResponse:
    patient = get_patient_by_id(body.patient_id)
    if not patient:
        async def _err():
            yield _sse({"type": "error", "detail": "unknown patient"})
        return StreamingResponse(_err(), media_type="text/event-stream")

    entries = get_entries(body.patient_id, days=30)
    # Attach deduplicated confirmed lab values so doctor_summary references current numbers
    patient["lab_values"] = get_lab_values(body.patient_id, confirmed_only=True, dedup_latest=True)

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def emit(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    async def run() -> None:
        try:
            result = await asyncio.to_thread(run_doctor_summary, patient, entries, emit)
            emit({"type": "result", "stage": "doctor_summary", "data": result})
        except Exception as exc:
            emit({"type": "error", "detail": str(exc)})
        finally:
            emit({"type": "__end__"})

    async def stream():
        task = asyncio.create_task(run())
        try:
            while True:
                event = await queue.get()
                if event.get("type") == "__end__":
                    break
                yield _sse(event)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ── Lifecycle ────────────────────────────────────────────────────────────────

@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.on_event("shutdown")
def _shutdown() -> None:
    close_clients()
