"""Statistical lag-correlation engine for Absorbd journal data.

Computes Spearman rank correlations between patient behavioral factors
(stress, missed medications, food triggers, sleep, exercise, BM count)
and symptoms, using biologically anchored time lags.

Multiple-comparisons correction: Benjamini-Hochberg FDR (q < 0.10).
Minimum observation filter: both factor and symptom must appear on >= 7 days.

Doctor-facing only — patients never see raw correlation output.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from journal import get_entries  # noqa: E402

# Biologically anchored lags per factor type (determined by mechanism, not data)
_FACTOR_LAGS: dict[str, list[int]] = {
    "stress": [0, 1],       # HPA axis: same-day + next-day gut response
    "missed": [1, 2],       # Medication non-adherence: accumulates over 1-2 days
    "food": [1],            # Gut transit: 6-24 hours
    "sleep": [1],           # Next-day recovery / inflammatory effect
    "exercise": [0, 1],     # Immediate anti-inflammatory + next-day
    "bm": [0],              # Same-day disease activity indicator
}

_LAG_LABELS = {0: "same day", 1: "next day", 2: "2 days later"}

# A "potential" correlation did not survive FDR correction but is nominally
# associated: it is kept (not discarded) so the doctor can see what is worth
# gathering more data on, and so literature grounding can confirm whether the
# relationship is documented even when our sample is still small.
_POTENTIAL_MAX_P_RAW = 0.10   # nominal significance before multiple-comparison correction
_POTENTIAL_MIN_R = 0.25       # at least a near-moderate effect size

# ── Direction-plausibility (FIX #2) ───────────────────────────────────────────
# Mechanistically expected sign of the correlation between each factor and a
# symptom. A factor whose observed correlation contradicts this sign is almost
# certainly confounded (e.g. by the disease-activity flare) or spurious, and must
# NOT be presented to a doctor as a trustworthy "significant" finding.
#   +1 -> more of the factor should mean MORE symptoms
#   -1 -> more of the factor should mean FEWER symptoms
_EXPECTED_SIGN: dict[str, int] = {
    "stress_level": +1,       # more stress -> more symptoms
    "bm_count": +1,           # more bowel movements -> more disease activity
    "sleep_hours": -1,        # more sleep -> fewer symptoms
    "exercise_active": -1,    # more activity -> fewer symptoms (anti-inflammatory)
    # missed_<med> and ate_<food> handled by prefix in _expected_sign()
}


def _expected_sign(factor: str) -> int | None:
    """Mechanistically expected sign of r for a factor, or None if unknown.

    Missing a medication should associate with MORE symptoms (+1); eating a
    trigger food should associate with MORE symptoms (+1).
    """
    if factor.startswith("missed_"):
        return +1
    if factor.startswith("ate_"):
        return +1
    return _EXPECTED_SIGN.get(factor)


def _direction_flag(factor: str, r: float) -> str:
    """"expected" if sign(r) matches the mechanism, else "unexpected".

    When the expected sign is unknown we do not flag the finding (treat as
    "expected" so unknown factors are not punished).
    """
    exp = _expected_sign(factor)
    if exp is None or r == 0:
        return "expected"
    observed = 1 if r > 0 else -1
    return "expected" if observed == exp else "unexpected"


# Activity-confounder adjustment (FIX #5). When the disease-activity-adjusted
# correlation collapses, the raw association was largely the flare confound.
_CONFOUND_ATTENUATION = 0.5   # adjusted < half of raw -> substantially weakened
_CONFOUND_FLOOR = 0.2         # ...or adjusted drops below this absolute value


@dataclass
class CorrelationFinding:
    factor: str        # e.g. "stress_level", "missed_Mesalamine", "ate_Dairy"
    symptom: str       # e.g. "Cramping"
    lag_days: int
    correlation: float  # Spearman r, -1 to 1
    p_adjusted: float   # BH-corrected p-value
    p_raw: float        # uncorrected Spearman p-value
    n: int              # number of valid (day_N, day_N+lag) pairs
    strength: str       # "weak" | "moderate" | "strong"
    direction: str      # "positive" | "negative"
    confidence: str     # "confirmed" (n >= 30) | "emerging" (n = 14-29)
    tier: str           # "significant" (survived FDR) | "potential" (nominal only)
    lag_label: str
    # ── FIX #2: direction-plausibility gate ──────────────────────────────────
    # "expected" if sign(r) matches the mechanism, "unexpected" if it contradicts
    # it (e.g. "missing meds -> fewer symptoms"). Unexpected findings are demoted
    # out of the trustworthy "significant" tier (see compute_lag_correlations).
    direction_flag: str = "expected"
    # ── FIX #5: disease-activity covariate adjustment ────────────────────────
    # Partial Spearman r controlling for an activity proxy (rolling-mean bm_count).
    # None when it could not be computed. confound_flag is True when the adjusted
    # correlation substantially weakens vs raw, i.e. the raw signal was largely
    # the flare confound. Raw `correlation` stays the primary number.
    r_adjusted: float | None = None
    confound_flag: bool = False
    # Foundry IQ literature grounding, attached later by correlation_grounding.
    # None = not yet checked; {"supported": False} = checked, no proof found.
    literature: dict | None = None


def _strength(r: float) -> str:
    ar = abs(r)
    if ar >= 0.6:
        return "strong"
    if ar >= 0.3:
        return "moderate"
    return "weak"


def _factor_lag_type(factor: str) -> str:
    if factor == "stress_level":
        return "stress"
    if factor.startswith("missed_"):
        return "missed"
    if factor.startswith("ate_"):
        return "food"
    if factor == "sleep_hours":
        return "sleep"
    if factor == "exercise_active":
        return "exercise"
    if factor == "bm_count":
        return "bm"
    return "stress"  # default


# ── Disease-activity confounder adjustment (FIX #5) ───────────────────────────

def _rankdata(vals: list[float]) -> list[float]:
    """Average-rank transform (ties share the mean of their rank positions)."""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # 1-based average rank
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _rank_residuals(vals: list[float], control_ranks: list[float]) -> list[float] | None:
    """Residualize `vals` on `control_ranks` via simple rank-based OLS.

    Rank-transform `vals`, regress those ranks linearly on the control ranks, and
    return the residuals. Returns None if the control has no variance.
    """
    n = len(vals)
    if n < 2:
        return None
    y = _rankdata(vals)
    x = control_ranks
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    var_x = sum((xi - mean_x) ** 2 for xi in x)
    if var_x == 0:
        return None
    cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    slope = cov / var_x
    intercept = mean_y - slope * mean_x
    return [y[i] - (intercept + slope * x[i]) for i in range(n)]


def _partial_spearman(
    x_vals: list[float], y_vals: list[float], control_vals: list[float],
) -> float | None:
    """Spearman r between x and y after partialling out a control variable.

    Both x and y are rank-residualized on the control's ranks, then Pearson-
    correlated (equivalent to Spearman on the residualized ranks). Returns None
    when it cannot be computed (no variance in the control or residuals).
    """
    if not (len(x_vals) == len(y_vals) == len(control_vals)) or len(x_vals) < 3:
        return None
    control_ranks = _rankdata(control_vals)
    rx = _rank_residuals(x_vals, control_ranks)
    ry = _rank_residuals(y_vals, control_ranks)
    if rx is None or ry is None:
        return None
    n = len(rx)
    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n
    var_rx = sum((v - mean_rx) ** 2 for v in rx)
    var_ry = sum((v - mean_ry) ** 2 for v in ry)
    if var_rx == 0 or var_ry == 0:
        return None
    cov = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    denom = (var_rx * var_ry) ** 0.5
    if denom == 0:
        return None
    return cov / denom


def _is_confounded(r: float, r_adjusted: float | None) -> bool:
    """True when the activity-adjusted correlation substantially weakens vs raw."""
    if r_adjusted is None:
        return False
    return abs(r_adjusted) < _CONFOUND_ATTENUATION * abs(r) or abs(r_adjusted) < _CONFOUND_FLOOR


def compute_lag_correlations(
    patient_id: str,
    days: int = 60,
    min_obs: int = 7,
    fdr_threshold: float = 0.10,
) -> list[CorrelationFinding]:
    """Return statistically significant lag-correlations sorted by |r| descending."""
    try:
        from scipy.stats import spearmanr
        from statsmodels.stats.multitest import multipletests
    except ImportError:
        return []

    entries = get_entries(patient_id, days=days)
    if len(entries) < 14:
        return []

    # Index entries by date string for fast lag lookups
    by_date: dict[str, dict] = {e["date"]: e for e in entries}
    all_dates = sorted(by_date.keys())

    # ── Build factor time series ──────────────────────────────────────────────
    factors: dict[str, dict[str, float]] = defaultdict(dict)

    # Get all medication names from entries
    med_names: set[str] = set()
    for e in entries:
        med_names.update(e.get("medications_taken", {}).keys())

    # Get all food triggers from entries
    food_names: set[str] = set()
    for e in entries:
        food_names.update((e.get("extra") or {}).get("food_today", []))

    # Get all symptoms from entries
    symptom_names: set[str] = set()
    for e in entries:
        symptom_names.update(e.get("symptoms_today", []))

    for d in all_dates:
        e = by_date[d]
        extra = e.get("extra") or {}

        # Continuous factors
        if e.get("stress_level") is not None:
            factors["stress_level"][d] = float(e["stress_level"])

        sleep = extra.get("sleep_hours")
        if sleep is not None:
            factors["sleep_hours"][d] = float(sleep)

        bm = extra.get("bm_count")
        if bm is not None:
            factors["bm_count"][d] = float(bm)

        exercise = extra.get("exercise")
        if exercise is not None:
            factors["exercise_active"][d] = 1.0 if exercise in ("Moderate", "Intense") else 0.0

        # Per-medication missed flag (1 = missed, 0 = taken or partial)
        for med, status in (e.get("medications_taken") or {}).items():
            key = f"missed_{med}"
            factors[key][d] = 1.0 if status == "missed" else 0.0

        # Per-food trigger flag (1 = ate it, 0 = didn't log it)
        food_today = set(extra.get("food_today") or [])
        for food in food_names:
            key = f"ate_{food}"
            factors[key][d] = 1.0 if food in food_today else 0.0

    # ── Build disease-activity proxy (FIX #5) ─────────────────────────────────
    # Rolling mean (window 3) of bm_count is a reasonable per-day flare proxy:
    # stress, sleep, BM count and symptoms all co-move during a flare, so
    # partialling this out reveals which factor->symptom links survive once the
    # shared flare component is removed.
    bm_series = factors.get("bm_count", {})
    activity_proxy: dict[str, float] = {}
    for idx, d in enumerate(all_dates):
        window = [bm_series[all_dates[j]]
                  for j in range(max(0, idx - 2), idx + 1)
                  if all_dates[j] in bm_series]
        if window:
            activity_proxy[d] = sum(window) / len(window)

    # ── Build symptom time series ─────────────────────────────────────────────
    symptoms: dict[str, dict[str, float]] = {}
    for sym in symptom_names:
        symptoms[sym] = {d: 1.0 if sym in by_date[d].get("symptoms_today", []) else 0.0
                         for d in all_dates}

    # ── Collect all (factor, symptom, lag) tests ──────────────────────────────
    tests: list[dict] = []

    for factor_key, factor_series in factors.items():
        lag_type = _factor_lag_type(factor_key)
        lags = _FACTOR_LAGS.get(lag_type, [0])

        for symptom_key, symptom_series in symptoms.items():
            for lag in lags:
                # Build aligned pairs (and the activity proxy on the factor day)
                x_vals, y_vals, c_vals = [], [], []
                for d in all_dates:
                    lag_date = (date.fromisoformat(d) + timedelta(days=lag)).isoformat()
                    if d in factor_series and lag_date in symptom_series:
                        x_vals.append(factor_series[d])
                        y_vals.append(symptom_series[lag_date])
                        c_vals.append(activity_proxy.get(d))

                n = len(x_vals)
                if n < 14:
                    continue

                # Observation filter: factor must vary on >= min_obs days,
                # symptom must be present on >= min_obs days
                factor_active = sum(1 for v in x_vals if v > 0)
                symptom_active = sum(1 for v in y_vals if v > 0)
                if factor_active < min_obs or symptom_active < min_obs:
                    continue

                # Constant arrays produce undefined correlation
                if len(set(x_vals)) < 2 or len(set(y_vals)) < 2:
                    continue

                try:
                    r, p = spearmanr(x_vals, y_vals)
                except Exception:
                    continue

                if abs(r) < 0.05:  # skip near-zero correlations before BH
                    continue

                # Partial Spearman controlling for the disease-activity proxy.
                # The factor itself IS the activity proxy (bm_count) -> skip;
                # partialling a variable out of itself is undefined/meaningless.
                r_adjusted: float | None = None
                if factor_key != "bm_count" and all(c is not None for c in c_vals):
                    try:
                        r_adjusted = _partial_spearman(x_vals, y_vals, c_vals)
                    except Exception:
                        r_adjusted = None

                tests.append({
                    "factor": factor_key,
                    "symptom": symptom_key,
                    "lag": lag,
                    "r": float(r),
                    "p": float(p),
                    "n": n,
                    "r_adjusted": r_adjusted,
                })

    if not tests:
        return []

    # ── Benjamini-Hochberg FDR correction ─────────────────────────────────────
    pvals = [t["p"] for t in tests]
    try:
        reject, p_adj, _, _ = multipletests(pvals, method="fdr_bh", alpha=fdr_threshold)
    except Exception:
        return []

    findings: list[CorrelationFinding] = []
    for i, test in enumerate(tests):
        r = test["r"]
        n = test["n"]
        if reject[i]:
            tier = "significant"
        else:
            # Keep nominally-significant, near-moderate associations as "potential"
            # rather than discarding them. Everything else is dropped as noise.
            if test["p"] >= _POTENTIAL_MAX_P_RAW or abs(r) < _POTENTIAL_MIN_R:
                continue
            tier = "potential"

        # FIX #2 — Direction-plausibility gate. A finding whose sign contradicts
        # the mechanism (e.g. "missing meds -> fewer symptoms") is demoted out of
        # the trustworthy "significant" tier down to "potential", keeping the flag
        # so the UI can badge it "unexpected direction, likely confounded". We
        # demote rather than drop so the doctor still sees the (suspect) signal.
        direction_flag = _direction_flag(test["factor"], r)
        if direction_flag == "unexpected" and tier == "significant":
            tier = "potential"

        r_adjusted = test.get("r_adjusted")
        confound_flag = _is_confounded(r, r_adjusted)

        confidence = "confirmed" if n >= 30 else "emerging"
        findings.append(CorrelationFinding(
            factor=test["factor"],
            symptom=test["symptom"],
            lag_days=test["lag"],
            correlation=r,
            p_adjusted=float(p_adj[i]),
            p_raw=float(test["p"]),
            n=n,
            strength=_strength(r),
            direction="positive" if r > 0 else "negative",
            confidence=confidence,
            tier=tier,
            lag_label=_LAG_LABELS.get(test["lag"], f"lag {test['lag']}"),
            direction_flag=direction_flag,
            r_adjusted=r_adjusted,
            confound_flag=confound_flag,
        ))

    # Significant before potential; within a tier, strongest |r| first.
    findings.sort(key=lambda f: (f.tier == "potential", -abs(f.correlation)))
    return findings


# ── Patient-safe nudges (FIX #10) ─────────────────────────────────────────────

def _strength_label(r: float) -> str:
    """Qualitative |r| bucket for patients. Never exposes the number itself."""
    ar = abs(r)
    if ar >= 0.6:
        return "strong"
    if ar >= 0.3:
        return "moderate"
    return "mild"


def _nudge_text(factor: str, symptom: str) -> str | None:
    """Second-person, motivating plain-language nudge. None if no safe phrasing.

    Only POSITIVE-direction, mechanistically-expected behaviors reach this point
    (the inclusion gate in curated_patient_nudges enforces direction_flag ==
    "expected"), so the phrasing here is always safe and actionable.
    """
    # Phrased so the symptom is the OBJECT, not the subject, so the verb agrees
    # whether the symptom is singular ("cramping") or plural ("bloody stools").
    sym = symptom.lower()
    if factor == "stress_level":
        return (f"You tend to get {sym} after your higher-stress days. "
                "Stress management may help.")
    if factor == "sleep_hours":
        return (f"You tend to have less {sym} after nights when you sleep more. "
                "Protecting your sleep may help.")
    if factor == "exercise_active":
        return (f"You tend to have less {sym} around your more active days. "
                "Gentle, regular activity may help.")
    if factor == "bm_count":
        return None  # not an actionable behavior for a patient
    if factor.startswith("ate_"):
        food = factor[len("ate_"):]
        return (f"You tend to get {sym} the day after you eat {food}. "
                "It may be worth watching how that food affects you.")
    # NOTE: missed_<med> is deliberately NOT handled here. A patient must never be
    # nudged about medication adherence from this engine, and the direction gate
    # already guarantees only "missing -> MORE symptoms" could ever arrive, which
    # is not a safe patient message. The assert below is the belt-and-suspenders.
    return None


def curated_patient_nudges(findings: list) -> list[dict]:
    """Safe, motivating, plain-language nudges for a PATIENT (no r/p/n numbers).

    Inclusion rules (ALL must hold):
      - tier == "significant"
      - direction_flag == "expected"
      - confound_flag is False
      - if literature is present, literature.supported is True

    Returns list of {text, strength_label, factor, symptom}. Never emits a
    "missing medication -> fewer symptoms" style nudge.
    """
    # Dedupe by (factor, symptom): the same behavior can correlate with the same
    # symptom at more than one lag (e.g. stress -> cramping same-day AND next-day).
    # Keep only the strongest so the patient sees one clear nudge per pair.
    seen: set = set()
    nudges: list[dict] = []
    for f in sorted(findings, key=lambda x: abs(getattr(x, "correlation", 0.0)),
                    reverse=True):
        key = (f.factor, f.symptom)
        if key in seen:
            continue
        if getattr(f, "tier", None) != "significant":
            continue
        if getattr(f, "direction_flag", "expected") != "expected":
            continue
        if getattr(f, "confound_flag", False):
            continue
        lit = getattr(f, "literature", None)
        if isinstance(lit, dict) and lit.get("supported") is not True:
            continue

        # Medication-adherence is never surfaced to a patient by this engine,
        # regardless of statistical direction. Skip it before building any text.
        if str(f.factor).startswith("missed_"):
            continue

        text = _nudge_text(f.factor, f.symptom)
        if not text:
            continue

        # Belt-and-suspenders: a medication-adherence nudge must never be emitted.
        assert not str(f.factor).startswith("missed_"), (
            f"refusing to build a medication-adherence patient nudge for {f.factor}"
        )

        seen.add(key)
        nudges.append({
            "text": text,
            "strength_label": _strength_label(f.correlation),
            "factor": f.factor,
            "symptom": f.symptom,
        })
    return nudges
