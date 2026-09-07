r"""Demo: the parallel reasoning trio (agents 3, 4, 5) on one patient.

Runs Deficiency Hypothesis, Medication Interaction, and Dietary Gap over a single
UC patient profile and prints the consolidated, verified, cited findings — the
exact input the Synthesis Agent (#6) will triage next.

Run:  venv\Scripts\python.exe agents\demo_reasoning_core.py
"""

from _base import Trace, TraceEvent, close_clients
from deficiency_hypothesis import hypothesize
from medication_interaction import analyze as medication_analyze
from dietary_gap import analyze as dietary_analyze

PROFILE = {
    "condition": "ulcerative colitis",
    "medications": ["prednisone", "mesalamine"],
    "symptoms": ["extreme fatigue", "bone pain or muscle cramps"],
    "dietary_restrictions": ["lactose intolerance (avoids dairy)", "vegan"],
}


def main() -> None:
    print(f"PATIENT: {PROFILE['condition']}")
    print(f"  meds: {', '.join(PROFILE['medications'])}")
    print(f"  symptoms: {', '.join(PROFILE['symptoms'])}")
    print(f"  diet: {', '.join(PROFILE['dietary_restrictions'])}\n")

    def on_event(ev: TraceEvent) -> None:
        if ev.step in ("verify", "conclude"):
            print(f"  [{ev.agent}/{ev.step}] {ev.detail}")

    trace = Trace(on_event=on_event)
    print("REASONING (verify + conclude steps)\n" + "-" * 64)
    try:
        defc = hypothesize(PROFILE, trace=trace)
        meds = medication_analyze(PROFILE, trace=trace)
        diet = dietary_analyze(PROFILE, trace=trace)
    finally:
        close_clients()

    print("\nCONSOLIDATED VERIFIED FINDINGS (-> Synthesis Agent input)\n" + "=" * 64)

    def dump(label, blocks, key):
        print(f"\n{label}")
        for b in blocks:
            for f in b["findings"]:
                origin = b.get(key, "")
                print(f"  - {f['nutrient']:12} <= {origin}")
                for s in f.get("sources", []):
                    print(f"      {s}")

    dump("From condition (Deficiency Hypothesis):", defc["results"], "focus")
    dump("From medications (Medication Interaction):", meds["results"], "medication")
    dump("From diet (Dietary Gap):", diet["results"], "restriction")


if __name__ == "__main__":
    main()
