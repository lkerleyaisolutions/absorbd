import { Fragment, useEffect, useRef, useState } from "react";
import {
  analyzeStream,
  doctorCreate, doctorLogin, doctorCreatePatient, doctorPatients, doctorDeletePatient,
  patientAccess, patientUploadDocument, patientConfirmLabValues, patientLabValues, patientDocuments, patientUpdate,
  documentUrl,
  journalStart, journalMessage, journalEntryDirect, journalEntries,
  doctorSummaryStream, doctorCorrelations, getPatientNudges,
} from "./api.js";

const CONDITIONS = [
  { id: "ulcerative colitis", label: "Ulcerative Colitis" },
  { id: "Crohn's disease", label: "Crohn's Disease" },
  { id: "celiac disease", label: "Celiac Disease" },
];

const SYMPTOM_CHECKLIST = [
  "Abdominal pain", "Bloating", "Cramping", "Diarrhea", "Bloody stools",
  "Constipation", "Fatigue", "Joint pain", "Skin rash", "Eye inflammation",
  "Nausea", "Vomiting", "Loss of appetite", "Unintended weight loss",
  "Night sweats", "Fever",
];

const AGENT_LABEL = {
  DeficiencyHypothesis: "Deficiency",
  MedicationInteraction: "Medication",
  DietaryGap: "Dietary",
  Synthesis: "Synthesis",
  Protocol: "Protocol",
  Safety: "Safety",
  DoctorGuide: "Doctor Guide",
  DoctorSummary: "Summary",
};

// Persisted AI-summary cache. Both the patient brief and the doctor analysis are
// expensive multi-LLM runs, so we keep the last result until the user reruns it,
// surviving navigation and full page reloads alike.
function loadCache(key) {
  try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : null; } catch { return null; }
}
function saveCache(key, val) {
  try {
    if (val == null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(val));
  } catch { /* quota or private-mode: in-memory cache still works this session */ }
}

const PATIENT_SUMMARY_CACHE_KEY = "absorb_patient_summary";
const ANALYSIS_CACHE_KEY = "absorb_analysis_cache";

// ── App ──────────────────────────────────────────────────────────────────────

export default function App() {
  // phases: loading | landing | doctor-login | doctor-register | doctor-dash | doctor-create-patient
  //         | doctor-patient-view | patient-entry | home | journal | summary | analysis
  const [phase, setPhase] = useState("loading");
  const [doctor, setDoctor] = useState(null);
  const [patient, setPatient] = useState(null);
  const [selectedPatient, setSelectedPatient] = useState(null);
  const [analysisProfile, setAnalysisProfile] = useState(null);
  // Cached doctor-visit summary so navigating away and back (or reloading) doesn't
  // re-run the expensive multi-LLM pipeline. Shape: { patientId, data }.
  const [patientSummary, setPatientSummary] = useState(() => loadCache(PATIENT_SUMMARY_CACHE_KEY));
  // Cached doctor-facing analysis, keyed by patient_id. Shape:
  // { patientId, trace, result, escalation }.
  const [analysisCache, setAnalysisCache] = useState(() => loadCache(ANALYSIS_CACHE_KEY));

  const cachePatientSummary = (val) => { setPatientSummary(val); saveCache(PATIENT_SUMMARY_CACHE_KEY, val); };
  const cacheAnalysis = (val) => { setAnalysisCache(val); saveCache(ANALYSIS_CACHE_KEY, val); };

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("demo") === "home") {
      setPatient({
        id: "demo-patient",
        name: params.get("name") || "Alex",
        condition: "ulcerative colitis",
        doctor_name: params.get("doctor") || "Dr. Chen",
        medications: [],
      });
      setPhase("home");
      return;
    }

    const doctorId = localStorage.getItem("absorb_doctor_id");
    const patientId = localStorage.getItem("absorb_patient_id");
    const patientCode = localStorage.getItem("absorb_patient_code");

    // On any auto-login failure, clear the stale keys so we don't silently
    // re-fail on every reload (which looks like a random logout to the user).
    const clearDoctor = () => {
      localStorage.removeItem("absorb_doctor_id");
      localStorage.removeItem("absorb_doctor_code");
    };
    const clearPatient = () => {
      localStorage.removeItem("absorb_patient_id");
      localStorage.removeItem("absorb_patient_code");
    };

    if (doctorId) {
      const doctorCode = localStorage.getItem("absorb_doctor_code");
      doctorLogin(doctorCode || "")
        .then((d) => {
          if (d.error) { clearDoctor(); setPhase("landing"); return; }
          setDoctor(d);
          setPhase("doctor-dash");
        })
        .catch(() => { clearDoctor(); setPhase("landing"); });
    } else if (patientId && patientCode) {
      patientAccess(patientCode)
        .then((p) => {
          if (p.error) { clearPatient(); setPhase("landing"); return; }
          setPatient(p);
          setPhase("home");
        })
        .catch(() => { clearPatient(); setPhase("landing"); });
    } else {
      setPhase("landing");
    }
  }, []);

  function logoutDoctor() {
    localStorage.removeItem("absorb_doctor_id");
    localStorage.removeItem("absorb_doctor_code");
    setDoctor(null);
    cacheAnalysis(null);
    setPhase("landing");
  }

  function logoutPatient() {
    localStorage.removeItem("absorb_patient_id");
    localStorage.removeItem("absorb_patient_code");
    setPatient(null);
    cachePatientSummary(null);
    setPhase("landing");
  }

  if (phase === "loading") return (
    <div className="app">
      <header className="topbar">
        <div className="brand"><img src="/asset-sheet/absorb-logo.png" alt="Absorbd" /></div>
        <div className="tagline">Clinically-grounded nutrition for IBD</div>
      </header>
      <div className="loading-screen">
        <div className="loading-spinner" />
        <div className="loading-text">Loading...</div>
      </div>
    </div>
  );

  const patientPhases = ["home", "journal", "calendar", "summary", "profile"];
  const isPatientView = patientPhases.includes(phase);

  return (
    <div className={`app ${isPatientView ? "patient-home-app" : ""}`}>
      {!isPatientView && (
        <header className="topbar">
          <div className="brand"><img src="/asset-sheet/absorb-logo.png" alt="Absorbd" /></div>
          <div className="tagline">Clinically-grounded nutrition for IBD</div>
          {doctor && (
            <button className="restart" onClick={logoutDoctor}>Log out</button>
          )}
          {patient && !doctor && (
            <button className="restart" onClick={logoutPatient}>Log out</button>
          )}
        </header>
      )}

      {phase === "landing" && (
        <LandingScreen
          onDoctor={() => setPhase("doctor-login")}
          onPatient={() => setPhase("patient-entry")}
        />
      )}

      {phase === "doctor-login" && (
        <DoctorLoginScreen
          onSuccess={(d) => {
            localStorage.setItem("absorb_doctor_id", d.id);
            localStorage.setItem("absorb_doctor_code", d.access_code);
            setDoctor(d);
            setPhase("doctor-dash");
          }}
          onBack={() => setPhase("landing")}
          onRegister={() => setPhase("doctor-register")}
        />
      )}

      {phase === "doctor-register" && (
        <DoctorRegisterScreen
          onSuccess={(d) => {
            localStorage.setItem("absorb_doctor_id", d.id);
            localStorage.setItem("absorb_doctor_code", d.access_code);
            setDoctor(d);
            setPhase("doctor-dash");
          }}
          onBack={() => setPhase("doctor-login")}
        />
      )}

      {phase === "doctor-dash" && doctor && (
        <DoctorDashboard
          doctor={doctor}
          onCreatePatient={() => setPhase("doctor-create-patient")}
          onSelectPatient={(p) => { setSelectedPatient(p); setPhase("doctor-patient-view"); }}
          onRefresh={() => {
            doctorPatients(doctor.id).then((r) => {
              setDoctor((d) => ({ ...d, patients: r.patients }));
            }).catch(() => {});
          }}
        />
      )}

      {phase === "doctor-create-patient" && doctor && (
        <CreatePatientForm
          doctorId={doctor.id}
          onSuccess={() => {
            doctorPatients(doctor.id).then((r) => {
              setDoctor((d) => ({ ...d, patients: r.patients }));
            }).catch(() => {});
            setPhase("doctor-dash");
          }}
          onBack={() => setPhase("doctor-dash")}
        />
      )}

      {phase === "doctor-patient-view" && selectedPatient && (
        <DoctorPatientView
          patient={selectedPatient}
          onBack={() => setPhase("doctor-dash")}
          onDeleted={() => {
            doctorPatients(doctor.id).then((r) => {
              setDoctor((d) => ({ ...d, patients: r.patients }));
            }).catch(() => {});
            setSelectedPatient(null);
            setPhase("doctor-dash");
          }}
          onRunAnalysis={(profile) => {
            setAnalysisProfile(profile);
            setPhase("analysis");
          }}
        />
      )}

      {phase === "patient-entry" && (
        <PatientEntryScreen
          onSuccess={(p) => {
            localStorage.setItem("absorb_patient_id", p.id);
            localStorage.setItem("absorb_patient_code", p.access_code);
            setPatient(p);
            setPhase("home");
          }}
          onBack={() => setPhase("landing")}
        />
      )}

      {phase === "home" && patient && (
        <HomeScreen
          patient={patient}
          onHome={() => setPhase("home")}
          onLogToday={() => setPhase("journal")}
          onCalendar={() => setPhase("calendar")}
          onDoctorSummary={() => setPhase("summary")}
          onProfile={() => setPhase("profile")}
          onLogout={doctor ? null : logoutPatient}
        />
      )}

      {phase === "journal" && patient && (
        <JournalChatScreen
          patient={patient}
          onComplete={() => setPhase("home")}
          onBack={() => setPhase("home")}
          onHome={() => setPhase("home")}
          onCalendar={() => setPhase("calendar")}
          onDoctorSummary={() => setPhase("summary")}
          onProfile={() => setPhase("profile")}
          onLogout={doctor ? null : logoutPatient}
        />
      )}

      {phase === "calendar" && patient && (
        <CalendarScreen
          patient={patient}
          onHome={() => setPhase("home")}
          onLogToday={() => setPhase("journal")}
          onCalendar={() => setPhase("calendar")}
          onDoctorSummary={() => setPhase("summary")}
          onProfile={() => setPhase("profile")}
          onLogout={doctor ? null : logoutPatient}
        />
      )}

      {phase === "summary" && patient && (
        <DoctorSummaryView
          patientId={patient.id}
          cachedResult={patientSummary && patientSummary.patientId === patient.id ? patientSummary.data : null}
          onResult={(data) => cachePatientSummary({ patientId: patient.id, data })}
          onBack={() => setPhase("home")}
          onHome={() => setPhase("home")}
          onLogToday={() => setPhase("journal")}
          onCalendar={() => setPhase("calendar")}
          onProfile={() => setPhase("profile")}
          onLogout={doctor ? null : logoutPatient}
        />
      )}

      {phase === "profile" && patient && (
        <ProfileScreen
          patient={patient}
          onHome={() => setPhase("home")}
          onLogToday={() => setPhase("journal")}
          onCalendar={() => setPhase("calendar")}
          onDoctorSummary={() => setPhase("summary")}
          onProfile={() => setPhase("profile")}
          onLogout={doctor ? null : logoutPatient}
        />
      )}

      {phase === "analysis" && analysisProfile && (
        <AnalysisView
          profile={analysisProfile}
          cached={analysisCache && analysisCache.patientId === analysisProfile.patient_id ? analysisCache : null}
          onComplete={(bundle) => cacheAnalysis({ patientId: analysisProfile.patient_id, ...bundle })}
          onBack={() => setPhase(selectedPatient ? "doctor-patient-view" : "landing")}
        />
      )}
    </div>
  );
}

// ── Landing Screen ───────────────────────────────────────────────────────────

function LandingScreen({ onDoctor, onPatient }) {
  return (
    <div className="landing">
      <div className="landing-hero">
        <h1>Clinically-grounded IBD nutrition intelligence.</h1>
        <p>Log daily symptoms and medications, get a ready-to-use summary before each appointment, and receive personalized nutrition guidance backed by research.</p>
      </div>
      <div className="landing-cards">
        <button className="landing-card" onClick={onDoctor}>
          <div className="lc-icon">🩺</div>
          <div className="lc-title">I'm a Doctor</div>
          <div className="lc-desc">Create patient profiles, upload lab results, and track daily adherence across your IBD patients.</div>
        </button>
        <button className="landing-card" onClick={onPatient}>
          <div className="lc-icon">📋</div>
          <div className="lc-title">I'm a Patient</div>
          <div className="lc-desc">Log daily symptoms and medications, then generate an AI-powered brief for your next appointment.</div>
        </button>
      </div>
    </div>
  );
}

// ── Doctor Login ─────────────────────────────────────────────────────────────

