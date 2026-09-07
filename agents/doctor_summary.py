"""Doctor Summary Agent — synthesizes journal history into a doctor visit brief.

Multi-step reasoning over longitudinal health data:
  1. TREND   — deterministic statistics (symptom frequency, adherence %, avg stress)
  2. PATTERN — LLM identifies notable correlations and concerns
  3. GROUND  — retrieve Foundry IQ clinical evidence for key patterns
  4. QUESTION — LLM phrases specific doctor questions grounded in trends + evidence
  5. SUMMARIZE — LLM writes a patient-readable one-paragraph overview
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "data"))

from _base import complete_json, complete_text, retrieve, grounded_context, Trace  # noqa: E402
from correlations import compute_lag_correlations  # noqa: E402

NARRATE_SYSTEM = """You are a clinical data analyst writing findings for a gastroenterologist.
You are given a list of statistically significant correlations found in a patient's journal data,
along with supporting evidence passages from clinical literature.
For each correlation, write ONE concise sentence in clinician language that states:
  1. The statistical finding (mention r value, n, and lag)
  2. The supporting clinical evidence with citation

Rules:
- Never fabricate correlations or statistics not in the data
- If no clinical evidence was retrieved for a finding, still narrate the finding but note it
- Write each finding as a standalone sentence
- Combine all into a JSON list

Return ONLY JSON:
{"narratives": [{"factor": "...", "symptom": "...", "narrative": "..."}]}"""

QUESTION_SYSTEM = """You are helping an IBD patient (not a doctor) get ready for their appointment.
Using their health trends and supporting clinical evidence, write the questions the patient can read out loud to their doctor.

Write as many questions as are genuinely necessary, between 2 and 7. Use fewer when the patient is stable and only a couple of things matter; use more only when there are several distinct, important issues worth raising. Do not pad to hit a number, and do not split one concern into multiple questions.

Write the way a patient actually talks, not a clinician:
- Plain, everyday English at about an 8th-grade reading level. No medical jargon.
- Do NOT include statistics, r-values, p-values, or lab numbers in the question itself.
- If you must mention a symptom or habit, use the patient's own plain words (e.g. "when I'm stressed", "my belly pain", "the days I forget my medicine").
- Each question should be one short sentence the patient can simply ask.
- Frame them as questions, not recommendations. Never tell the patient what to take or do.

For each question, add a short "rationale": one plain-English sentence telling the patient WHY this is worth asking, written to the patient ("you").

