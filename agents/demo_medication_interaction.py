r"""Demo runner for the Medication Interaction Agent.

Shows the agent's visible multi-step reasoning trace, grounded findings with
citations, adversarial verification, and its refusal to fabricate depletions for
drugs the knowledge base has no evidence on.

Run:  venv\Scripts\python.exe agents\demo_medication_interaction.py
"""

from _base import Trace, TraceEvent, close_clients
from medication_interaction import analyze

SAMPLE_PROFILE = {
    "condition": "ulcerative colitis",
    "medications": ["prednisone", "adalimumab", "mesalamine"],
}

STEP_ICON = {
    "plan": "[PLAN]   ",
    "retrieve": "[SEARCH] ",
    "analyze": "[ANALYZE]",
    "verify": "[VERIFY] ",
    "conclude": "[DONE]   ",
}


def main() -> None:
    print(f"Patient: {SAMPLE_PROFILE['condition']}")
    print(f"Medications: {', '.join(SAMPLE_PROFILE['medications'])}\n")

    # live-stream the reasoning trace as it happens
    def on_event(ev: TraceEvent) -> None:
        print(f"  {STEP_ICON.get(ev.step, ev.step)} {ev.detail}")

    trace = Trace(on_event=on_event)
    print("REASONING TRACE")
    print("-" * 64)
    try:
        out = analyze(SAMPLE_PROFILE, trace=trace)
    finally:
        close_clients()

    print("\nVERIFIED FINDINGS")
    print("=" * 64)
    for r in out["results"]:
        print(f"MEDICATION: {r['medication']}")
        findings = r.get("findings", [])
        if not findings:
            print("  No grounded evidence -> no finding asserted (anti-hallucination).")
        for f in findings:
            print(f"  - {f['nutrient']}: {f['effect']}  ({f.get('mechanism','')})")
            if f.get("verified_quote"):
                print(f"    verified: \"{f['verified_quote'][:140]}\"")
            for s in f.get("sources", []):
                print(f"    source: {s}")
        print()


if __name__ == "__main__":
    main()