function DoctorLoginScreen({ onSuccess, onBack, onRegister }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function login() {
    if (!code.trim()) return;
    setBusy(true); setError("");
    try {
      const d = await doctorLogin(code.trim().toUpperCase());
      onSuccess(d);
    } catch (e) {
      setError(e.status === 401 ? "Invalid access code. Try again." : "Connection error: " + e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="entry-screen">
      <button className="back-link" onClick={onBack}>← Back</button>
      <h2>Doctor Login</h2>
      <p>Enter your practice access code (format: DOC-XXXXX)</p>
      <input
        className="code-input"
        placeholder="DOC-XXXXX"
        value={code}
        onChange={(e) => setCode(e.target.value.toUpperCase())}
        onKeyDown={(e) => e.key === "Enter" && login()}
        maxLength={9}
        autoFocus
      />
      {error && <div className="entry-error">{error}</div>}
      <button className="primary entry-btn" onClick={login} disabled={busy || !code.trim()}>
        {busy ? "Logging in..." : "Log In"}
      </button>
      <div className="entry-hint">
        Don't have a code?{" "}
        <button className="link-btn" onClick={onRegister}>Create a new doctor account</button>
      </div>
    </div>
  );
}

// ── Doctor Register ───────────────────────────────────────────────────────────

function DoctorRegisterScreen({ onSuccess, onBack }) {
  const [name, setName] = useState("");
  const [practice, setPractice] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [created, setCreated] = useState(null); // {id, access_code, name, practice}
  const [copied, setCopied] = useState(false);

  async function register() {
    if (!name.trim()) { setError("Please enter your name."); return; }
    setBusy(true); setError("");
    try {
      const result = await doctorCreate(name.trim(), practice.trim());
      if (result.error) { setError(result.error); return; }
      setCreated({ ...result, name: name.trim(), practice: practice.trim(), patients: [] });
    } catch (e) {
      setError("Connection error: " + e.message);
    } finally {
      setBusy(false);
    }
  }

  function copyCode() {
    navigator.clipboard.writeText(created.access_code).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  if (created) {
    return (
      <div className="entry-screen">
        <h2>Account Created</h2>
        <p>Save this code — share it with your patients so they can log in.</p>
        <div className="access-code-display">{created.access_code}</div>
        <button className="secondary copy-btn" onClick={copyCode}>
          {copied ? "Copied!" : "Copy code"}
        </button>
        <button className="primary entry-btn" style={{marginTop: 24}} onClick={() => onSuccess(created)}>
          Go to My Dashboard
        </button>
      </div>
    );
  }

  return (
    <div className="entry-screen">
      <button className="back-link" onClick={onBack}>&#8592; Back</button>
      <h2>Create Doctor Account</h2>
      <p>Enter your details to generate a practice access code.</p>
      <input
        className="code-input"
        style={{fontSize: 16, letterSpacing: "normal", textTransform: "none", maxWidth: 320}}
        placeholder="Your name (e.g. Dr. Sarah Kim)"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && register()}
        autoFocus
      />
      <input
        className="code-input"
        style={{fontSize: 16, letterSpacing: "normal", textTransform: "none", maxWidth: 320, marginTop: 12}}
        placeholder="Practice name (optional)"
        value={practice}
        onChange={(e) => setPractice(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && register()}
      />
      {error && <div className="entry-error">{error}</div>}
      <button className="primary entry-btn" onClick={register} disabled={busy || !name.trim()}>
        {busy ? "Creating account..." : "Create Account"}
      </button>
    </div>
  );
}

// ── Doctor Dashboard ─────────────────────────────────────────────────────────

function DoctorDashboard({ doctor, onCreatePatient, onSelectPatient, onRefresh }) {
  const patients = doctor.patients || [];

  return (
    <div className="doctor-dash">
      <div className="dash-header">
        <div>
          <div className="dash-title">{/^dr\b/i.test(doctor.name || "") ? doctor.name : `Dr. ${doctor.name}`}</div>
          <div className="dash-sub">{doctor.practice} · Code: {doctor.access_code}</div>
        </div>
        <button className="primary" onClick={onCreatePatient}>+ New Patient</button>
      </div>

      {patients.length === 0 ? (
        <div className="dash-empty">
          No patients yet. Create your first patient profile to get started.
        </div>
      ) : (
        <div className="patient-list">
          {patients.map((p) => (
            <button key={p.id} className="patient-row" onClick={() => onSelectPatient(p)}>
              <div className="pr-left">
                <div className="pr-name">{p.name?.trim() || p.condition}</div>
                {p.name?.trim() && <div className="pr-condition">{p.condition}</div>}
                <div className="pr-code">Code: {p.access_code}</div>
              </div>
              <div className="pr-stats">
                {p.last_entry_date && (
                  <span className="pr-stat">Last: {new Date(p.last_entry_date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>
                )}
                {(p.total_logged ?? p.days_logged) > 0 && (
                  <span className="pr-stat">
                    {p.total_logged ?? p.days_logged} {(p.total_logged ?? p.days_logged) === 1 ? "day" : "days"} logged
                    {p.days_logged > 0 && <span className="pr-stat-sub"> · {p.days_logged} this week</span>}
                  </span>
                )}
                {p.overall_adherence_pct != null && p.overall_adherence_pct > 0 && (
                  <span className={`pr-stat adherence-${p.overall_adherence_pct >= 80 ? "good" : "warn"}`}>
                    {p.overall_adherence_pct}% adherence
                  </span>
                )}
              </div>
              <div className="pr-arrow">›</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Create Patient Form ──────────────────────────────────────────────────────

function CreatePatientForm({ doctorId, onSuccess, onBack }) {
  const [name, setName] = useState("");
  const [condition, setCondition] = useState("");
  const [meds, setMeds] = useState([{ name: "", brand: "", dose: "", frequency: "" }]);
  const [symptoms, setSymptoms] = useState([]);
  const [dietRestrictions, setDietRestrictions] = useState("");
  const [doctorNotes, setDoctorNotes] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function addMed() { setMeds((m) => [...m, { name: "", brand: "", dose: "", frequency: "" }]); }
  function removeMed(i) { setMeds((m) => m.filter((_, idx) => idx !== i)); }
  function updateMed(i, field, val) {
    setMeds((m) => m.map((row, idx) => idx === i ? { ...row, [field]: val } : row));
  }
  function toggleSymptom(s) {
    setSymptoms((prev) => prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]);
  }

  async function submit() {
    if (!condition) { setError("Please select a condition."); return; }
    setBusy(true); setError("");
    const cleanMeds = meds.filter((m) => m.name.trim());
    const diet = dietRestrictions.split(",").map((s) => s.trim()).filter(Boolean);
    try {
      const r = await doctorCreatePatient({
        doctor_id: doctorId,
        condition,
        name: name.trim(),
        medications: cleanMeds,
        symptoms_to_watch: symptoms,
        dietary_restrictions: diet,
        doctor_notes: doctorNotes,
      });
      if (r.error) { setError(r.error); return; }
      setResult(r);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  if (result) {
    return (
      <div className="entry-screen">
        <h2>Patient Created</h2>
        <p>Give this access code to your patient:</p>
        <div className="access-code-display">{result.access_code}</div>
        <p style={{ fontSize: "13px", color: "#888" }}>They'll enter this code on the Patient login screen to access their check-in dashboard.</p>
        <button className="primary entry-btn" onClick={onSuccess}>Back to Dashboard</button>
      </div>
    );
  }

  return (
    <div className="create-patient-form">
      <div className="form-header">
        <button className="back-link" onClick={onBack}>← Back</button>
        <h2>New Patient Profile</h2>
      </div>

      <div className="form-section">
        <label className="form-label">Patient name</label>
        <input className="text-input" placeholder="First name (e.g. Alex)"
          value={name} onChange={(e) => setName(e.target.value)} />
      </div>

      <div className="form-section">
        <label className="form-label">Condition</label>
        <div className="chips">
          {CONDITIONS.map((c) => (
            <button key={c.id} className={`chip ${condition === c.id ? "on" : ""}`}
              onClick={() => setCondition(c.id)}>
              {c.label}
            </button>
          ))}
        </div>
      </div>

      <div className="form-section">
        <label className="form-label">Medications</label>
        {meds.map((m, i) => (
          <div key={i} className="med-row">
            <input className="med-input" placeholder="Drug name" value={m.name}
              onChange={(e) => updateMed(i, "name", e.target.value)} />
            <input className="med-input" placeholder="Brand (optional)" value={m.brand}
              onChange={(e) => updateMed(i, "brand", e.target.value)} />
            <input className="med-input med-small" placeholder="Dose" value={m.dose}
              onChange={(e) => updateMed(i, "dose", e.target.value)} />
            <input className="med-input med-small" placeholder="Frequency" value={m.frequency}
              onChange={(e) => updateMed(i, "frequency", e.target.value)} />
            {meds.length > 1 && (
              <button className="med-remove" onClick={() => removeMed(i)}>×</button>
            )}
          </div>
        ))}
        <button className="secondary" style={{ fontSize: "12px", padding: "4px 10px" }} onClick={addMed}>
          + Add medication
        </button>
      </div>

      <div className="form-section">
        <label className="form-label">Symptoms to watch</label>
        <div className="chips">
          {SYMPTOM_CHECKLIST.map((s) => (
            <button key={s} className={`chip ${symptoms.includes(s) ? "on" : ""}`}
              onClick={() => toggleSymptom(s)}>
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="form-section">
        <label className="form-label">Dietary restrictions (comma-separated)</label>
        <input className="text-input" placeholder="e.g. gluten-free, low-fiber, lactose intolerant"
          value={dietRestrictions} onChange={(e) => setDietRestrictions(e.target.value)} />
      </div>

      <div className="form-section">
        <label className="form-label">Doctor notes (shown to patient at each check-in)</label>
        <textarea className="notes-input" rows={3}
          placeholder="Special instructions, reminders, or things to watch for..."
          value={doctorNotes} onChange={(e) => setDoctorNotes(e.target.value)} />
      </div>

      {error && <div className="entry-error">{error}</div>}
      <button className="primary" onClick={submit} disabled={busy || !condition}>
        {busy ? "Creating..." : "Create Patient"}
      </button>
    </div>
  );
}

// ── Doctor Patient View ──────────────────────────────────────────────────────

const DOC_TYPE_LABELS = {
  lab_results: "Lab Results",
  colonoscopy: "Colonoscopy Report",
  clinical_notes: "Clinical Notes",
  prescription: "Prescription",
  pathology: "Pathology Report",
  imaging: "Imaging Report",
  infusion_record: "Infusion Record",
  dietitian_notes: "Dietitian Notes",
  operative_report: "Operative Report",
  stool_test: "Stool Test",
  bone_density: "Bone Density (DEXA)",
};

function DoctorPatientView({ patient, onBack, onRunAnalysis, onDeleted }) {
  const [labValues, setLabValues] = useState(patient.lab_values || []);
  const [documents, setDocuments] = useState(patient.documents || []);
  const [pendingLabs, setPendingLabs] = useState(null);
  const [pendingDocId, setPendingDocId] = useState(null);
  const [duplicateWarning, setDuplicateWarning] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [confirmToast, setConfirmToast] = useState(false);
  const [docType, setDocType] = useState("lab_results");
  const [entries, setEntries] = useState([]);
  const [stats, setStats] = useState(null);
  const fileRef = useRef(null);
  const [displayNotes, setDisplayNotes] = useState(patient.doctor_notes || "");
  const [editingNotes, setEditingNotes] = useState(false);
  const [editNotesText, setEditNotesText] = useState(patient.doctor_notes || "");
  const [savingNotes, setSavingNotes] = useState(false);

  const [displayDiet, setDisplayDiet] = useState(patient.dietary_restrictions || []);
  const [editingDiet, setEditingDiet] = useState(false);
  const [editDietText, setEditDietText] = useState((patient.dietary_restrictions || []).join(", "));
  const [savingDiet, setSavingDiet] = useState(false);

  const [correlations, setCorrelations] = useState(null);
  const [grounding, setGrounding] = useState(false);
  const [grounded, setGrounded] = useState(false);
  // Inline, dismissible error banner — replaces native alert() so a failed
  // action doesn't freeze the UI with an OS modal during a demo.
  const [actionError, setActionError] = useState(null);

  // Delete-patient flow: a typed-confirmation modal guards against accidents.
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const patientLabel = patient.name?.trim() || patient.condition;

  async function handleDeletePatient() {
    setDeleting(true);
    try {
      await doctorDeletePatient(patient.id, patient.doctor_id);
      onDeleted();
    } catch (err) {
      setActionError("Delete error: " + err.message);
      setDeleting(false);
    }
  }

  async function findSupportingResearch() {
    setGrounding(true);
    try {
      const r = await doctorCorrelations(patient.id, 60, true);
      setCorrelations(r.findings || []);
      setGrounded(true);
    } catch { /* leave existing findings in place */ }
    finally { setGrounding(false); }
  }

  useEffect(() => {
    journalEntries(patient.id, 7).then((r) => {
      setEntries(r.entries || []);
      setStats(r.stats || null);
    }).catch(() => {});
    patientLabValues(patient.id, true).then((r) => {
      setLabValues(r.lab_values || []);
    }).catch(() => {});
    patientDocuments(patient.id).then((r) => {
      setDocuments(r.documents || []);
    }).catch(() => {});
    doctorCorrelations(patient.id, 60).then((r) => {
      setCorrelations(r.findings || []);
    }).catch(() => setCorrelations([]));
  }, [patient.id]);

  async function handleUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setDuplicateWarning(null);
    setUploading(true);
    try {
      const r = await patientUploadDocument(patient.id, docType, file);
      if (r.duplicate) {
        setDuplicateWarning({
          filename: r.filename,
          upload_date: r.upload_date,
        });
        return;
      }
      setDocuments((prev) => [{
        id: r.document_id,
        filename: file.name,
        doc_type: docType,
        upload_date: new Date().toISOString().slice(0, 10),
        indexed: true,
        summary: "",
        has_file: r.has_file ?? true,
      }, ...prev]);
      setPendingLabs(r.lab_values_extracted || []);
      setPendingDocId(r.document_id);
    } catch (err) {
      setActionError("Upload error: " + err.message);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  function updatePendingLab(i, field, val) {
    setPendingLabs((labs) => labs.map((lab, idx) => idx === i ? { ...lab, [field]: val } : lab));
  }

  async function confirmLabs() {
    setConfirming(true);
    try {
      await patientConfirmLabValues(pendingDocId, pendingLabs);
      setLabValues((prev) => [...prev, ...pendingLabs.map((lv) => ({ ...lv, confirmed: true }))]);
      setPendingLabs(null);
      setPendingDocId(null);
      setConfirmToast(true);
      setTimeout(() => setConfirmToast(false), 3000);
    } catch (err) {
      setActionError("Confirm failed: " + err.message);
    } finally {
      setConfirming(false);
    }
  }

  function discardLabs() {
    if (window.confirm("Discard these extracted values? This cannot be undone.")) {
      setPendingLabs(null);
      setPendingDocId(null);
    }
  }

  function addLabRow() {
    setPendingLabs((prev) => [...prev, {
      test_name: "", value: "", unit: "", reference_range: "", status: "NORMAL", test_date: "",
    }]);
  }

  async function saveDoctorNotes() {
    setSavingNotes(true);
    try {
      await patientUpdate(patient.id, { doctor_notes: editNotesText });
      setDisplayNotes(editNotesText);
      setEditingNotes(false);
    } catch (err) {
      setActionError("Failed to save notes: " + err.message);
    } finally {
      setSavingNotes(false);
    }
  }

  async function saveDoctorDiet() {
    const parsed = editDietText.split(",").map((s) => s.trim()).filter(Boolean);
    setSavingDiet(true);
    try {
      await patientUpdate(patient.id, { dietary_restrictions: parsed });
      setDisplayDiet(parsed);
      setEditingDiet(false);
    } catch (err) {
      setActionError("Failed to save dietary restrictions: " + err.message);
    } finally {
      setSavingDiet(false);
    }
  }

  function buildAnalysisProfile() {
    const meds = (patient.medications || []).map((m) =>
      typeof m === "string" ? m : `${m.name}${m.brand ? ` (${m.brand})` : ""}${m.dose ? ` ${m.dose}` : ""}`
    );
    return {
      condition: patient.condition,
      medications: meds,
      symptoms: patient.symptoms_to_watch || [],
      dietary_restrictions: displayDiet,
      patient_id: patient.id,
    };
  }

  const confirmedLabs = labValues.filter((lv) => lv.confirmed !== false);
  const statusColor = (s) => s === "LOW" ? "#ef4444" : s === "HIGH" ? "#f59e0b" : "#22c55e";

  return (
    <div className="doctor-patient-view">
      {actionError && (
        <div className="action-error" role="alert">
          <span>{actionError}</span>
          <button className="action-error-x" onClick={() => setActionError(null)} aria-label="Dismiss">×</button>
        </div>
      )}
      <div className="dpv-header">
        <button className="back-link" onClick={onBack}>← Dashboard</button>
        <div className="dpv-title">
          {patient.name?.trim() || patient.condition}
          {patient.name?.trim() && <span className="dpv-subcondition">{patient.condition}</span>}
        </div>
        <div className="dpv-code">
          Patient code: <strong>{patient.access_code}</strong>
          <button className="copy-code-btn" onClick={() =>
            navigator.clipboard.writeText(patient.access_code)
          } title="Copy code">&#x2398;</button>
        </div>
      </div>

      <div className="dpv-notes">
        {editingNotes ? (
          <>
            <textarea
              className="notes-input"
              rows={3}
              value={editNotesText}
              onChange={(e) => setEditNotesText(e.target.value)}
              placeholder="Notes shown to the patient at each check-in..."
              autoFocus
            />
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <button className="secondary" onClick={() => { setEditingNotes(false); setEditNotesText(displayNotes); }}>
                Cancel
              </button>
              <button className="primary" onClick={saveDoctorNotes} disabled={savingNotes}>
                {savingNotes ? "Saving..." : "Save notes"}
              </button>
            </div>
          </>
        ) : (
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
            <div>
              <strong>Your notes for this patient:</strong>
              {displayNotes
                ? <span> {displayNotes}</span>
                : <span style={{ color: "var(--muted)", fontStyle: "italic" }}> No notes yet.</span>
              }
            </div>
            <button className="link-btn" style={{ flexShrink: 0, fontSize: "12px" }} onClick={() => setEditingNotes(true)}>
              Edit
            </button>
          </div>
        )}
      </div>

      <div className="dpv-diet">
        {editingDiet ? (
          <>
            <input
              className="notes-input"
              type="text"
              value={editDietText}
              onChange={(e) => setEditDietText(e.target.value)}
              placeholder="Dietary restrictions (comma-separated), e.g. lactose-free, low-residue"
              autoFocus
            />
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <button className="secondary" onClick={() => { setEditingDiet(false); setEditDietText(displayDiet.join(", ")); }}>
                Cancel
              </button>
              <button className="primary" onClick={saveDoctorDiet} disabled={savingDiet}>
                {savingDiet ? "Saving..." : "Save restrictions"}
              </button>
            </div>
          </>
        ) : (
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
            <div>
              <strong>Dietary restrictions:</strong>
              {displayDiet.length > 0
                ? <span> {displayDiet.join(", ")}</span>
                : <span style={{ color: "var(--muted)", fontStyle: "italic" }}> None set.</span>
              }
            </div>
            <button className="link-btn" style={{ flexShrink: 0, fontSize: "12px" }} onClick={() => setEditingDiet(true)}>
              Edit
            </button>
          </div>
        )}
      </div>

      <div className="dpv-sections">
        {/* Run analysis — surfaced first; this is the core feature */}
        <section className="dpv-section dpv-section-analysis">
          <h3>AI Analysis</h3>
          <p style={{ fontSize: "13px", color: "#888", marginBottom: "10px" }}>
            Run the 9-agent pipeline with this patient's profile and confirmed lab values. Lab-confirmed deficiencies will be highlighted in the reasoning trace.
          </p>
          <button className="primary" onClick={() => onRunAnalysis(buildAnalysisProfile())}>
            Run Analysis
          </button>
        </section>

        {/* Lab values */}
        <section className="dpv-section">
          <h3>Lab Values</h3>

          {confirmedLabs.length > 0 && (
            <table className="lab-table">
              <thead>
                <tr><th>Test</th><th>Result</th><th>Reference</th><th>Status</th><th>Date</th></tr>
              </thead>
              <tbody>
                {confirmedLabs.map((lv, i) => (
                  <tr key={i}>
                    <td>{lv.test_name}</td>
                    <td>{lv.value} {lv.unit}</td>
                    <td>{lv.reference_range || "—"}</td>
                    <td style={{ color: statusColor(lv.status), fontWeight: 600 }}>{lv.status}</td>
                    <td>{lv.test_date || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* Upload section */}
          {!pendingLabs && (
            <div className="upload-section">
              <select className="doc-type-select" value={docType} onChange={(e) => setDocType(e.target.value)}>
                <option value="lab_results">Lab Results</option>
                <option value="colonoscopy">Colonoscopy Report</option>
                <option value="clinical_notes">Clinical Notes</option>
                <option value="prescription">Prescription</option>
                <option value="pathology">Pathology Report</option>
                <option value="imaging">Imaging Report (MRI/CT)</option>
                <option value="infusion_record">Infusion Record</option>
                <option value="dietitian_notes">Dietitian Notes</option>
                <option value="operative_report">Operative Report</option>
                <option value="stool_test">Stool Test Results</option>
                <option value="bone_density">Bone Density Scan (DEXA)</option>
              </select>
              <label className={`upload-btn ${uploading ? "uploading" : ""}`}>
                {uploading ? "Processing..." : "Upload PDF"}
                <input ref={fileRef} type="file" accept=".pdf" style={{ display: "none" }}
                  onChange={handleUpload} disabled={uploading} />
              </label>
            </div>
          )}

          {/* Duplicate file warning */}
          {duplicateWarning && !pendingLabs && (
            <div className="duplicate-warning">
              <strong>Already uploaded:</strong> "{duplicateWarning.filename}" was previously uploaded on {duplicateWarning.upload_date}. Upload a different file or review the existing document below.
              <button className="link-btn" style={{ marginLeft: 10 }} onClick={() => setDuplicateWarning(null)}>Dismiss</button>
            </div>
          )}

          {/* Lab confirmation gate */}
          {pendingLabs && (
            <div className="lab-confirm-panel">
              <h4>Review Extracted Lab Values</h4>
              <p className="lab-confirm-note">AI extracted these values. Review and correct before confirming — only confirmed values feed into clinical analysis.</p>
              <table className="lab-table editable">
                <thead>
                  <tr><th>Test</th><th>Value</th><th>Unit</th><th>Reference</th><th>Status</th><th>Date</th></tr>
                </thead>
                <tbody>
                  {pendingLabs.map((lv, i) => (
                    <tr key={i}>
                      <td><input className="lab-edit" value={lv.test_name} onChange={(e) => updatePendingLab(i, "test_name", e.target.value)} /></td>
                      <td><input className="lab-edit lab-edit-sm" value={lv.value} onChange={(e) => updatePendingLab(i, "value", e.target.value)} /></td>
                      <td><input className="lab-edit lab-edit-sm" value={lv.unit} onChange={(e) => updatePendingLab(i, "unit", e.target.value)} /></td>
                      <td><input className="lab-edit" value={lv.reference_range} onChange={(e) => updatePendingLab(i, "reference_range", e.target.value)} /></td>
                      <td>
                        <select className="lab-status-select" value={lv.status} onChange={(e) => updatePendingLab(i, "status", e.target.value)}>
                          <option>LOW</option><option>NORMAL</option><option>HIGH</option>
                        </select>
                      </td>
                      <td><input className="lab-edit lab-edit-sm" value={lv.test_date} onChange={(e) => updatePendingLab(i, "test_date", e.target.value)} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {pendingLabs.length === 0 && (
                <div className="lab-empty-note">
                  No values were automatically extracted. This can happen with scanned or image-only PDFs. Use "+ Add row" to enter values manually.
                </div>
              )}
              <div className="lab-confirm-actions">
                <button className="secondary" onClick={discardLabs}>Discard</button>
                <button className="secondary" onClick={addLabRow}>+ Add row</button>
                {pendingLabs.length > 0 && (
                  <button className="primary" onClick={confirmLabs} disabled={confirming}>
                    {confirming ? "Confirming..." : `Confirm ${pendingLabs.length} Lab Value${pendingLabs.length !== 1 ? "s" : ""}`}
                  </button>
                )}
              </div>
            </div>
          )}

          {confirmToast && (
            <div className="confirm-toast">
              Lab values confirmed. They will appear in the next analysis.
            </div>
          )}
        </section>

        {/* Uploaded Documents */}
        <section className="dpv-section">
          <h3>Uploaded Documents {documents.length > 0 && <span className="doc-count">({documents.length})</span>}</h3>
          {documents.length === 0 ? (
            <div className="dash-empty" style={{ padding: "6px 0" }}>No documents uploaded yet.</div>
          ) : (
            <div className="doc-list">
              {documents.map((doc) => (
                <div key={doc.id} className="doc-row">
                  <div className="doc-row-left">
                    <span className="doc-type-badge">{DOC_TYPE_LABELS[doc.doc_type] || doc.doc_type}</span>
                    {doc.has_file ? (
                      <a
                        className="doc-filename doc-filename-link"
                        href={documentUrl(doc.id)}
                        target="_blank"
                        rel="noopener noreferrer"
                        title="Open the original PDF"
                      >
                        {doc.filename}
                      </a>
                    ) : (
                      <span className="doc-filename">{doc.filename}</span>
                    )}
                  </div>
                  <div className="doc-row-right">
                    {doc.summary && (
                      <span className="doc-summary" title={doc.summary}>
                        {doc.summary.length > 80 ? doc.summary.slice(0, 78) + "…" : doc.summary}
                      </span>
                    )}
                    <span className="doc-date">{doc.upload_date}</span>
                    <span className={`doc-status ${doc.indexed ? "indexed" : "pending"}`}>
                      {doc.indexed ? "indexed" : "pending"}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Medications */}
        {patient.medications && patient.medications.length > 0 && (
          <section className="dpv-section">
            <h3>Prescribed Medications</h3>
            <div className="med-adherence-list">
              {patient.medications.map((m, i) => {
                const name = typeof m === "string" ? m : m.name;
                const label = typeof m === "string" ? m
                  : `${m.name}${m.brand ? ` (${m.brand})` : ""}${m.dose ? ` — ${m.dose}` : ""}${m.frequency ? `, ${m.frequency}` : ""}`;
                const pct = stats?.adherence_by_med?.[name];
                return (
                  <div key={i} className="med-adherence-row">
                    <span className="ma-name">{label}</span>
                    {pct != null
                      ? <span className={`ma-pct ${pct >= 80 ? "good" : "warn"}`}>{pct}% adherence</span>
                      : <span className="ma-pct" style={{color:"var(--muted)"}}>No data yet</span>
                    }
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* Journal history */}
        <section className="dpv-section">
          <h3>Recent Check-ins {stats && `(${stats.days_logged} in last 7 days)`}</h3>
          {entries.length === 0 ? (
            <div className="dash-empty" style={{ padding: "10px 0" }}>No entries yet.</div>
          ) : (
            <div className="entry-list">
              {entries.slice(0, 10).map((e) => <EntryRow key={e.id} entry={e} />)}
            </div>
          )}
        </section>

        {/* Correlation insights */}
        <CorrelationInsightsCard findings={correlations} onGround={findSupportingResearch}
          grounding={grounding} grounded={grounded} />

        {/* Discreet, standalone delete trigger — confirmation modal guards it. */}
        <div className="delete-patient-row">
          <button className="delete-patient-link" onClick={() => { setDeleteConfirmText(""); setShowDeleteModal(true); }}>
            Delete patient
          </button>
        </div>
      </div>

      {showDeleteModal && (
        <div className="modal-overlay" onClick={() => !deleting && setShowDeleteModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginTop: 0 }}>Delete {patientLabel}?</h3>
            <p style={{ fontSize: "14px", color: "var(--muted)" }}>
              This permanently deletes the patient (code <strong>{patient.access_code}</strong>) and
              everything tied to it: all journal check-ins, uploaded documents, and lab values.
              <strong> This action cannot be undone.</strong>
            </p>
            <p style={{ fontSize: "13px", marginBottom: 6 }}>
              Type <strong>DELETE</strong> to confirm:
            </p>
            <input
              className="text-input"
              value={deleteConfirmText}
              onChange={(e) => setDeleteConfirmText(e.target.value)}
              placeholder="DELETE"
              autoFocus
              disabled={deleting}
            />
            <div style={{ display: "flex", gap: 8, marginTop: 14, justifyContent: "flex-end" }}>
              <button className="secondary" onClick={() => setShowDeleteModal(false)} disabled={deleting}>
                Cancel
              </button>
              <button
                className="danger-btn"
                onClick={handleDeletePatient}
                disabled={deleting || deleteConfirmText.trim().toUpperCase() !== "DELETE"}
              >
                {deleting ? "Deleting..." : "Permanently delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Patient Entry Screen ─────────────────────────────────────────────────────

function PatientEntryScreen({ onSuccess, onBack }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function access() {
    if (!code.trim()) return;
    setBusy(true); setError("");
    try {
      const p = await patientAccess(code.trim().toUpperCase());
      onSuccess(p);
    } catch (e) {
      setError(e.status === 401 ? "Invalid access code. Check with your doctor." : "Connection error: " + e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="entry-screen">
      <button className="back-link" onClick={onBack}>← Back</button>
      <h2>Patient Login</h2>
      <p>Enter the 6-character access code your doctor gave you.</p>
      <input
        className="code-input"
        placeholder="XXXXXX"
        value={code}
        onChange={(e) => setCode(e.target.value.toUpperCase())}
        onKeyDown={(e) => e.key === "Enter" && access()}
        maxLength={6}
        autoFocus
      />
      {error && <div className="entry-error">{error}</div>}
      <button className="primary entry-btn" onClick={access} disabled={busy || !code.trim()}>
        {busy ? "Connecting..." : "Access My Dashboard"}
      </button>
      <div className="entry-hint">Your 6-character code comes from your gastroenterologist's office.</div>
    </div>
  );
}

// ── Home Screen (patient) ────────────────────────────────────────────────────

function PatientShell({ active, onHome, onLogToday, onCalendar, onDoctorSummary, onProfile, onLogout, contentClassName = "patient-home-content", children }) {
  return (
    <div className="patient-home-shell">
      <header className="patient-home-brand" aria-label="Absorbd">
        <img src="/asset-sheet/absorb-logo.png" alt="Absorbd" />
        {onLogout && (
          <button className="patient-logout" onClick={onLogout}>Log out</button>
        )}
      </header>

      <main className={contentClassName}>
        {children}
      </main>

      <nav className="patient-bottom-nav" aria-label="Patient navigation">
        <button className={active === "home" ? "active" : ""} onClick={onHome}>
          <NavGlyph type="home" /><span>Home</span>
        </button>
        <button className={active === "logs" ? "active" : ""} onClick={onCalendar || onLogToday}>
          <NavGlyph type="logs" /><span>Logs</span>
        </button>
        <button className={active === "reports" ? "active" : ""} onClick={onDoctorSummary}>
          <NavGlyph type="reports" /><span>Reports</span>
        </button>
        <button className={active === "profile" ? "active" : ""} onClick={onProfile}>
          <NavGlyph type="profile" /><span>Profile</span>
        </button>
      </nav>
    </div>
  );
}

function HomeScreen({ patient, onHome, onLogToday, onCalendar, onDoctorSummary, onProfile, onLogout }) {
  const firstName = patient?.name?.trim()?.split(/\s+/)?.[0] || "";
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const heading = firstName ? `${greeting}, ${firstName}!` : `${greeting}!`;

  return (
    <PatientShell
      active="home"
      onHome={onHome}
      onLogToday={onLogToday}
      onCalendar={onCalendar}
      onDoctorSummary={onDoctorSummary}
      onProfile={onProfile}
      onLogout={onLogout}
    >
      <section className="patient-welcome">
        <h1>{heading}</h1>
        <p>Here's your health overview.</p>
      </section>

      <section className="feature-grid" aria-label="Primary actions">
          <article className="feature-card log-card">
            <div className="feature-art">
              <img src="/asset-sheet/nurse.png" alt="Nurse Sarah" />
              <div className="round-badge meal-badge" aria-hidden="true">
                <span className="badge-emoji">🥗</span>
              </div>
              <div className="gauge-badge" aria-hidden="true">
                <img src="/asset-sheet/pain-gauge.png" alt="" />
              </div>
            </div>
            <div className="feature-copy">
              <h2>Log Your Day</h2>
              <p>Track your symptoms, meals, and energy levels with Nurse Sarah.</p>
              <button className="feature-button green-button" onClick={onLogToday}>
                <span className="fb-plus" aria-hidden="true">+</span> Start Daily Log
              </button>
            </div>
          </article>

          <article className="feature-card visit-card">
            <div className="feature-art">
              <img src="/asset-sheet/doctor.png" alt="" aria-hidden="true" />
              <div className="calendar-badge" aria-hidden="true">
                <svg viewBox="0 0 48 48">
                  <rect x="6" y="10" width="36" height="32" rx="4" fill="#f8fbff" stroke="#8da4c5" strokeWidth="2" />
                  <rect x="6" y="10" width="36" height="9" rx="4" fill="#2b77c1" />
                  <line x1="15" y1="6" x2="15" y2="14" stroke="#e19a3b" strokeWidth="4" strokeLinecap="round" />
                  <line x1="33" y1="6" x2="33" y2="14" stroke="#e19a3b" strokeWidth="4" strokeLinecap="round" />
                  <rect x="12" y="23" width="6" height="6" rx="1" fill="#9aaac0" />
                  <rect x="21" y="23" width="6" height="6" rx="1" fill="#9aaac0" />
                  <rect x="30" y="23" width="6" height="6" rx="1" fill="#9aaac0" />
                  <rect x="12" y="32" width="6" height="6" rx="1" fill="#9aaac0" />
                  <rect x="21" y="32" width="6" height="6" rx="1" fill="#9aaac0" />
                  <rect x="30" y="32" width="6" height="6" rx="1" fill="#9aaac0" />
                </svg>
              </div>
              <div className="tube-badge" aria-hidden="true">
                <svg viewBox="0 0 38 58">
                  <rect x="12" y="6" width="14" height="42" rx="7" fill="#f8fbff" stroke="#90a6bf" strokeWidth="2" />
                  <rect x="10" y="4" width="18" height="7" rx="2" fill="#60a6dc" stroke="#3b7fb3" strokeWidth="2" />
                  <path d="M14 29h10v14a5 5 0 0 1-10 0z" fill="#e9544f" />
                  <line x1="16" y1="17" x2="22" y2="17" stroke="#90a6bf" strokeWidth="2" />
                  <line x1="16" y1="23" x2="22" y2="23" stroke="#90a6bf" strokeWidth="2" />
                </svg>
              </div>
            </div>
            <div className="feature-copy">
              <h2>My Questions</h2>
              <p>Find out what to talk to your doctor about with help from Dr. Collins.</p>
              <button className="feature-button blue-button" onClick={onDoctorSummary}>View Reports</button>
            </div>
          </article>
        </section>

        <section className="mini-grid" aria-label="Quick links">
          <button className="mini-card" onClick={onProfile}>
            <span className="mini-illustration" aria-hidden="true">
              <img src="/asset-sheet/mini-medications.png" alt="" />
            </span>
            <strong>Medications</strong>
            <span>Manage prescriptions</span>
          </button>

          <button className="mini-card" onClick={onCalendar}>
            <span className="mini-illustration" aria-hidden="true">
              <img src="/asset-sheet/mini-appointments.png" alt="" />
            </span>
            <strong>Past Logs</strong>
            <span>Review your check-ins</span>
          </button>

          <button className="mini-card" onClick={onDoctorSummary}>
            <span className="mini-illustration" aria-hidden="true">
              <img src="/asset-sheet/mini-education.png" alt="" />
            </span>
            <strong>Visit Summary</strong>
            <span>Generate a doctor brief</span>
          </button>
        </section>

        <PatientNudgesCard patientId={patient?.id} />
    </PatientShell>
  );
}

// Patient-safe insight chips derived from the correlation engine (no numbers).
// The friendly counterpart to the doctor-only CorrelationInsightsCard.
function PatientNudgesCard({ patientId }) {
  const [nudges, setNudges] = useState(null); // null = loading
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!patientId) { setNudges([]); return; }
    getPatientNudges(patientId)
      .then((r) => { if (!cancelled) setNudges(Array.isArray(r?.nudges) ? r.nudges : []); })
      .catch(() => { if (!cancelled) { setNudges([]); setFailed(true); } });
    return () => { cancelled = true; };
  }, [patientId]);

  if (failed) return null; // fail quietly: this is an enhancement, not core flow
  if (nudges === null) return null; // don't flash an empty card while loading

  return (
    <section className="nudges-card" aria-label="Personalized insights">
      <div className="nudges-head">
        <span className="nudges-spark" aria-hidden="true">&#10024;</span>
        <h2>Insights for you</h2>
      </div>
      {nudges.length === 0 ? (
        <p className="nudges-empty">
          Keep logging - we'll surface patterns as we learn your triggers.
        </p>
      ) : (
        <div className="nudges-list">
          {nudges.map((n, i) => (
            <div className="nudge-chip" key={i}>
              <p className="nudge-text">{n?.text}</p>
              {(n?.factor || n?.symptom || n?.strength_label) && (
                <div className="nudge-meta">
                  {n?.factor && <span className="nudge-tag">{corrFactorLabel(n.factor)}</span>}
                  {n?.symptom && <span className="nudge-tag">{n.symptom}</span>}
                  {n?.strength_label && <span className="nudge-strength">{n.strength_label}</span>}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function NavGlyph({ type }) {
  if (type === "home") {
    return <svg viewBox="0 0 24 24"><path d="M3 11.2 12 3l9 8.2v9.5a1.3 1.3 0 0 1-1.3 1.3h-4.9v-6.8H9.2V22H4.3A1.3 1.3 0 0 1 3 20.7z" fill="currentColor" /></svg>;
  }
  if (type === "logs") {
    return <svg viewBox="0 0 24 24"><rect x="6" y="3" width="12" height="18" rx="2" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M9 8h6M9 12h6M9 16h4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>;
  }
  if (type === "reports") {
    return <svg viewBox="0 0 24 24"><path d="M7 3h7l4 4v14H7z" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M14 3v5h4M10 13h5M10 17h5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>;
  }
  if (type === "profile") {
    return <svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="3.2" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M5 21c.8-4.1 3.1-6.1 7-6.1s6.2 2 7 6.1" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>;
  }
  return <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M12 2.8v3M12 18.2v3M5.5 5.5l2.1 2.1M16.4 16.4l2.1 2.1M2.8 12h3M18.2 12h3M5.5 18.5l2.1-2.1M16.4 7.6l2.1-2.1" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>;
}

// ── Profile Screen (patient) ─────────────────────────────────────────────────

function ProfileScreen({ patient, onHome, onLogToday, onCalendar, onDoctorSummary, onProfile, onLogout }) {
  const name = patient?.name?.trim() || "";
  const initials =
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0].toUpperCase())
      .join("") || "?";

  const condition = patient?.condition?.trim() || "Not specified";

  const doctorName = patient?.doctor_name?.trim();
  const doctorLabel = doctorName
    ? (/^dr\b/i.test(doctorName) ? doctorName : `Dr. ${doctorName}`)
    : "Not assigned";

  let memberSince = "";
  if (patient?.created_at) {
    const d = new Date(patient.created_at);
    if (!isNaN(d)) {
      memberSince = d.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
    }
  }

  const meds = Array.isArray(patient?.medications) ? patient.medications : [];
  const symptoms = Array.isArray(patient?.symptoms_to_watch) ? patient.symptoms_to_watch : [];
  const restrictions = Array.isArray(patient?.dietary_restrictions) ? patient.dietary_restrictions : [];
  const labs = Array.isArray(patient?.lab_values) ? patient.lab_values : [];
  const notes = patient?.doctor_notes?.trim() || "";

  return (
    <PatientShell
      active="profile"
      onHome={onHome}
      onLogToday={onLogToday}
      onCalendar={onCalendar}
      onDoctorSummary={onDoctorSummary}
      onProfile={onProfile}
      onLogout={onLogout}
    >
      <section className="profile-hero">
        <div className="profile-avatar" aria-hidden="true">{initials}</div>
        <div className="profile-hero-meta">
          <h1>{name || "Your Profile"}</h1>
          <span className="profile-condition-pill">{condition}</span>
          {memberSince && <div className="profile-since">Member since {memberSince}</div>}
        </div>
      </section>

      <section className="profile-section">
        <h2>Overview</h2>
        <div className="profile-info-grid">
          <ProfileField label="Diagnosis" value={condition} />
          <ProfileField label="Care Team" value={doctorLabel} />
          <ProfileField label="Patient Code" value={patient?.access_code || "—"} mono />
          <ProfileField label="Medications" value={`${meds.length} prescribed`} />
        </div>
      </section>

      <section className="profile-section">
        <h2>Prescribed Medications</h2>
        {meds.length === 0 ? (
          <p className="profile-empty">No medications on file.</p>
        ) : (
          <ul className="profile-med-list">
            {meds.map((m, i) => {
              const label = m.brand && m.brand !== m.name ? `${m.name} (${m.brand})` : m.name;
              const detail = [m.dose, m.frequency].filter(Boolean).join(" · ");
              return (
                <li key={i} className="profile-med-item">
                  <span className="profile-med-dot" aria-hidden="true" />
                  <div className="profile-med-body">
                    <strong>{label || "Medication"}</strong>
                    {detail && <span className="profile-med-detail">{detail}</span>}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="profile-section">
        <h2>Symptoms Being Monitored</h2>
        {symptoms.length === 0 ? (
          <p className="profile-empty">None specified by your care team.</p>
        ) : (
          <div className="profile-chips">
            {symptoms.map((s, i) => <span key={i} className="profile-chip">{s}</span>)}
          </div>
        )}
      </section>

      <section className="profile-section">
        <h2>Dietary Restrictions</h2>
        {restrictions.length === 0 ? (
          <p className="profile-empty">None on file.</p>
        ) : (
          <div className="profile-chips">
            {restrictions.map((r, i) => <span key={i} className="profile-chip diet">{r}</span>)}
          </div>
        )}
      </section>

      {labs.length > 0 && (
        <section className="profile-section">
          <h2>Recent Lab Values</h2>
          <div className="profile-lab-list">
            {labs.map((lv, i) => (
              <div key={i} className="profile-lab-row">
                <span className="profile-lab-name">{lv.test_name}</span>
                <span className="profile-lab-value">
                  {lv.value}{lv.unit ? ` ${lv.unit}` : ""}
                </span>
                <span className={`profile-lab-status ${String(lv.status || "").toLowerCase()}`}>
                  {lv.status || "—"}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {notes && (
        <section className="profile-section">
          <h2>Notes From Your Doctor</h2>
          <div className="profile-notes">{notes}</div>
        </section>
      )}

      {onLogout && (
        <div className="profile-logout-wrap">
          <button className="profile-logout-btn" onClick={onLogout}>Log out</button>
        </div>
      )}
    </PatientShell>
  );
}

function ProfileField({ label, value, mono }) {
  return (
    <div className="profile-field">
      <span className="profile-field-label">{label}</span>
      <span className={`profile-field-value${mono ? " mono" : ""}`}>{value}</span>
    </div>
  );
}

// ── Calendar of patient logs ─────────────────────────────────────────────────
// Month grid of journal check-ins. Logged days are marked and tappable; picking
// a day drops down a detail panel with that day's symptoms, medications taken,
// sleep, stress, and any other metrics captured in the entry's `extra` blob.

const CAL_WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const CAL_MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

// Local YYYY-MM-DD (avoids the UTC shift that toISOString() introduces).
function isoLocal(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function stressDot(stress) {
  if (stress == null) return "dot-neutral";
  return stress >= 7 ? "dot-high" : stress >= 5 ? "dot-mid" : "dot-low";
}

function prettyKey(k) {
  return k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function CalendarScreen({ patient, onHome, onLogToday, onCalendar, onDoctorSummary, onProfile, onLogout }) {
  const [entries, setEntries] = useState(null);
  const [loading, setLoading] = useState(true);
  const today = new Date();
  const [view, setView] = useState({ year: today.getFullYear(), month: today.getMonth() });
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    let cancelled = false;
    journalEntries(patient.id, 400)
      .then((d) => { if (!cancelled) setEntries(d.entries || []); })
      .catch(() => { if (!cancelled) setEntries([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [patient.id]);

  const byDate = {};
  (entries || []).forEach((e) => { byDate[e.date] = e; });

  const todayIso = isoLocal(today);
  const firstOfMonth = new Date(view.year, view.month, 1);
  const startWeekday = firstOfMonth.getDay();
  const daysInMonth = new Date(view.year, view.month + 1, 0).getDate();

  const cells = [];
  for (let i = 0; i < startWeekday; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  while (cells.length % 7 !== 0) cells.push(null);

  const loggedCount = (entries || []).filter((e) => {
    const [y, m] = e.date.split("-").map(Number);
    return y === view.year && m === view.month + 1;
  }).length;

  function shiftMonth(delta) {
    setSelected(null);
    setView((v) => {
      const m = v.month + delta;
      return { year: v.year + Math.floor(m / 12), month: ((m % 12) + 12) % 12 };
    });
  }
  function goToday() {
    setSelected(null);
    setView({ year: today.getFullYear(), month: today.getMonth() });
  }
  function pickDay(iso) {
    if (!byDate[iso]) return;
    setSelected((s) => (s === iso ? null : iso));
  }

  const selectedEntry = selected ? byDate[selected] : null;

  // Split the flat cell list into week rows so the detail panel can be injected
  // directly beneath the selected day's row as a connected dropdown.
  const weeks = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));

  let selWeek = -1;
  let selCol = -1;
  if (selected) {
    const selDay = Number(selected.slice(8, 10));
    const idx = startWeekday + selDay - 1;
    selWeek = Math.floor(idx / 7);
    selCol = idx % 7;
  }

  return (
    <PatientShell
      active="logs"
      onHome={onHome}
      onLogToday={onLogToday}
      onCalendar={onCalendar}
      onDoctorSummary={onDoctorSummary}
      onProfile={onProfile}
      onLogout={onLogout}
    >
      <section className="cal-hero">
        <div className="cal-hero-art" aria-hidden="true">
          <img
            src="/asset-sheet/calendar-nurse.png"
            alt=""
            onError={(e) => { e.currentTarget.src = "/asset-sheet/nurse.png"; }}
          />
        </div>
        <div className="cal-hero-copy">
          <h1>Your Log Calendar</h1>
          <p>Every day you check in is saved here. Tap a highlighted day to open that day's log.</p>
          <button className="feature-button green-button cal-log-btn" onClick={onLogToday}>
            <span className="fb-plus" aria-hidden="true">+</span> Log Today
          </button>
        </div>
      </section>

      <section className="cal-card">
        <div className="cal-toolbar">
          <button className="cal-nav-btn" onClick={() => shiftMonth(-1)} aria-label="Previous month">‹</button>
          <div className="cal-title">
            <strong>{CAL_MONTHS[view.month]} {view.year}</strong>
            <span>{loggedCount} {loggedCount === 1 ? "day logged" : "days logged"}</span>
          </div>
          <button className="cal-nav-btn" onClick={() => shiftMonth(1)} aria-label="Next month">›</button>
        </div>

        <button className="cal-today-link" onClick={goToday}>Jump to today</button>

        <div className="cal-weekdays">
          {CAL_WEEKDAYS.map((w) => <span key={w}>{w}</span>)}
        </div>

        {loading ? (
          <div className="cal-loading">Loading your logs…</div>
        ) : (
          <div className="cal-grid">
            {weeks.map((week, wi) => (
              <Fragment key={wi}>
                {week.map((d, ci) => {
                  const i = wi * 7 + ci;
                  if (d == null) return <span key={i} className="cal-cell empty" />;
                  const iso = isoLocal(new Date(view.year, view.month, d));
                  const entry = byDate[iso];
                  const logged = !!entry;
                  const cls = [
                    "cal-cell",
                    logged ? "logged" : "",
                    iso === todayIso ? "today" : "",
                    iso === selected ? "selected" : "",
                  ].filter(Boolean).join(" ");
                  return (
                    <button
                      key={i}
                      className={cls}
                      onClick={() => pickDay(iso)}
                      disabled={!logged}
                      aria-pressed={iso === selected}
                    >
                      <span className="cal-num">{d}</span>
                      {logged && <span className={`cal-dot ${stressDot(entry.stress_level)}`} aria-hidden="true" />}
                    </button>
                  );
                })}
                {selWeek === wi && selectedEntry && (
                  <div className="cal-detail-row" style={{ "--arrow-col": selCol }}>
                    <span className="cal-arrow" aria-hidden="true" />
                    <DayLogDetail entry={selectedEntry} onClose={() => setSelected(null)} />
                  </div>
                )}
              </Fragment>
            ))}
          </div>
        )}

        <div className="cal-legend" aria-hidden="true">
          <span><i className="cal-dot dot-low" /> Calm</span>
          <span><i className="cal-dot dot-mid" /> Moderate</span>
          <span><i className="cal-dot dot-high" /> High stress</span>
        </div>
      </section>

      {!loading && loggedCount === 0 && (
        <p className="cal-empty">No check-ins logged in {CAL_MONTHS[view.month]}. Tap “Log Today” to start your streak.</p>
      )}
    </PatientShell>
  );
}

function DayLogDetail({ entry, onClose }) {
  const d = new Date(entry.date + "T12:00:00");
  const dateLabel = d.toLocaleDateString("en-US", {
    weekday: "long", month: "long", day: "numeric", year: "numeric",
  });

  const symptoms = entry.symptoms_today || [];
  const medEntries = Object.entries(entry.medications_taken || {});
  const stress = entry.stress_level;
  const extra = entry.extra || {};
  const sleep = extra.sleep_hours;
  const bm = extra.bm_count;
  const exercise = extra.exercise;
  const foods = extra.food_today || extra.foods_today || [];
  const notes = entry.notes;

  const tiles = [];
  if (sleep != null && sleep !== "") tiles.push({ label: "Sleep", value: `${sleep}`, unit: "hrs", icon: "sleep" });
  if (stress != null) tiles.push({ label: "Stress", value: `${stress}`, unit: "/10", icon: "stress", tone: stressDot(stress) });
  if (bm != null && bm !== "") tiles.push({ label: "Bowel movements", value: `${bm}`, unit: "", icon: "bm" });
  if (exercise) tiles.push({ label: "Exercise", value: `${exercise}`, unit: "", icon: "exercise" });

  const known = new Set(["sleep_hours", "bm_count", "exercise", "food_today", "foods_today"]);
  const otherMetrics = Object.entries(extra).filter(
    ([k, v]) => !known.has(k) && v != null && v !== "" &&
      (typeof v !== "object" || (Array.isArray(v) && v.length > 0))
  );

  return (
    <section className="day-detail" role="region" aria-label={`Log for ${dateLabel}`}>
      <div className="day-detail-head">
        <h2>{dateLabel}</h2>
        <button className="day-detail-close" onClick={onClose} aria-label="Close log">×</button>
      </div>

      {tiles.length > 0 && (
        <div className="day-metric-tiles">
          {tiles.map((t, i) => (
            <div key={i} className={`metric-tile ${t.tone || ""}`}>
              <MetricIcon type={t.icon} />
              <div className="metric-body">
                <span className="metric-value">{t.value}{t.unit && <small>{t.unit}</small>}</span>
                <span className="metric-label">{t.label}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="day-section">
        <h3>Symptoms</h3>
        {symptoms.length === 0 ? (
          <p className="day-empty">No symptoms logged — feeling well.</p>
        ) : (
          <div className="day-chips">
            {symptoms.map((s, i) => <span key={i} className="day-chip symptom">{s}</span>)}
          </div>
        )}
      </div>

      <div className="day-section">
        <h3>Medications</h3>
        {medEntries.length === 0 ? (
          <p className="day-empty">No medications tracked.</p>
        ) : (
          <div className="day-chips">
            {medEntries.map(([med, status]) => (
              <span key={med} className={`day-chip med med-${status || "none"}`}>
                {med}{status ? ` · ${status}` : ""}
              </span>
            ))}
          </div>
        )}
      </div>

      {foods.length > 0 && (
        <div className="day-section">
          <h3>Foods</h3>
          <div className="day-chips">
            {foods.map((f, i) => <span key={i} className="day-chip food">{f}</span>)}
          </div>
        </div>
      )}

      {otherMetrics.length > 0 && (
        <div className="day-section">
          <h3>Other Metrics</h3>
          <div className="day-chips">
            {otherMetrics.map(([k, v]) => (
              <span key={k} className="day-chip metric">
                {prettyKey(k)}: {Array.isArray(v) ? v.join(", ") : String(v)}
              </span>
            ))}
          </div>
        </div>
      )}

      {notes && (
        <div className="day-section">
          <h3>Notes</h3>
          <p className="day-notes">{notes}</p>
        </div>
      )}
    </section>
  );
}

function MetricIcon({ type }) {
  if (type === "sleep") return <svg viewBox="0 0 24 24" className="metric-ic"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" /></svg>;
  if (type === "stress") return <svg viewBox="0 0 24 24" className="metric-ic"><path d="M12 21s-7-4.4-9.3-9A5.2 5.2 0 0 1 12 6.5 5.2 5.2 0 0 1 21.3 12C19 16.6 12 21 12 21z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" /></svg>;
  if (type === "bm") return <svg viewBox="0 0 24 24" className="metric-ic"><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M9 12h6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>;
  if (type === "exercise") return <svg viewBox="0 0 24 24" className="metric-ic"><path d="M4 12h2M18 12h2M7 8.5v7M17 8.5v7M9 12h6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>;
  return null;
}

// NOTE: LegacyHomeScreen + PatientTrendPanel (the original form-style home and
// 7-day snapshot) were removed June 9 2026. The current patient home is
// HomeScreen; trends live in the doctor view. Removed to keep one home path.

// ── Journal Chat Screen ───────────────────────────────────────────────────────

// Sentinel symptom chip that is mutually exclusive with all real symptoms.
const WELL_CHIP = "Feeling well today";

function JournalChatScreen({ patient, onComplete, onBack, onHome, onCalendar, onDoctorSummary, onProfile, onLogout }) {
  const [messages, setMessages] = useState([]);
  const [turn, setTurn] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [selected, setSelected] = useState([]);
  const [inputText, setInputText] = useState("");
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const [scaleValue, setScaleValue] = useState(5);
  const endRef = useRef(null);

  useEffect(() => {
    journalStart(patient.id)
      .then((t) => {
        if (t.error) {
          setError(
            t.error === "unknown patient"
              ? "This is a preview of the home screen. Log in with a patient access code to start a real check-in."
              : t.error
          );
          return;
        }
        setSessionId(t.session_id);
        setTurn(t);
        setMessages((t.agent || []).map((txt) => ({ role: "agent", text: txt })));
      })
      .catch((e) => setError(e.message || "Could not start check-in."));
  }, [patient.id]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  useEffect(() => {
    const sc = turn?.input?.scale;
    if (turn?.input?.kind === "scale" && sc) {
      setScaleValue(sc.default ?? sc.min ?? 0);
    }
  }, [turn]);

  function toggleChip(opt) {
    setSelected((prev) => {
      if (prev.includes(opt)) return prev.filter((x) => x !== opt);
      // "Feeling well today" is mutually exclusive with any symptom: picking it
      // clears the rest, and picking a symptom clears it.
      if (opt === WELL_CHIP) return [opt];
      return [...prev.filter((x) => x !== WELL_CHIP), opt];
    });
  }

  async function send(textOverride, selectedOverride) {
    if (sending) return;
    const text = textOverride !== undefined ? textOverride : inputText;
    const chips = selectedOverride !== undefined ? selectedOverride : selected;

    const displayMap = { confirm: "Looks good, save it", edit: "Edit something" };
    const displayText = displayMap[text] || text || (chips.length > 0 ? chips.join(", ") : "None / Skip");

    setSending(true);
    setError("");
    setMessages((prev) => [...prev, { role: "user", text: displayText }]);
    setInputText("");
    setSelected([]);
    setMessages((prev) => [...prev, { role: "typing" }]);

    try {
      const t = await journalMessage(sessionId, text, chips);
      setMessages((prev) => [
        ...prev.filter((m) => m.role !== "typing"),
        ...(t.agent || []).map((txt) => ({ role: "agent", text: txt })),
      ]);
      setTurn(t);
      if (t.done) {
        setDone(true);
        setTimeout(onComplete, 2000);
      }
    } catch (e) {
      setMessages((prev) => prev.filter((m) => m.role !== "typing"));
      setError(e.message || "Something went wrong.");
    } finally {
      setSending(false);
    }
  }

  if (done) {
    return (
      <PatientShell
        active="logs"
        onHome={onHome}
        onCalendar={onCalendar}
        onDoctorSummary={onDoctorSummary}
        onProfile={onProfile}
        onLogout={onLogout}
        contentClassName="patient-plain-content"
      >
        <div className="saved-screen">
          <div className="saved-check">&#10003;</div>
          <div className="saved-title">Check-in saved!</div>
          <div className="saved-sub">Your entry for today has been recorded.</div>
        </div>
      </PatientShell>
    );
  }

  const inp = turn?.input || {};

  return (
    <PatientShell
      active="logs"
      onHome={onHome}
      onCalendar={onCalendar}
      onDoctorSummary={onDoctorSummary}
      onProfile={onProfile}
      onLogout={onLogout}
      contentClassName="patient-chat-content"
    >
      <div className="chat-pagebar">
        <button className="back-link" onClick={onBack}>&#8592; Back</button>
        <span className="chat-pagetitle">Daily Check-in</span>
      </div>

      <div className="chat">
          {!turn && !error && (
            <div className="bubble agent typing"><span /><span /><span /></div>
          )}
          {messages.map((m, i) =>
            m.role === "typing" ? (
              <div key={i} className="bubble agent typing"><span /><span /><span /></div>
            ) : (
              <div key={i} className={`bubble ${m.role}`}>{m.text}</div>
            )
          )}
          {error && <div className="bubble agent" style={{ color: "#ef4444" }}>{error}</div>}
          <div ref={endRef} />
        </div>

        {turn && !turn.done && (
          <div className="composer">
            {inp.kind === "chips_multi" && (
              <>
                {inp.options?.length > 0 && (
                  <div className="chips">
                    {inp.options.map((opt) => (
                      <button key={opt} className={`chip ${selected.includes(opt) ? "on" : ""}`}
                        onClick={() => toggleChip(opt)}>
                        {opt}
                      </button>
                    ))}
                  </div>
                )}
                <div className="composer-row">
                  {inp.allow_text && (
                    <input className="text-input"
                      placeholder={inp.placeholder || "Or type something else..."}
                      value={inputText}
                      onChange={(e) => setInputText(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter" && !sending) send(); }}
                      disabled={sending}
                    />
                  )}
                  <button className="primary send"
                    style={inp.allow_text ? {} : { marginLeft: "auto" }}
                    onClick={() => send()} disabled={sending}>
                    {sending ? "..." : selected.length > 0 ? `Continue (${selected.length})` : "None / Skip"}
                  </button>
                </div>
              </>
            )}

            {inp.kind === "chips_single" && (
              <>
                {inp.options?.length > 0 && (
                  <div className="chips">
                    {inp.options.map((opt) => (
                      <button key={opt} className="chip" disabled={sending}
                        onClick={() => send(opt, [])}>
                        {opt}
                      </button>
                    ))}
                  </div>
                )}
                {inp.allow_text && (
                  <div className="composer-row">
                    <input className="text-input"
                      placeholder={inp.placeholder || "Or type a different answer..."}
                      value={inputText}
                      onChange={(e) => setInputText(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter" && !sending && inputText.trim()) send(); }}
                      disabled={sending}
                    />
                    <button className="primary send" onClick={() => send()}
                      disabled={sending || !inputText.trim()}>
                      {sending ? "..." : "Send"}
                    </button>
                  </div>
                )}
              </>
            )}

            {inp.kind === "text" && (
              <>
                {inp.options?.length > 0 && (
                  <div className="chips">
                    {inp.options.map((opt) => (
                      <button key={opt} className="chip" disabled={sending}
                        onClick={() => send(opt, [])}>
                        {opt}
                      </button>
                    ))}
                  </div>
                )}
                <div className="composer-row">
                  <input className="text-input"
                    placeholder={inp.placeholder || "Type your response..."}
                    value={inputText}
                    onChange={(e) => setInputText(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && !sending) send(); }}
                    disabled={sending}
                    autoFocus
                  />
                  <button className="primary send" onClick={() => send()}
                    disabled={sending || !inputText.trim()}>
                    {sending ? "..." : "Send"}
                  </button>
                </div>
              </>
            )}

            {inp.kind === "scale" && inp.scale && (
              <div className="scale-input">
                <div className="scale-value">
                  {inp.scale.max_value_label && scaleValue === inp.scale.max
                    ? inp.scale.max_value_label
                    : scaleValue}
                </div>
                <input type="range" className="scale-slider"
                  min={inp.scale.min} max={inp.scale.max} step={inp.scale.step || 1}
                  value={scaleValue}
                  onChange={(e) => setScaleValue(Number(e.target.value))}
                  disabled={sending} />
                <div className="scale-ends">
                  <span>{inp.scale.min_label ?? inp.scale.min}</span>
                  <span>{inp.scale.max_label ?? inp.scale.max}</span>
                </div>
                <button className="primary send" onClick={() => send(String(scaleValue), [])}
                  disabled={sending}>
                  {sending ? "..." : "Continue"}
                </button>
              </div>
            )}

            {inp.kind === "confirm" && (
              <div className="chips">
                <button className="chip on" disabled={sending}
                  onClick={() => send("confirm", [])}>
                  Looks good, save it
                </button>
                <button className="chip" disabled={sending}
                  onClick={() => send("edit", [])}>
                  Edit something
                </button>
              </div>
            )}
          </div>
        )}
    </PatientShell>
  );
}

// ── Correlation Insights Card ─────────────────────────────────────────────────

function corrFactorLabel(factor) {
  if (factor === "stress_level") return "Stress";
  if (factor === "sleep_hours") return "Sleep";
  if (factor === "bm_count") return "Bowel movements";
  if (factor === "exercise_active") return "Exercise";
  if (factor.startsWith("missed_")) return `Missed ${factor.slice(7)}`;
  if (factor.startsWith("ate_")) return factor.slice(4);
  return factor.replace(/_/g, " ");
}

function corrStrengthBadgeStyle(strength) {
  if (strength === "strong") return { background: "#fee2e2", color: "#dc2626", border: "1px solid #fca5a5" };
  if (strength === "moderate") return { background: "#fef3c7", color: "#b45309", border: "1px solid #fcd34d" };
  return { background: "var(--surface-2)", color: "var(--text-2)", border: "1px solid var(--border)" };
}

// One correlation finding as a connected dropdown: a clickable summary row that
// expands a panel (literature support + the full statistics) beneath it. Module
// scope + its own state so an open row stays open when the parent card re-renders
// (e.g. after "Find supporting research" grounds the findings).
function CorrelationFindingRow({ f, grounded }) {
  const [open, setOpen] = useState(false);
  const lit = f.literature;
  const dir = f.direction === "negative" ? "lower" : "higher";
  const unexpected = f.direction_flag === "unexpected";
  const hasAdjusted = typeof f.r_adjusted === "number" && f.confound_flag === true;
  return (
    <div className={`corr-row${open ? " open" : ""}${unexpected ? " corr-row-unexpected" : ""}`}>
      <button
        type="button"
        className="corr-row-head"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span style={{ fontWeight: 600, fontSize: 13 }}>{corrFactorLabel(f.factor)}</span>
        <span style={{ color: "var(--muted)", fontSize: 12 }}>&#8594;</span>
        <span style={{ fontSize: 13 }}>{f.symptom}</span>
        <span style={{ fontSize: 11, color: "var(--muted)" }}>({f.lag_label})</span>
        <span style={{ ...corrStrengthBadgeStyle(f.strength), borderRadius: 10, padding: "2px 8px", fontSize: 11, fontWeight: 600 }}>
          {f.strength}
        </span>
        {unexpected && (
          <span className="corr-badge-unexpected" title="The sign of this association is opposite to what is clinically expected, so it is likely driven by a confounder.">
            unexpected direction &middot; likely confounded
          </span>
        )}
        {lit?.supported && (
          <span style={{ background: "#ecfdf5", color: "#065f46", border: "1px solid #6ee7b7", borderRadius: 10, padding: "2px 8px", fontSize: 11, fontWeight: 600 }}>
            literature-supported
          </span>
        )}
        <span style={{ fontSize: 11, color: "var(--muted)", marginLeft: "auto", whiteSpace: "nowrap" }}>
          r={f.correlation.toFixed(2)}
          {hasAdjusted && (
            <span className="corr-adj-r" title="Partial correlation after controlling for disease-activity (flare) state.">
              {" "}adj. r={f.r_adjusted.toFixed(2)} (flare-controlled)
            </span>
          )}
          , n={f.n}, p={f.p_adjusted.toFixed(3)}
        </span>
        <span className="corr-chev" aria-hidden="true">&#9662;</span>
      </button>
      {open && (
        <div className="corr-detail">
          <span className="corr-arrow" aria-hidden="true" />
          <div className="corr-detail-panel">
            <p style={{ margin: "0 0 10px", fontSize: 12.5, color: "var(--text)", lineHeight: 1.5 }}>
              When <strong>{corrFactorLabel(f.factor).toLowerCase()}</strong> is {dir}, this
              patient tends to report more <strong>{f.symptom.toLowerCase()}</strong> {f.lag_label}.
            </p>
            <div className="corr-stat-grid">
              <div><span>Correlation (r)</span><strong>{f.correlation.toFixed(2)}</strong></div>
              <div><span>Direction</span><strong>{f.direction}</strong></div>
              <div><span>Observations (n)</span><strong>{f.n}</strong></div>
              <div><span>p (BH-FDR)</span><strong>{f.p_adjusted.toFixed(3)}</strong></div>
              <div><span>Confidence</span><strong>{f.confidence}</strong></div>
              <div><span>Tier</span><strong>{f.tier}</strong></div>
              {hasAdjusted && (
                <div><span>Adjusted r (flare-controlled)</span><strong>{f.r_adjusted.toFixed(2)}</strong></div>
              )}
            </div>
            {hasAdjusted && (
              <div className="corr-confound-note">
                Weakened after controlling for disease activity. The flare-controlled partial
                correlation (adj. r={f.r_adjusted.toFixed(2)}) is smaller than the raw r={f.correlation.toFixed(2)},
                suggesting disease activity confounds part of this association.
              </div>
            )}
            {unexpected && (
              <div className="corr-unexpected-note">
                The direction of this association is opposite to what is clinically expected, so it is
                likely confounded rather than a trustworthy independent signal.
              </div>
            )}
            {lit?.supported && (
              <div style={{ marginTop: 12, padding: "8px 10px", background: "#ecfdf5", borderRadius: 8, fontSize: 12, color: "#065f46", lineHeight: 1.45 }}>
                <strong>Documented in literature:</strong> {lit.claim}
                {lit.quote && <div style={{ marginTop: 3, fontStyle: "italic", color: "#0f766e" }}>&ldquo;{lit.quote}&rdquo;</div>}
                {lit.source && (
                  <div style={{ marginTop: 3 }}>
                    {lit.source_url
                      ? <a href={lit.source_url} target="_blank" rel="noreferrer" style={{ color: "#0f766e", fontWeight: 600, textDecoration: "none" }}>
                          {lit.source}{lit.pmid && !lit.source.includes(lit.pmid) ? ` (PMID ${lit.pmid})` : ""} &#8599;
                        </a>
                      : <span>{lit.source}</span>}
                  </div>
                )}
              </div>
            )}
            {lit && !lit.supported && (
              <div style={{ marginTop: 10, fontSize: 12, color: "var(--muted)" }}>No published support found yet.</div>
            )}
            {!lit && !grounded && (
              <div style={{ marginTop: 10, fontSize: 12, color: "var(--muted)" }}>
                Use &ldquo;Find supporting research&rdquo; above to check this against the Foundry IQ evidence base.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function CorrelationInsightsCard({ findings, onGround, grounding, grounded }) {
  const sectionHead = (text, top) => (
    <div style={{ fontSize: 11, fontWeight: 700, color: "var(--text-2)", textTransform: "uppercase", letterSpacing: "0.05em", marginTop: top ? 14 : 0, marginBottom: 4 }}>
      {text}
    </div>
  );

  const inner = () => {
    if (findings === null) {
      return <div style={{ color: "var(--muted)", fontSize: 13 }}>Loading patterns...</div>;
    }
    if (findings.length === 0) {
      return (
        <div style={{ color: "var(--muted)", fontSize: 13 }}>
          No patterns detected yet. At least 14 journal entries with consistent food, sleep, and stress tracking are needed to surface correlations.
        </div>
      );
    }
    const significant = findings.filter((f) => f.tier === "significant");
    const confirmed = significant.filter((f) => f.confidence === "confirmed");
    const emerging = significant.filter((f) => f.confidence === "emerging");
    const potential = findings.filter((f) => f.tier === "potential");
    return (
      <>
        <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 0, marginBottom: 10 }}>
          Patterns in this patient's journal (Spearman r). Significant tiers survive BH-FDR correction; potential ones are nominal signals shown so they can be confirmed with more data. Literature check is against the Foundry IQ evidence base.
        </p>
        <div style={{ marginBottom: 12 }}>
          {grounded ? (
            <span style={{ fontSize: 12, color: "#065f46", fontWeight: 600 }}>Research evidence checked against Foundry IQ.</span>
          ) : grounding ? (
            <div className="grounding-progress" role="status" aria-live="polite">
              <span className="grounding-bar" aria-hidden="true"><span className="grounding-bar-fill" /></span>
              <span className="grounding-progress-text">
                Checking {significant.length === 1 ? "1 finding" : `${significant.length} findings`} against published research...
              </span>
            </div>
          ) : (
            <button className="secondary" onClick={onGround} style={{ fontSize: 12, padding: "4px 12px" }}>
              Find supporting research
            </button>
          )}
        </div>
        {confirmed.length > 0 && (
          <>
            {sectionHead("Confirmed (n ≥ 30)", false)}
            {confirmed.map((f, i) => <CorrelationFindingRow key={`c${i}`} f={f} grounded={grounded} />)}
          </>
        )}
        {emerging.length > 0 && (
          <>
            {sectionHead("Emerging — preliminary, more data needed", confirmed.length > 0)}
            {emerging.map((f, i) => <CorrelationFindingRow key={`e${i}`} f={f} grounded={grounded} />)}
          </>
        )}
        {potential.length > 0 && (
          <>
            {sectionHead("Potential — not yet statistically confirmed", confirmed.length > 0 || emerging.length > 0)}
            {potential.map((f, i) => <CorrelationFindingRow key={`p${i}`} f={f} grounded={grounded} />)}
          </>
        )}
      </>
    );
  };

  return (
    <section className="dpv-section">
      <h3>Correlation Insights</h3>
      {inner()}
      {Array.isArray(findings) && findings.length > 0 && (
        <p className="card-disclaimer">
          Decision support only. These are statistical associations in this patient's self-reported data, not proof of cause, and not a substitute for clinical judgment.
        </p>
      )}
    </section>
  );
}

// ── Entry Row ────────────────────────────────────────────────────────────────

function EntryRow({ entry }) {
  const [expanded, setExpanded] = useState(false);
  const symptoms = entry.symptoms_today || [];
  const stress = entry.stress_level;
  const meds = entry.medications_taken || {};
  const medTaken = Object.values(meds).filter((v) => v === "taken").length;
  const medTotal = Object.keys(meds).length;
  const stressCls = stress >= 7 ? "stress-high" : stress >= 5 ? "stress-mid" : "stress-low";
  const d = new Date(entry.date + "T12:00:00");
  const dateLabel = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });

  return (
    <div className={`entry-row ${expanded ? "entry-expanded" : ""}`}
      onClick={() => setExpanded((v) => !v)}
      style={{ cursor: "pointer" }}>
      <div className="entry-date">{dateLabel}</div>
      <div className="entry-symptoms">
        {symptoms.length === 0 ? (
          <span className="no-symptoms">No symptoms</span>
        ) : (
          <>
            {(expanded ? symptoms : symptoms.slice(0, 2)).map((s, i) => (
              <span key={i} className="entry-symptom">{s}</span>
            ))}
            {!expanded && symptoms.length > 2 && (
              <span className="entry-symptom muted">+{symptoms.length - 2} more</span>
            )}
          </>
        )}
      </div>
      {stress != null && (
        <span className={`stress-badge ${stressCls}`}>Stress {stress}/10</span>
      )}
      {medTotal > 0 && (
        <span className={`med-badge ${medTaken === medTotal ? "med-ok" : "med-miss"}`}>
          Meds {medTaken}/{medTotal}
        </span>
      )}
      {expanded && entry.notes && (
        <div className="entry-notes" onClick={(e) => e.stopPropagation()}>
          {entry.notes}
        </div>
      )}
      {expanded && Object.keys(meds).length > 0 && (
        <div className="entry-med-detail" onClick={(e) => e.stopPropagation()}>
          {Object.entries(meds).map(([med, status]) => (
            <span key={med} className={`med-detail-chip med-detail-${status}`}>
              {med}: {status}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Why-Prioritized provenance block ─────────────────────────────────────────
// Renders the Synthesis "why": the converging condition/medication/diet pathways,
// the convergence count, the one-line rationale, and a lab-confirmed anchor.
// All data is already produced by the pipeline; this only surfaces it.

const TYPE_LABEL = { condition: "Condition", medication: "Medication", diet: "Diet" };

function WhyPrioritized({ nutrient, prov, onTraceFocus }) {
  const [open, setOpen] = useState(false);
  const { origins = [], convergence = 0, rationale = "", lab_confirmed = null } = prov || {};
  if (!rationale && origins.length === 0 && !lab_confirmed) return null;

  const n = convergence || origins.length;
  const countLabel = n <= 1 ? "1 pathway" : `${n} pathways converge`;
  const hasDetail = origins.length > 0 || !!lab_confirmed;

  return (
    <div className="why-block">
      {rationale && (
        <div className="why-line"><span className="why-key">Why</span> {rationale}</div>
      )}
      {hasDetail && (
        <button className={`why-toggle${open ? " open" : ""}`} onClick={() => setOpen((o) => !o)}>
          {countLabel}
          <span className="why-caret">{open ? "▾" : "▸"}</span>
        </button>
      )}
      {open && hasDetail && (
        <div className="why-detail">
          {origins.map((o, i) => (
            <div key={i} className={`pathway pathway-${o.type}`}>
              <span className="pathway-type">{TYPE_LABEL[o.type] || o.type}</span>
              <div className="pathway-body">
                <span className="pathway-origin">{o.origin}</span>
                {o.detail && <span className="pathway-detail">{o.detail}</span>}
              </div>
            </div>
          ))}
          {lab_confirmed && (
            <div className="pathway pathway-lab">
              <span className="pathway-type">Lab</span>
              <div className="pathway-body">
                <span className="pathway-origin">
                  {lab_confirmed.test_name} {lab_confirmed.value} {lab_confirmed.unit}
                  {lab_confirmed.status ? ` — ${lab_confirmed.status}` : ""}
                </span>
                <span className="pathway-detail">doctor-confirmed, not hypothesized</span>
              </div>
            </div>
          )}
          <button className="why-trace-link" onClick={() => onTraceFocus(nutrient)}>
            Show in reasoning trace
          </button>
        </div>
      )}
    </div>
  );
}

// ── Analysis View ────────────────────────────────────────────────────────────

function AnalysisView({ profile, cached, onComplete, onBack }) {
  const [trace, setTrace] = useState(cached?.trace || []);
  const [result, setResult] = useState(cached?.result || null);
  const [escalation, setEscalation] = useState(cached?.escalation || null);
  const [running, setRunning] = useState(!cached);
  const [error, setError] = useState("");
  const [focusNutrient, setFocusNutrient] = useState(null);
  const [runId, setRunId] = useState(0);
  const endRef = useRef(null);
  const focusRef = useRef(null);

  useEffect(() => {
    // Keep the cached analysis; only generate when we have nothing cached or the
    // user explicitly reran. Navigating away and back (or reloading) hits this guard.
    if (cached && runId === 0) return;

    let cancelled = false;
    let gotResult = false;
    const controller = new AbortController();
    // Local accumulators mirror the streamed state so we can lift the finished
    // bundle up for caching once the run completes.
    let accTrace = [];
    let accResult = null;
    let accEscalation = null;
    // Fresh run (including reruns): reset all stream state.
    setTrace([]); setResult(null); setEscalation(null); setError(""); setRunning(true);
    // Watchdog: the pipeline normally finishes in ~50s. If nothing has come back
    // after 100s, surface a recoverable notice instead of an indefinite spinner.
    const watchdog = setTimeout(() => {
      if (!cancelled && !gotResult) {
        setError("This is taking longer than expected — the server may be busy. You can keep waiting or retry.");
      }
    }, 100000);
    analyzeStream(profile, (ev) => {
      if (cancelled) return;
      if (ev.type === "trace") { accTrace = [...accTrace, ev]; setTrace((t) => [...t, ev]); }
      else if (ev.type === "result") {
        gotResult = true;
        if (ev.stage === "synthesis") {
          accResult = { ...(accResult || {}), synthesis: ev.data };
          setResult((r) => ({ ...(r || {}), synthesis: ev.data }));
        }
        if (ev.stage === "safety") {
          accEscalation = ev.data.escalation;
          accResult = { ...(accResult || {}), protocol: ev.data.protocol };
          setEscalation(ev.data.escalation);
          setResult((r) => ({ ...(r || {}), protocol: ev.data.protocol }));
        }
        if (ev.stage === "doctor_guide") {
          // ev.data may be the legacy array of clinician questions, or the v2
          // object { questions: [...], patient_actions: [...] }. Normalize both.
          const d = ev.data;
          const questions = Array.isArray(d) ? d : (d?.questions || []);
          const patientActions = Array.isArray(d) ? [] : (d?.patient_actions || []);
          accResult = { ...(accResult || {}), questions, patientActions };
          setResult((r) => ({ ...(r || {}), questions, patientActions }));
        }
      } else if (ev.type === "error") setError(ev.detail || "The analysis ran into an error.");
    }, controller.signal)
      .catch((e) => {
        if (!cancelled && e.name !== "AbortError") setError(String(e.message || e));
      })
      .finally(() => {
        if (!cancelled) {
          setRunning(false); clearTimeout(watchdog);
          // Persist the finished analysis so it stays until the next rerun.
          if (gotResult && accResult) {
            onComplete && onComplete({ trace: accTrace, result: accResult, escalation: accEscalation });
          }
        }
      });
    return () => { cancelled = true; clearTimeout(watchdog); controller.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile, runId]);

  const retry = () => setRunId((n) => n + 1);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [trace]);
  useEffect(() => {
    if (focusNutrient) focusRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focusNutrient]);

  const allTags = [profile.condition, ...(profile.medications || []), ...(profile.symptoms || [])];
  const traceStepClass = (ev) => {
    if (ev.step === "lab_confirmed") return "step-lab-confirmed";
    if (ev.step === "lab_context") return "step-lab-context";
    return `step-${ev.step}`;
  };

  // v1 join: index the Synthesis "why" by nutrient so a card can fall back to it
  // when the backend carry-through (v2) is absent. Both sides use canonical names.
  const synthByNutrient = {};
  for (const s of result?.synthesis || []) synthByNutrient[s.nutrient] = s;

  // v3 deep-link: first trace row mentioning the focused nutrient gets the scroll ref.
  const traceMentions = (ev) =>
    focusNutrient && (ev.detail || "").toLowerCase().includes(focusNutrient.toLowerCase());
  const focusIdx = focusNutrient ? trace.findIndex(traceMentions) : -1;

  return (
    <>
      <div className="recap">
        <span className="recap-label">Analysis</span>
        {allTags.slice(0, 4).map((tag, i) => <span key={i} className="recap-tag">{tag}</span>)}
        <button className="secondary" onClick={() => setRunId((n) => n + 1)}
          disabled={running}
          style={{ marginLeft: "auto", padding: "3px 12px", fontSize: "12px" }}>
          {running ? "Analyzing…" : "↻ Rerun"}
        </button>
        <button className="secondary" onClick={onBack}
          style={{ padding: "3px 12px", fontSize: "12px" }}>
          ← Back
        </button>
      </div>

      <div className="panels">
        <section className="panel trace">
          <div className="panel-header">
            <h2>Reasoning Trace</h2>
            {running && <span className="pulse">live</span>}
          </div>
          <div className="trace-list">
            {trace.map((ev, i) => (
              <div key={i}
                ref={i === focusIdx ? focusRef : null}
                className={`tr ${traceStepClass(ev)}${traceMentions(ev) ? " tr-focus" : ""}`}>
                <span className="agent">{AGENT_LABEL[ev.agent] || ev.agent}</span>
                <span className="stepname">{String(ev.step || "").replace(/_/g, " ")}</span>
                <span className="detail">{ev.detail}</span>
              </div>
            ))}
            {error && <div className="error">{error}</div>}
            <div ref={endRef} />
          </div>
        </section>

        <section className="panel output">
          <div className="panel-header"><h2>Personalized Protocol</h2></div>

          <div className="disclaimer">
            Clinical decision support only, not a diagnostic device. All recommendations require independent verification against the patient's labs and history, and remain subject to your clinical judgment.
          </div>

          {escalation?.urgent && (
            escalation.source === "watchlist" ? (
              <div className="watchlist-flag">
                <span className="watchlist-flag-icon" aria-hidden="true">&#128065;</span>
                <span>
                  <strong>Watch-list flag:</strong> your care team is monitoring for{" "}
                  {escalation.symptom || escalation.factor || escalation.message || "this"}.
                </span>
              </div>
            ) : (
              <div className="escalation">&#9888; {escalation.message}</div>
            )
          )}

          {result?.protocol && (
            <>
              <h3>Prioritized Nutrients</h3>
              <div className="cards">
                {result.protocol.map((p) => {
                  const s = synthByNutrient[p.nutrient] || {};
                  const prov = {
                    origins: p.origins?.length ? p.origins : (s.origins || []),
                    convergence: p.convergence ?? s.convergence ?? 0,
                    rationale: p.rationale || s.rationale || "",
                    lab_confirmed: p.lab_confirmed || s.lab_confirmed || null,
                  };
                  const ivPreferred = p.route === "iv_preferred";
                  const doseUnverified = p.safety_status === "dose_unverified";
                  return (
                    <div key={p.nutrient} className={`card pri-${p.priority}${ivPreferred ? " card-iv" : ""}`}>
                      <div className="card-head">
                        <span className="nutrient">{p.nutrient}</span>
                        <span className="card-head-meta">
                          {prov.lab_confirmed && <span className="lab-chip">LAB-CONFIRMED</span>}
                          <span className={`pill ${p.priority}`}>{p.priority}</span>
                        </span>
                      </div>
                      <div className="dose">{p.dose}</div>
                      {doseUnverified && (
                        <div className="dose-caveat">&#9888; Dose unverified. Confirm against patient-specific dosing before ordering.</div>
                      )}
                      {p.form && p.form !== "general" && <div className="meta">Form: {p.form}</div>}
                      {p.timing && <div className="meta">Timing: {p.timing}</div>}
                      {ivPreferred && (
                        <div className="iv-callout">
                          <div className="iv-callout-head">&#128137; Discuss IV iron with your clinician</div>
                          {p.route_rationale && <div className="iv-callout-body">{p.route_rationale}</div>}
                        </div>
                      )}
                      {p.lab_note && <div className="lab-note">&#9432; {p.lab_note}</div>}
                      <WhyPrioritized nutrient={p.nutrient} prov={prov} onTraceFocus={setFocusNutrient} />
                      {p.safety_note && <div className="safety">&#128737; {p.safety_note}</div>}
                      {p.caution && <div className="caution">&#9888; {p.caution}</div>}
                      {(p.sources || []).map((src) => (
                        <a key={src} href={src} target="_blank" rel="noreferrer" className="src">Source &#8599;</a>
                      ))}
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {result?.patientActions?.length > 0 && (
            <>
              <h3>Your Next Steps</h3>
              <ul className="patient-actions">
                {result.patientActions.map((a, i) => (
                  <li key={i} className="patient-action">
                    <span className="patient-action-check" aria-hidden="true">&#10003;</span>
                    <span>{typeof a === "string" ? a : (a?.text || a?.action || "")}</span>
                  </li>
                ))}
              </ul>
            </>
          )}

          {result?.questions?.length > 0 && (
            <>
              <h3 className={result?.patientActions?.length > 0 ? "for-doctor-head" : undefined}>
                {result?.patientActions?.length > 0 ? "For Your Consideration" : "Recommended Clinical Actions"}
              </h3>
              <ol className="questions actions-list">
                {result.questions.map((q, i) => {
                  const pri = q.priority === "urgent" ? "RED" : q.priority === "high" ? "YELLOW" : "GREEN";
                  return (
                    <li key={i}>
                      <div className="q">
                        {q.priority && <span className={`pill ${pri} action-pri`}>{q.priority}</span>}
                        {q.action || q.question}
                      </div>
                      {q.order && <div className="action-order"><strong>Order:</strong> {q.order}</div>}
                      {q.rationale && <div className="why">{q.rationale}</div>}
                    </li>
                  );
                })}
              </ol>
            </>
          )}

          {!result && running && (
            <div className="empty">Analyzing — the agents are reasoning over this patient's profile.</div>
          )}

          {!result && !running && error && (
            <div className="output-error" role="alert">
              <p className="output-error-title">The analysis didn't complete.</p>
              <p className="output-error-detail">{error}</p>
              <button className="feature-button blue-button" onClick={retry}>Retry analysis</button>
            </div>
          )}

        </section>
      </div>
    </>
  );
}

const SUMMARY_PROGRESS_STEPS = [
  "Loading your journal history",
  "Analyzing symptom patterns",
  "Reviewing medication adherence",
  "Identifying health trends",
  "Preparing questions for your doctor",
  "Finalizing your summary",
];

// ── Doctor Summary View ──────────────────────────────────────────────────────

function DoctorSummaryView({ patientId, cachedResult, onResult, onBack, onHome, onLogToday, onCalendar, onProfile, onLogout }) {
  const [stepsDone, setStepsDone] = useState(cachedResult ? SUMMARY_PROGRESS_STEPS.length : 0);
  const [result, setResult] = useState(cachedResult || null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  // Bumped by the Rerun button to force a fresh generation past the cache guard.
  const [rerun, setRerun] = useState(0);

  useEffect(() => {
    // Keep the cached summary; only generate when we have nothing yet or the
    // user explicitly asked to rerun. Navigating away and back hits this guard.
    if (result && rerun === 0) return;

    let cancelled = false;
    const controller = new AbortController();
    setRunning(true);
    setError("");
    setStepsDone(0);
    setResult(null);
    doctorSummaryStream(patientId, (ev) => {
      if (cancelled) return;
      if (ev.type === "trace") {
        setStepsDone((n) => Math.min(n + 1, SUMMARY_PROGRESS_STEPS.length));
      } else if (ev.type === "result" && ev.stage === "doctor_summary") {
        setResult(ev.data);
        onResult && onResult(ev.data);
      } else if (ev.type === "error") {
        setError(ev.detail || "Could not generate the summary.");
      }
    }, controller.signal)
      .catch((e) => { if (!cancelled && e.name !== "AbortError") setError(String(e.message || e)); })
      .finally(() => !cancelled && setRunning(false));
    return () => { cancelled = true; controller.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patientId, rerun]);

  return (
    <PatientShell
      active="reports"
      onHome={onHome}
      onLogToday={onLogToday}
      onCalendar={onCalendar}
      onDoctorSummary={() => {}}
      onProfile={onProfile}
      onLogout={onLogout}
      contentClassName="patient-plain-content"
    >
      <div className="recap">
        <span className="recap-label">Doctor Summary</span>
        {result && <span className="recap-tag">{result.period}</span>}
        {result && <span className="recap-tag">{result.days_tracked} days</span>}
        <button className="secondary" onClick={() => setRerun((n) => n + 1)}
          disabled={running}
          style={{ marginLeft: "auto", padding: "3px 12px", fontSize: "12px" }}>
          {running ? "Generating…" : "↻ Rerun"}
        </button>
        <button className="secondary" onClick={onBack}
          style={{ padding: "3px 12px", fontSize: "12px" }}>
          ← Back
        </button>
      </div>

      <div className="panels">
        <section className="panel trace">
          <div className="panel-header">
            <h2>Preparing your summary</h2>
            {running && <span className="pulse">working</span>}
          </div>
          <div className="summary-progress">
            {SUMMARY_PROGRESS_STEPS.map((step, i) => {
              const done = i < stepsDone;
              const active = i === stepsDone && running;
              return (
                <div key={i} className={`progress-step ${done ? "step-done" : active ? "step-active" : "step-pending"}`}>
                  <div className="ps-icon">{done ? "✓" : active ? "·" : "○"}</div>
                  <div className="ps-label">{step}</div>
                </div>
              );
            })}
            {!running && !error && (
              <div className="progress-step step-done" style={{ marginTop: 8, fontWeight: 600 }}>
                <div className="ps-icon">✓</div>
                <div className="ps-label">Summary ready</div>
              </div>
            )}
            {error && <div className="error" style={{ marginTop: 8 }}>{error}</div>}
          </div>
        </section>

        <section className="panel output">
          <div className="panel-header"><h2>Your Doctor Brief</h2></div>

          <div className="disclaimer">
            This summary is based on your self-reported data. Always review findings with your gastroenterologist.
          </div>

          {result ? (
            <>
              <div className="summary-stats">
                <div className="stat"><div className="stat-val">{result.days_tracked}</div><div className="stat-lbl">Days logged</div></div>
                <div className="stat"><div className="stat-val">{result.symptom_free_days}</div><div className="stat-lbl">Symptom-free days</div></div>
                {result.avg_stress != null && (
                  <div className="stat"><div className="stat-val">{result.avg_stress}</div><div className="stat-lbl">Avg stress /10</div></div>
                )}
                {result.overall_adherence_pct != null && (
                  <div className="stat"><div className="stat-val">{result.overall_adherence_pct}%</div><div className="stat-lbl">Med adherence</div></div>
                )}
              </div>

              {result.summary_text && <div className="summary-text">{result.summary_text}</div>}

              {result.top_symptoms?.length > 0 && (
                <>
                  <h3>Most Frequent Symptoms</h3>
                  <div className="chips" style={{ margin: "4px 0 14px" }}>
                    {result.top_symptoms.map((s) => (
                      <span key={s} className="chip on" style={{ cursor: "default" }}>{s}</span>
                    ))}
                  </div>
                </>
              )}

              {/* "Patterns Identified" is intentionally hidden from the patient
                  view: those narratives are written in clinician language (r-values,
                  lags, n). They still feed the doctor-question generation upstream. */}

              {result.questions?.length > 0 && (
                <>
                  <h3>Questions for Your Doctor</h3>
                  <ol className="questions">
                    {result.questions.map((q, i) => (
                      <li key={i}>
                        <div className="q">{q.question}</div>
                        {q.rationale && <div className="why">{q.rationale}</div>}
                      </li>
                    ))}
                  </ol>
                </>
              )}

              {result.sources?.length > 0 && (
                <div style={{ marginTop: "10px" }}>
                  {result.sources.map((s) => (
                    <a key={s} href={s} target="_blank" rel="noreferrer" className="src">Source &#8599;</a>
                  ))}
                </div>
              )}
            </>
          ) : (
            !running && <div className="empty">No summary could be generated.</div>
          )}

          {!result && running && (
            <div className="empty">Analyzing your journal history...</div>
          )}
        </section>
      </div>
    </PatientShell>
  );
}
