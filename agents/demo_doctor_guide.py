r"""Demo: the FULL 7-agent reasoning pipeline ending in doctor questions.

trio -> synthesis -> protocol -> safety -> doctor guide.
The finale: 3 specific questions the patient brings to their next appointment.

Run:  venv\Scripts\python.exe agents\demo_doctor_guide.py
"""

from _base import Trace, close_clients
from deficiency_hypothesis import hypothesize
from medication_interaction import analyze as medication_analyze
from dietary_gap import analyze as dietary_analyze
from synthesis import synthesize
from protocol import build_protocol
from safety import run_safety
from doctor_guide import run_doctor_guide

PROFILE = {
    "condition": "ulcerative colitis",
    "medications": ["prednisone", "mesalamine"],
    "symptoms": ["extreme fatigue", "bone pain or muscle cramps"],
    "dietary_restrictions": ["lactose intolerance (avoids dairy)", "vegan"],
}


def main() -> None:
    print(f"PATIENT: {PROFILE['condition']}")
    print(f"  meds: {', '.join(PROFILE['medications'])} | diet: {', '.join(PROFILE['dietary_restrictions'])}\n")
    trace = Trace(on_event=lambda ev: None)
    try:
        defc = hypothesize(PROFILE, trace=trace)
        meds = medication_analyze(PROFILE, trace=trace)
        diet = dietary_analyze(PROFILE, trace=trace)
        syn = synthesize(meds, defc, diet, trace=trace)
        proto = build_protocol(syn, PROFILE, trace=trace)
        safety = run_safety(proto, PROFILE, trace=trace)
        guide = run_doctor_guide(syn, safety, PROFILE, trace=trace)
    finally:
        close_clients()

    print("QUESTIONS FOR YOUR NEXT APPOINTMENT")
    print("=" * 64)
    for i, q in enumerate(guide["questions"], 1):
        print(f"{i}. {q.get('question','')}")
        print(f"   why: {q.get('rationale','')}\n")


if __name__ == "__main__":
    main()
