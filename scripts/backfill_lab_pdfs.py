"""Backfill openable lab-report PDFs for already-seeded demo patients.

The seed scripts skip patients that already have labs, so editing those scripts
does not repair an existing DB. This backfill does two things, idempotently:

  1. Removes obviously-broken leftover junk doc rows: any patient_documents row
     whose filename matches "tmp%" AND that has 0 associated lab_values. This is
     conservative on purpose, it only touches tmp-named rows with no lab values.

  2. For every lab_results document with stored_path IS NULL and at least one
     confirmed lab value, generates a matching PDF to uploads/{doc_id}.pdf and
     sets stored_path. Skips (with a warning) lab_results docs that have 0 lab
     values rather than crashing.

Safe to re-run: a doc whose PDF already exists on disk and whose stored_path is
already set is skipped.

Run:  venv/Scripts/python.exe scripts/backfill_lab_pdfs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data"))
sys.path.insert(0, str(ROOT / "scripts"))

from journal import _conn, set_document_path  # noqa: E402
from lab_pdf import title_from_filename, write_lab_report_pdf  # noqa: E402


def _delete_junk_tmp_docs() -> None:
    """Remove tmp-named document rows that carry zero lab values."""
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT d.id, d.filename, d.doc_type
            FROM patient_documents d
            WHERE d.filename LIKE 'tmp%'
              AND (SELECT COUNT(*) FROM lab_values lv WHERE lv.document_id = d.id) = 0
            """
        ).fetchall()
        if not rows:
            print("No junk tmp documents to remove.")
            return
        for r in rows:
            conn.execute("DELETE FROM patient_documents WHERE id = ?", (r["id"],))
            print(f"Removed junk doc: {r['filename']} (doc_type={r['doc_type']}, id={r['id']})")
        conn.commit()


def _lab_status_rank(status: str) -> int:
    """Order flagged results first (HIGH/LOW), then NORMAL, for a sensible table."""
    s = (status or "").upper()
    if s in ("HIGH", "LOW"):
        return 0
    return 1


def _backfill_doc(doc) -> tuple[bool, str]:
    """Generate a PDF for one lab_results document. Returns (done, message)."""
    doc_id = doc["id"]
    patient_id = doc["patient_id"]
    filename = doc["filename"] or "Laboratory_Report.pdf"
    summary = doc["summary"] or None
    lab_date = doc["upload_date"] or ""

    pdf_path = ROOT / "uploads" / f"{doc_id}.pdf"

    # Idempotency: file already there and path set.
    if pdf_path.exists() and doc["stored_path"]:
        return False, f"skip (already present): {filename}"

    with _conn() as conn:
        patient = conn.execute(
            "SELECT name, condition FROM patients WHERE id = ?", (patient_id,)
        ).fetchone()
        labs = conn.execute(
            """SELECT test_name, value, unit, reference_range, status, test_date
               FROM lab_values
               WHERE document_id = ? AND confirmed = 1""",
            (doc_id,),
        ).fetchall()

    if not labs:
        return False, f"WARN: 0 confirmed lab values, skipped: {filename}"

    panel = [dict(lv) for lv in labs]
    panel.sort(key=lambda lv: _lab_status_rank(lv.get("status", "")))

    patient_name = (patient["name"] if patient and patient["name"] else "Patient")
    condition = (patient["condition"] if patient and patient["condition"] else "")

    write_lab_report_pdf(
        pdf_path,
        patient_name=patient_name,
        condition=condition,
        report_title=title_from_filename(filename),
        panel=panel,
        lab_date=lab_date,
        summary=summary,
    )
    set_document_path(doc_id, str(pdf_path))
    return True, f"OK: {patient_name} | {filename} | {len(panel)} labs | {pdf_path}"


def main() -> None:
    print("=" * 60)
    print("  Backfilling demo lab-report PDFs")
    print("=" * 60)

    print("\n[1] Removing junk tmp document rows")
    _delete_junk_tmp_docs()

    print("\n[2] Generating PDFs for lab_results docs with no stored file")
    with _conn() as conn:
        docs = conn.execute(
            """SELECT * FROM patient_documents
               WHERE doc_type = 'lab_results' AND stored_path IS NULL
               ORDER BY upload_date DESC"""
        ).fetchall()

    fixed = 0
    skipped = 0
    warned = 0
    for doc in docs:
        done, msg = _backfill_doc(doc)
        print("   " + msg)
        if done:
            fixed += 1
        elif msg.startswith("WARN"):
            warned += 1
        else:
            skipped += 1

    print("\n" + "=" * 60)
    print(f"  Done. fixed={fixed}  skipped={skipped}  warned={warned}")
    print("=" * 60)


if __name__ == "__main__":
    main()
