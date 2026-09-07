"""Brand name -> generic name mapping for IBD medications.

Patients say "Humira", not "adalimumab". The Intake Agent uses this to
normalize whatever the patient types into the generic name that the
Medication Interaction Agent and drug_interactions.json key on.

Keys are lowercase. Match against user input after lowercasing and stripping.
"""

MEDICATION_MAP = {
    # --- Biologics (anti-TNF) ---
    "humira": "adalimumab",
    "hadlima": "adalimumab",
    "amjevita": "adalimumab",
    "hyrimoz": "adalimumab",
    "adalimumab": "adalimumab",
    "remicade": "infliximab",
    "inflectra": "infliximab",
    "renflexis": "infliximab",
    "avsola": "infliximab",
    "infliximab": "infliximab",
    "simponi": "golimumab",
    "golimumab": "golimumab",
    "cimzia": "certolizumab",
    "certolizumab": "certolizumab",

    # --- Biologics (anti-integrin / anti-interleukin) ---
    "entyvio": "vedolizumab",
    "vedolizumab": "vedolizumab",
    "stelara": "ustekinumab",
    "ustekinumab": "ustekinumab",
    "skyrizi": "risankizumab",
    "risankizumab": "risankizumab",
    "omvoh": "mirikizumab",
    "mirikizumab": "mirikizumab",

    # --- Small molecule (JAK / S1P) ---
    "xeljanz": "tofacitinib",
    "tofacitinib": "tofacitinib",
    "rinvoq": "upadacitinib",
    "upadacitinib": "upadacitinib",
    "zeposia": "ozanimod",
    "ozanimod": "ozanimod",
    "velsipity": "etrasimod",
    "etrasimod": "etrasimod",

    # --- Aminosalicylates (5-ASA) ---
    "asacol": "mesalamine",
    "asacol hd": "mesalamine",
    "lialda": "mesalamine",
    "pentasa": "mesalamine",
    "delzicol": "mesalamine",
    "apriso": "mesalamine",
    "rowasa": "mesalamine",
    "canasa": "mesalamine",
    "mesalamine": "mesalamine",
    "mesalazine": "mesalamine",
    "azulfidine": "sulfasalazine",
    "sulfasalazine": "sulfasalazine",
    "dipentum": "olsalazine",
    "olsalazine": "olsalazine",
    "colazal": "balsalazide",
    "balsalazide": "balsalazide",

    # --- Corticosteroids ---
    "prednisone": "prednisone",
    "prednisolone": "prednisone",
    "entocort": "budesonide",
    "entocort ec": "budesonide",
    "uceris": "budesonide",
    "budesonide": "budesonide",
    "medrol": "methylprednisolone",
    "methylprednisolone": "methylprednisolone",

    # --- Immunomodulators ---
    "imuran": "azathioprine",
    "azasan": "azathioprine",
    "azathioprine": "azathioprine",
    "6-mp": "mercaptopurine",
    "6mp": "mercaptopurine",
    "purinethol": "mercaptopurine",
    "purixan": "mercaptopurine",
    "mercaptopurine": "mercaptopurine",
    "trexall": "methotrexate",
    "rasuvo": "methotrexate",
    "otrexup": "methotrexate",
    "methotrexate": "methotrexate",

    # --- Bile acid sequestrant (post-resection diarrhea) ---
    "questran": "cholestyramine",
    "prevalite": "cholestyramine",
    "cholestyramine": "cholestyramine",
}


def normalize_medication(raw: str) -> str | None:
    """Return the generic name for a brand/generic input, or None if unknown.

    Tries exact match first, then substring containment so freeform input
    like "I take Humira 40mg" still resolves to adalimumab.

    Note: returns a SINGLE generic. Freeform input naming two drugs (e.g.
    "Humira and Imuran") resolves only the first match in table order. The
    Intake Agent is responsible for splitting multi-drug input into separate
    calls before normalizing.
    """
    if not raw:
        return None
    cleaned = raw.strip().lower()
    if cleaned in MEDICATION_MAP:
        return MEDICATION_MAP[cleaned]
    for brand, generic in MEDICATION_MAP.items():
        if brand in cleaned:
            return generic
    return None
