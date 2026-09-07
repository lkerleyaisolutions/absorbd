r"""Demo: full reasoning pipeline through the Synthesis Agent (#6).

Runs the parallel trio (deficiency / medication / dietary) then the hybrid
Synthesis Agent: deterministic merge + grounded LLM triage -> RED/YELLOW/GREEN.

Run:  venv\Scripts\python.exe agents\demo_synthesis.py
"""

from _base import Trace, TraceEvent, close_clients
from deficiency_hypothesis import hypothesize
from medication_interaction import analyze as medication_analyze
from dietary_gap import analyze as dietary_analyze
from synthesis import synthesize

PROFILE = {
    "condition": "ulcerative colitis",
    "medications": ["prednisone", "mesalamine"],
    "symptoms": ["extreme fatigue", "bone pain or muscle cramps"],
    "dietary_restrictions": ["lactose intolerance (avoids dairy)", "vegan"],
}

PRIORITY_TAG = {"RED": "[RED]   ", "YELLOW": "[YELLOW]", "GREEN": "[GREEN] "}


def main() -> None:
    print(f"PATIENT: {PROFILE['condition']}")
    print(f"  meds: {', '.join(PROFILE['medications'])} | diet: {', '.join(PROFILE['dietary_restrictions'])}\n")

    trace = Trace(on_event=lambda ev: None)
    try:
        defc = hypothesize(PROFILE, trace=trace)
        meds = medication_analyze(PROFILE, trace=trace)
        diet = dietary_analyze(PROFILE, trace=trace)

        print("SYNTHESIS")
        print("-" * 64)
        syn_trace = Trace(on_event=lambda ev: print(f"  [{ev.step}] {ev.detail}"))
        result = synthesize(meds, defc, diet, trace=syn_trace)
    finally:
        close_clients()

    print("\nPRIORITIZED PROTOCOL TARGETS\n" + "=" * 64)
    for n in result["nutrients"]:
        print(f"{PRIORITY_TAG.get(n['priority'], n['priority'])} {n['nutrient']}  "
              f"(convergence {n['convergence']})")
        print(f"    why: {n['rationale']}")
        origins = ", ".join(f"{o['type']}:{o['origin']}" for o in n["origins"])
        print(f"    implicated by: {origins}")
        for s in n["sources"]:
            print(f"    source: {s}")
        print()


if __name__ == "__main__":
    main()