Return ONLY JSON:
{"questions":[{"question":"...","rationale":"..."}]}"""

SUMMARY_SYSTEM = """Write a concise 2-3 sentence patient-friendly summary of their health over the tracked period.
Plain language. Focus on the most important trend. No treatment recommendations.
Return ONLY the summary text — no JSON, no preamble."""


def _compute_trends(entries: list[dict], profile: dict) -> dict:
    """Deterministic statistics — no LLM, cannot fabricate numbers."""
    if not entries:
        return {}

    n = len(entries)
    raw_meds = profile.get("medications", [])
    # Normalize: medications can be strings or {name, brand, dose, frequency} dicts
    meds = [m["name"] if isinstance(m, dict) else str(m) for m in raw_meds]

    # Symptom frequency
    symptom_counts: Counter = Counter()
    for e in entries:
        for s in (e.get("symptoms_today") or []):
            symptom_counts[s] += 1
    top_symptoms = [s for s, _ in symptom_counts.most_common(5)]
    symptom_free_days = sum(1 for e in entries if not e.get("symptoms_today"))

    # Medication adherence per drug and overall.
    # Denominator = days the med actually had a logged status (taken/missed/partial),
    # NOT total days logged. This matches data.journal.get_patient_stats so the
    # doctor summary and the patient dashboard report the same adherence number.
    adherence_by_med: dict[str, float] = {}
    for med in meds:
        statuses = [
            (e.get("medications_taken") or {}).get(med)
            for e in entries
            if (e.get("medications_taken") or {}).get(med)
        ]
        if not statuses:
            continue
        taken_days = sum(1 for s in statuses if s == "taken")
        adherence_by_med[med] = round(taken_days / len(statuses) * 100)
    overall_adherence = (
        round(sum(adherence_by_med.values()) / len(adherence_by_med))
        if adherence_by_med else None
    )

    # Stress statistics
    stress_vals = [e["stress_level"] for e in entries if e.get("stress_level") is not None]
    avg_stress = round(sum(stress_vals) / len(stress_vals), 1) if stress_vals else None
    high_stress_days = sum(1 for v in stress_vals if v >= 7)

    # Rough stress-symptom correlation: days where stress >= 7 AND symptoms present
    stress_symptom_overlap = sum(
        1 for e in entries
        if (e.get("stress_level") or 0) >= 7 and e.get("symptoms_today")
    )

    dates = sorted(e["date"] for e in entries)

    return {
        "days_tracked": n,
        "date_range": f"{dates[0]} to {dates[-1]}" if dates else "",
        "symptom_free_days": symptom_free_days,
        "top_symptoms": top_symptoms,
        "symptom_counts": dict(symptom_counts.most_common()),
        "avg_stress": avg_stress,
        "high_stress_days": high_stress_days,
        "stress_symptom_overlap_days": stress_symptom_overlap,
        "adherence_by_med": adherence_by_med,
        "overall_adherence_pct": overall_adherence,
    }


def run_doctor_summary(profile: dict, entries: list[dict], emit=None) -> dict:
    """Generate a doctor visit summary.

    emit: optional thread-safe callback for SSE events (same contract as orchestrator emit).
    Returns the full summary dict (also embedded in the SSE result event).
    """
    def _emit_trace(agent: str, step: str, detail: str) -> None:
        if emit:
            emit({"type": "trace", "agent": agent, "step": step, "detail": detail})

    trace = Trace(on_event=lambda ev: _emit_trace(ev.agent, ev.step, ev.detail))

    if not entries:
        return {
            "error": "no_entries",
            "message": "No journal entries yet. Start logging daily check-ins first.",
        }

    # ── 1. TREND ANALYSIS (deterministic code) ─────────────────────────────
    trends = _compute_trends(entries, profile)
    trace.emit(
        "DoctorSummary", "trends",
        f"{trends['days_tracked']} days: stress avg {trends['avg_stress']}, "
        f"adherence {trends['overall_adherence_pct']}%, "
        f"top symptoms: {', '.join(trends['top_symptoms'][:3]) or 'none'}",
    )

    # Medication label: prefer structured list labels if available
    med_labels = []
    for m in (profile.get("medications") or []):
        if isinstance(m, dict):
            label = m.get("name", "")
            if m.get("brand"):
                label += f" ({m['brand']})"
            if m.get("dose"):
                label += f" {m['dose']}"
            med_labels.append(label)
        else:
            med_labels.append(str(m))

    lab_values = profile.get("lab_values", [])
    lab_block = ""
    if lab_values:
        lab_lines = "\n".join(
            f"  - {lv['test_name']}: {lv['value']} {lv['unit']} "
            f"[ref {lv.get('reference_range','?')}] {lv['status']} (tested {lv.get('test_date','unknown date')})"
            for lv in lab_values
        )
        lab_block = f"\nCONFIRMED LAB VALUES:\n{lab_lines}"

    trend_text = (
        f"Patient: {profile.get('condition')}, "
        f"medications: {', '.join(med_labels) or 'none'}\n"
        f"Period: {trends.get('date_range')} ({trends['days_tracked']} days)\n"
        f"Symptom-free days: {trends['symptom_free_days']}/{trends['days_tracked']}\n"
        f"Top symptoms: {trends['top_symptoms']}\n"
        f"Avg stress: {trends['avg_stress']}/10, High-stress days: {trends['high_stress_days']}\n"
        f"Stress+symptom overlap days: {trends['stress_symptom_overlap_days']}\n"
        f"Medication adherence: {json.dumps(trends['adherence_by_med'])}"
        f"{lab_block}"
    )

    # ── 2. STATISTICAL CORRELATION COMPUTE (deterministic) ─────────────────
    patient_id = profile.get("id", "")
    stat_findings = []
    if patient_id:
        try:
            stat_findings = compute_lag_correlations(patient_id, days=60)
        except Exception as exc:
            trace.emit("DoctorSummary", "correlations", f"skipped: {exc}")

    confirmed = [f for f in stat_findings if f.confidence == "confirmed"]
    emerging = [f for f in stat_findings if f.confidence == "emerging"]
    trace.emit(
        "DoctorSummary", "correlations",
        f"{len(confirmed)} confirmed, {len(emerging)} emerging patterns found statistically",
    )

    # ── 3. GROUNDED CONTEXTUALIZATION (Foundry IQ) ─────────────────────────
    # Build search queries from statistical findings + any obvious clinical questions
    search_queries: list[str] = []
    for f in (confirmed + emerging)[:4]:
        if "stress" in f.factor:
            search_queries.append(f"psychological stress IBD flare {profile.get('condition', 'IBD')}")
        elif "missed" in f.factor:
            med_name = f.factor.replace("missed_", "")
            search_queries.append(f"medication adherence {med_name} IBD relapse")
        elif "ate_" in f.factor:
            food = f.factor.replace("ate_", "")
            search_queries.append(f"{food} food trigger IBD symptoms")
        elif "sleep" in f.factor:
            search_queries.append("sleep disturbance IBD disease activity")
        elif "exercise" in f.factor:
            search_queries.append("physical activity exercise IBD inflammatory")

    # If no statistical findings, fall back to general trend-based queries
    if not search_queries:
        if trends["high_stress_days"] > 0:
            search_queries.append("stress IBD flare correlation")
        if trends["overall_adherence_pct"] and trends["overall_adherence_pct"] < 80:
            search_queries.append("medication non-adherence IBD relapse risk")

    all_passages = []
    seen: set[str] = set()
    for query in search_queries[:4]:
        passages = retrieve(query, top=4)
        for p in passages:
            fp = p.content[:100].strip().lower()
            if fp not in seen:
                seen.add(fp)
                all_passages.append(p)
        trace.emit("DoctorSummary", "retrieve", f"'{query}': {len(passages)} passages")

    evidence_block = (
        grounded_context(all_passages)
        if all_passages
        else "(no clinical evidence retrieved)"
    )
    trace.emit("DoctorSummary", "ground", f"{len(all_passages)} unique evidence passages")

    # ── 4. NARRATE STATISTICAL FINDINGS (LLM, grounded) ────────────────────
    patterns: list[str] = []
    if stat_findings:
        findings_text = "\n".join(
            f"- Factor: {f.factor}, Symptom: {f.symptom}, Lag: {f.lag_label}, "
            f"r={f.correlation:.2f}, n={f.n}, BH-p={f.p_adjusted:.3f}, "
            f"strength={f.strength}, confidence={f.confidence}"
            for f in (confirmed + emerging)[:5]
        )
        narrate_input = (
            f"Patient condition: {profile.get('condition')}\n"
            f"Statistical findings:\n{findings_text}\n\n"
            f"Clinical evidence:\n{evidence_block}"
        )
        try:
            narrate_result = complete_json(NARRATE_SYSTEM, narrate_input)
            for item in narrate_result.get("narratives", []):
                narrative = item.get("narrative", "")
                if narrative:
                    patterns.append(narrative)
                    trace.emit("DoctorSummary", "pattern", narrative[:120])
        except Exception:
            for f in (confirmed + emerging)[:3]:
                patterns.append(
                    f"{f.symptom} correlates with {f.factor.replace('_', ' ')} "
                    f"({f.lag_label}, r={f.correlation:.2f}, n={f.n})"
                )
    else:
        trace.emit("DoctorSummary", "patterns", "no significant correlations (insufficient data)")

    # ── 5. DOCTOR QUESTIONS (LLM + grounded context) ───────────────────────
    question_input = (
        f"{trend_text}\n\n"
        f"STATISTICAL PATTERNS:\n" + ("\n".join(f"- {p}" for p in patterns) or "(none detected)") +
        f"\n\nCLINICAL EVIDENCE:\n{evidence_block}"
    )
    try:
        question_result = complete_json(QUESTION_SYSTEM, question_input)
        questions = question_result.get("questions", [])
    except Exception:
        questions = []

    trace.emit("DoctorSummary", "questions", f"{len(questions)} questions generated")
    for q in questions:
        trace.emit("DoctorSummary", "question", q.get("question", "")[:120])

    # ── 6. SUMMARY TEXT (LLM) ──────────────────────────────────────────────
    summary_input = (
        f"{profile.get('condition')} patient tracked {trends['days_tracked']} days. "
        f"Symptom-free: {trends['symptom_free_days']}/{trends['days_tracked']} days. "
        f"Top symptoms: {', '.join(trends['top_symptoms'][:3]) or 'none'}. "
        f"Avg stress: {trends['avg_stress']}/10. "
        f"Medication adherence: {trends['overall_adherence_pct']}%. "
        f"Statistical patterns: {'; '.join(patterns[:2]) or 'none detected'}"
    )
    try:
        summary_text = complete_text(SUMMARY_SYSTEM, summary_input)
    except Exception:
        summary_text = f"Tracked {trends['days_tracked']} days of health data."

    trace.emit("DoctorSummary", "conclude", "Summary complete — ready for your appointment")

    sources = sorted({p.source_url for p in all_passages if p.source_url})

    return {
        "period": trends.get("date_range", ""),
        "days_tracked": trends["days_tracked"],
        "symptom_free_days": trends["symptom_free_days"],
        "top_symptoms": trends["top_symptoms"],
        "avg_stress": trends["avg_stress"],
        "overall_adherence_pct": trends["overall_adherence_pct"],
        "adherence_by_med": trends["adherence_by_med"],
        "patterns": patterns,
        "questions": questions,
        "summary_text": summary_text,
        "sources": sources,
        "correlation_findings": [
            {
                "factor": f.factor,
                "symptom": f.symptom,
                "lag_label": f.lag_label,
                "correlation": round(f.correlation, 3),
                "p_adjusted": round(f.p_adjusted, 4),
                "n": f.n,
                "strength": f.strength,
                "confidence": f.confidence,
            }
            for f in stat_findings[:8]
        ],
    }
