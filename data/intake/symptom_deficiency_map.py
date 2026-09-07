"""Symptom -> candidate deficiency mapping for the Intake Agent.

The symptom checklist in intake is not just UX. Each checked symptom feeds
the Deficiency Hypothesis Agent as additional evidence, raising the
confidence of associated deficiencies. RED_FLAG_KEYWORDS trigger an
immediate escalation note before the pipeline even runs.

NOTE: These are HINTS used to weight hypotheses, not diagnoses. The agents
must still retrieve and cite clinical evidence before asserting anything.
The deficiency associations below should be cross-checked against the
Section 6 (symptom-to-deficiency) output of the clinical research run.
"""

# Plain-language symptom (as shown to patient) -> ranked candidate deficiencies
SYMPTOM_DEFICIENCY_HINTS = {
    "extreme fatigue":             ["iron", "b12", "folate", "vitamin_d"],
    "hair loss or brittle nails":  ["zinc", "iron", "biotin"],
    "bone pain or muscle cramps":  ["vitamin_d", "calcium", "magnesium"],
    "tingling or numbness in hands or feet": ["b12", "folate"],
    "frequent infections or slow healing":   ["zinc", "vitamin_d"],
    "irregular heartbeat or palpitations":   ["magnesium", "potassium"],
    "night blindness or dry eyes":           ["vitamin_a"],
    "swollen or sore tongue":                ["b12", "folate", "iron"],
    "easy bruising or bleeding":             ["vitamin_k", "vitamin_c"],
    "low mood or depression":                ["vitamin_d", "b12", "folate", "omega_3"],
}

# Symptoms that warrant an immediate escalation flag regardless of other findings.
# Each entry is a list of keyword tokens; a reported symptom matches if it CONTAINS
# any token (case-insensitive). Substring matching means free-text variants like
# "palpitations", "heart palpitations", or "irregular heartbeat" all trigger, not
# just the exact checklist label. Keep this list conservative: only genuine
# seek-care-now signals belong here.
RED_FLAG_KEYWORDS = [
    "palpitation",          # possible electrolyte (Mg/K) disturbance / arrhythmia
    "irregular heartbeat",
    "chest pain",
    "severe bleeding",
    "heavy rectal bleeding",
    "blood in stool",
    "bloody stool",
    "fainting",
    "passing out",
    "shortness of breath",
    "difficulty breathing",
    "severe abdominal pain",
]

# The full checklist presented to the patient during intake, in display order.
SYMPTOM_CHECKLIST = list(SYMPTOM_DEFICIENCY_HINTS.keys())


def deficiencies_for_symptoms(symptoms: list[str]) -> dict[str, int]:
    """Aggregate symptom hints into a deficiency -> hit-count weighting.

    A deficiency named by multiple reported symptoms gets a higher count,
    which the Deficiency Hypothesis Agent can use to raise its confidence.
    """
    weights: dict[str, int] = {}
    for symptom in symptoms:
        for deficiency in SYMPTOM_DEFICIENCY_HINTS.get(symptom.strip().lower(), []):
            weights[deficiency] = weights.get(deficiency, 0) + 1
    return weights


def has_red_flag(symptoms: list[str]) -> list[str]:
    """Return any reported symptoms that are red flags requiring escalation.

    Matches on keyword substrings (not exact label equality) so free-text and
    checklist phrasings both escalate. Returns the original symptom strings that
    matched, so the escalation message can quote the patient's own wording.
    """
    flagged = []
    for s in symptoms:
        low = s.strip().lower()
        if any(kw in low for kw in RED_FLAG_KEYWORDS):
            flagged.append(s)
    return flagged
