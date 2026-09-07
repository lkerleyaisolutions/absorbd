r"""Demo: full pipeline through the Protocol Agent (#7).

trio -> synthesis -> protocol. Shows the actionable, cited supplement plan for the
prioritized nutrients.

Run:  venv\Scripts\python.exe agents\demo_protocol.py
"""

from _base import Trace, close_clients
from deficiency_hypothesis import hypothesize
from medication_interaction import analyze as medication_analyze
from dietary_gap import analyze as dietary_analyze
from synthesis import synthesize
from protocol import build_protocol

PROFILE = {
    "condition": "ulcerative colitis",
    "medications": ["prednisone", "mesalamine"],
    "symptoms": ["extreme fatigue", "bone pain or muscle cramps"],
    "dietary_restrictions": ["lactose intolerance (avoids dairy)", "vegan"],
}

TAG = {"RED": "[RED]   ", "YELLOW": "[YELLOW]", "GREEN": "[GREEN] "}


def main() -> None:
    print(f"PATIENT: {PROFILE['condition']} | meds: {', '.join(PROFILE['medications'])}\n")
    trace = Trace(on_event=lambda ev: None)
    try:
        defc = hypothesize(PROFILE, trace=trace)
        meds = medication_analyze(PROFILE, trace=trace)
        diet = dietary_analyze(PROFILE, trace=trace)
        syn = synthesize(meds, defc, diet, trace=trace)

        print("PROTOCOL DRAFTING")
        print("-" * 64)
        ptrace = Trace(on_event=lambda ev: print(f"  [{ev.step}] {ev.detail}"))
        result = build_protocol(syn, PROFILE, trace=ptrace)
    finally:
        close_clients()

    print("\nSUPPLEMENT PROTOCOL\n" + "=" * 64)
    for e in result["protocol"]:
        print(f"{TAG.get(e['priority'], e['priority'])} {e['nutrient']}")
        print(f"    dose:   {e['dose']}")
        if e["form"] and e["form"] != "general":
            print(f"    form:   {e['form']}")
        if e["timing"]:
            print(f"    timing: {e['timing']}")
        print(f"    evidence: {e['evidence_level']}")
        if e["caution"]:
            print(f"    caution: {e['caution']}")
        for s in e["sources"]:
            print(f"    source: {s}")
        print()


if __name__ == "__main__":
    main()
