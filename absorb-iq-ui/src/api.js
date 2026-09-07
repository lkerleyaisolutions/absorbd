// API helpers. In dev, Vite proxies /api -> FastAPI backend.
const BASE = "/api";

// ── Response helper ──────────────────────────────────────────────────────────

// The backend signals failures with real HTTP status codes and a FastAPI
// {"detail": "..."} body. Surface that detail as the Error message (with
// err.status set) so UI catch blocks can show meaningful text.
async function _json(r, label) {
  if (!r.ok) {
    let detail = "";
    try {
      detail = (await r.json()).detail || "";
    } catch { /* non-JSON error body */ }
    const err = new Error(detail || `${label} ${r.status}`);
    err.status = r.status;
    throw err;
  }
  return r.json();
}

// ── SSE helper (shared) ──────────────────────────────────────────────────────

function _dispatchChunk(chunk, onEvent) {
  // An SSE event may carry multiple `data:` lines; per spec they are joined with "\n".
  const dataLines = chunk
    .split("\n")
    .filter((l) => l.startsWith("data:"))
    .map((l) => l.slice(5).replace(/^ /, ""));
  if (!dataLines.length) return;
  const payload = dataLines.join("\n").trim();
  if (!payload) return;
  try {
    onEvent(JSON.parse(payload));
  } catch (err) {
    // Don't silently swallow: a malformed event is a real signal worth seeing.
    console.warn("SSE: failed to parse event payload", payload, err);
  }
}

async function _readSSE(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      _dispatchChunk(chunk, onEvent);
    }
  }
  // Flush any trailing event that arrived without a final blank-line separator.
  buffer += decoder.decode();
  if (buffer.trim()) _dispatchChunk(buffer, onEvent);
}

// ── Analysis stream ──────────────────────────────────────────────────────────

export async function analyzeStream(profile, onEvent, signal) {
  const r = await fetch(`${BASE}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile),
    signal,
  });
  if (!r.ok || !r.body) throw new Error(`analyze ${r.status}`);
  return _readSSE(r, onEvent);
}

// ── Doctor API ───────────────────────────────────────────────────────────────

export async function doctorCreate(name, practice) {
  const r = await fetch(`${BASE}/doctor/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, practice }),
  });
  return _json(r, "doctor/create");
}

export async function doctorLogin(access_code) {
  const r = await fetch(`${BASE}/doctor/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ access_code }),
  });
  return _json(r, "doctor/login");
}

export async function doctorCreatePatient(body) {
  const r = await fetch(`${BASE}/doctor/create-patient`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return _json(r, "doctor/create-patient");
}

export async function doctorPatients(doctor_id) {
  const r = await fetch(`${BASE}/doctor/patients?doctor_id=${encodeURIComponent(doctor_id)}`);
  return _json(r, "doctor/patients");
}

// doctor_id is required: the backend verifies ownership before this
// destructive, unrecoverable delete.
export async function doctorDeletePatient(patient_id, doctor_id) {
  const r = await fetch(
    `${BASE}/doctor/patient/${encodeURIComponent(patient_id)}?doctor_id=${encodeURIComponent(doctor_id)}`,
    { method: "DELETE" }
  );
  return _json(r, "doctor/patient delete");
}

// ── Patient API ──────────────────────────────────────────────────────────────

export async function patientAccess(access_code) {
  const r = await fetch(`${BASE}/patient/access`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ access_code }),
  });
  return _json(r, "patient/access");
}

export async function patientUploadDocument(patient_id, doc_type, file) {
  const form = new FormData();
  form.append("patient_id", patient_id);
  form.append("doc_type", doc_type);
  form.append("file", file);
  const r = await fetch(`${BASE}/patient/upload-document`, { method: "POST", body: form });
  return _json(r, "patient/upload-document");
}

// URL the browser can open to view/download the original uploaded PDF.
export function documentUrl(document_id) {
  return `${BASE}/patient/document/${encodeURIComponent(document_id)}`;
}

export async function patientConfirmLabValues(document_id, lab_values) {
  const r = await fetch(`${BASE}/patient/confirm-lab-values`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_id, lab_values }),
  });
  return _json(r, "patient/confirm-lab-values");
}

export async function patientLabValues(patient_id, confirmed_only = false) {
  const r = await fetch(
    `${BASE}/patient/lab-values?patient_id=${encodeURIComponent(patient_id)}&confirmed_only=${confirmed_only}`
  );
  return _json(r, "patient/lab-values");
}

export async function patientDocuments(patient_id) {
  const r = await fetch(
    `${BASE}/patient/documents?patient_id=${encodeURIComponent(patient_id)}`
  );
  return _json(r, "patient/documents");
}

export async function patientUpdate(patient_id, updates) {
  const r = await fetch(`${BASE}/patient/${encodeURIComponent(patient_id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  return _json(r, "patient/update");
}

export async function patientStats(patient_id, days = 7) {
  const r = await fetch(
    `${BASE}/patient/stats?patient_id=${encodeURIComponent(patient_id)}&days=${days}`
  );
  return _json(r, "patient/stats");
}

// ── Journal API ──────────────────────────────────────────────────────────────

export async function journalStart(patient_id) {
  const r = await fetch(`${BASE}/journal/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ patient_id }),
  });
  return _json(r, "journal/start");
}

export async function journalMessage(session_id, text, selected) {
  const r = await fetch(`${BASE}/journal/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id, text, selected }),
  });
  return _json(r, "journal/message");
}

export async function journalEntryDirect(body) {
  const r = await fetch(`${BASE}/journal/entry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return _json(r, "journal/entry");
}

export async function journalEntries(patient_id, days = 30) {
  const r = await fetch(
    `${BASE}/journal/entries?patient_id=${encodeURIComponent(patient_id)}&days=${days}`
  );
  return _json(r, "journal/entries");
}

export async function journalYesterday(patient_id) {
  const r = await fetch(
    `${BASE}/journal/yesterday?patient_id=${encodeURIComponent(patient_id)}`
  );
  return _json(r, "journal/yesterday");
}

// Curated, patient-safe nudges (no numbers) derived from the correlation engine.
export async function getPatientNudges(patient_id) {
  const r = await fetch(`${BASE}/patient/nudges?patient_id=${encodeURIComponent(patient_id)}`);
  return _json(r, "patient/nudges");
}

export async function doctorCorrelations(patient_id, days = 60, ground = false) {
  const r = await fetch(
    `${BASE}/doctor/correlations?patient_id=${encodeURIComponent(patient_id)}&days=${days}&ground=${ground ? "true" : "false"}`
  );
  return _json(r, "doctor/correlations");
}

export async function doctorSummaryStream(patient_id, onEvent, signal) {
  const r = await fetch(`${BASE}/journal/doctor-summary`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ patient_id }),
    signal,
  });
  if (!r.ok || !r.body) throw new Error(`journal/doctor-summary ${r.status}`);
  return _readSSE(r, onEvent);
}
