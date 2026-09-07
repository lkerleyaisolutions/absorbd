r"""Demo: full pipeline through the Safety Agent (#8).

trio -> synthesis -> protocol -> safety. Shows red-flag escalation and grounded
dose-ceiling enforcement over the drafted protocol.

Run:  venv\Scripts\python.exe agents\demo_safety.py
"""

from _base import Trace, close_clients
from deficiency_hypothesis import hypothesize
from medication_interaction import analyze as medication_analyze
from dietary_gap import analyze as dietary_analyze
from synthesis import synthesize
from protocol import build_protocol
from safety import run_safety

# Includes a red-flag symptom (palpitations) to demonstrate escalation.
PROFILE = {
    "condition": "ulcerative colitis",
    "medications": ["prednisone", "mesalamine"],
    "symptoms": ["extreme fatigue", "irregular heartbeat or palpitations"],
    "dietary_restrictions": ["lactose intolerance (avoids dairy)", "vegan"],
}

STATUS_TAG = {
    "ok": "[OK]      ",
    "capped": "[CAPPED]  ",
    "unverified": "[UNVERIFIED]",
    "ul_unknown": "[NO-UL]   ",
    "deferred": "[DEFERRED]",
}


def main() -> None:
    print(f"PATIENT: {PROFILE['condition']} | symptoms: {', '.join(PROFILE['symptoms'])}\n")
    trace = Trace(on_event=lambda ev: None)
    try:
        defc = hypothesize(PROFILE, trace=trace)
        meds = medication_analyze(PROFILE, trace=trace)
        diet = dietary_analyze(PROFILE, trace=trace)
        syn = synthesize(meds, defc, diet, trace=trace)
        proto = build_protocol(syn, PROFILE, trace=trace)

        print("SAFETY CHECKS")
        print("-" * 64)
        strace = Trace(on_event=lambda ev: print(f"  [{ev.step}] {ev.detail}"))
        result = run_safety(proto, PROFILE, trace=strace)
    finally:
        close_clients()

    esc = result["escalation"]
    print("\nESCALATION\n" + "=" * 64)
    print(esc["message"] if esc["urgent"] else "No urgent red flags.")

    print("\nSAFETY-CHECKED PROTOCOL\n" + "=" * 64)
    for e in result["checked_protocol"]:
        print(f"{STATUS_TAG.get(e.get('safety_status'), e.get('safety_status',''))} "
              f"{e['nutrient']}: {e['dose']}")
        if e.get("upper_limit"):
            print(f"    UL: {e['upper_limit']}")
        print(f"    safety: {e.get('safety_note','')}")


if __name__ == "__main__":
    main()
