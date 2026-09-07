import sys
sys.path.insert(0, 'agents')
sys.path.insert(0, 'data/intake')
sys.path.insert(0, 'data')

print("Testing imports...")
from journal import (init_db, create_doctor, create_patient, get_doctor_by_code,
                     get_patient_by_id, add_entry, get_entries, get_patient_stats)
print("  journal.py OK")

from journal_agent import start_journal_session, handle_journal_message
print("  journal_agent.py OK")

from doctor_summary import run_doctor_summary
print("  doctor_summary.py OK")

from document_ingestion import ingest_document
print("  document_ingestion.py OK")

from orchestrator import run_pipeline, prepare_profile
print("  orchestrator.py OK")

print()
print("Testing DB init + doctor/patient creation...")
init_db()
print("  init_db OK")

doc = create_doctor("Dr. Test", "IBD Clinic")
code = doc["access_code"]
print("  Doctor created: code=" + code)

doc_fetched = get_doctor_by_code(code)
print("  Doctor login OK: id=" + doc_fetched["id"][:8] + "...")

pat = create_patient(
    doctor_id=doc_fetched["id"],
    condition="ulcerative colitis",
    medications=[{"name": "Mesalamine", "brand": "Lialda", "dose": "2.4g", "frequency": "daily"}],
    symptoms_to_watch=["Abdominal pain", "Fatigue", "Diarrhea", "Bloating"],
    dietary_restrictions=["low-fiber"],
    doctor_notes="Watch for bloody stools.",
)
pat_code = pat["access_code"]
print("  Patient created: code=" + pat_code)

pat_fetched = get_patient_by_id(pat["id"])
print("  Patient lookup OK: condition=" + pat_fetched["condition"])

entry_id = add_entry(
    patient_id=pat["id"],
    symptoms_today=["Fatigue", "Bloating"],
    medications_taken={"Mesalamine": "taken"},
    stress_level=6,
    notes="Tired all day, slight bloating.",
)
print("  Entry saved: " + entry_id)

entries = get_entries(pat["id"], days=7)
print("  get_entries OK: " + str(len(entries)) + " entry/entries")

stats = get_patient_stats(pat["id"], days=7)
print("  Stats OK: adherence=" + str(stats["overall_adherence_pct"]) + "%, streak=" + str(stats["streak"]))

print()
print("Testing journal agent session...")
sess = start_journal_session(pat["id"])
print("  start_journal_session OK: session_id=" + sess.get("session_id", "ERR"))
print("  First prompt: " + str(sess.get("agent", ["?"])[0])[:60])

print()
print("All systems OK.")
