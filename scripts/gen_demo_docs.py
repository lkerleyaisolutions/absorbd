"""Generate realistic demo PDF documents for DEMO01 (UC patient).

Creates 2 sample files for each upload category so the document ingestion
pipeline can be exercised during demos without needing real patient records.

Output: demo_docs/  (relative to project root)

Run:  venv/Scripts/python.exe scripts/gen_demo_docs.py
"""

from __future__ import annotations

from pathlib import Path
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
from fpdf import FPDF

OUT = Path(__file__).resolve().parent.parent / "demo_docs"
OUT.mkdir(exist_ok=True)


def pdf(title: str) -> FPDF:
    p = FPDF()
    p.add_page()
    p.set_margins(20, 20, 20)
    p.set_font("Helvetica", "B", 16)
    p.cell(0, 10, title, ln=True)
    p.set_font("Helvetica", "", 10)
    p.set_text_color(100, 100, 100)
    p.cell(0, 6, "GI Associates of Boston  |  Dr. Elena Hartley, MD", ln=True)
    p.cell(0, 6, "Patient: Jane Doe  |  DOB: 1988-03-14  |  MRN: 00142837", ln=True)
    p.ln(4)
    p.set_draw_color(200, 200, 200)
    p.line(20, p.get_y(), 190, p.get_y())
    p.ln(4)
    p.set_text_color(0, 0, 0)
    p.set_font("Helvetica", "", 11)
    return p


def section(p: FPDF, heading: str) -> None:
    p.set_font("Helvetica", "B", 11)
    p.set_fill_color(240, 240, 240)
    p.cell(0, 7, heading, ln=True, fill=True)
    p.set_font("Helvetica", "", 11)
    p.ln(1)


def lines(p: FPDF, *rows: str) -> None:
    for row in rows:
        p.set_x(p.l_margin)
        p.multi_cell(p.epw, 6, row)
    p.ln(2)


# ── 1. Lab Results ────────────────────────────────────────────────────────────

def lab_results_1():
    p = pdf("Laboratory Report -CBC & Metabolic Panel")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Collected: 2026-05-18   Resulted: 2026-05-19   Ordering provider: Dr. Elena Hartley")
    section(p, "COMPLETE BLOOD COUNT")
    rows = [
        ("WBC",         "6.2",  "x10^9/L",  "4.0-11.0",   "NORMAL"),
        ("RBC",         "3.85", "x10^12/L", "3.80-5.10",  "NORMAL"),
        ("Hemoglobin",  "10.2", "g/dL",     "12.0-16.0",  "LOW *"),
        ("Hematocrit",  "31.4", "%",         "36-46",      "LOW *"),
        ("MCV",         "74",   "fL",        "80-100",     "LOW *"),
        ("Platelets",   "412",  "x10^9/L",  "150-400",    "HIGH *"),
    ]
    p.set_font("Courier", "B", 9)
    p.cell(55, 6, "TEST", border="B")
    p.cell(25, 6, "RESULT", border="B")
    p.cell(25, 6, "UNIT", border="B")
    p.cell(40, 6, "REFERENCE", border="B")
    p.cell(0,  6, "FLAG", border="B", ln=True)
    p.set_font("Courier", "", 9)
    for r in rows:
        flag_color = (200, 0, 0) if "*" in r[4] else (0, 0, 0)
        p.set_text_color(*flag_color)
        p.cell(55, 6, r[0])
        p.cell(25, 6, r[1])
        p.cell(25, 6, r[2])
        p.cell(40, 6, r[3])
        p.cell(0,  6, r[4], ln=True)
        p.set_text_color(0, 0, 0)
    p.ln(4)
    section(p, "IRON STUDIES & INFLAMMATORY MARKERS")
    rows2 = [
        ("Ferritin",            "6",    "ng/mL",  "20-250",   "LOW *"),
        ("Serum Iron",          "38",   "ug/dL",  "60-170",   "LOW *"),
        ("TIBC",                "498",  "ug/dL",  "250-370",  "HIGH *"),
        ("Transferrin Sat.",    "8",    "%",       "20-50",    "LOW *"),
        ("CRP (hs)",            "24.1", "mg/L",   "0.0-5.0",  "HIGH *"),
        ("ESR",                 "68",   "mm/hr",  "0-20",     "HIGH *"),
        ("Albumin",             "3.2",  "g/dL",   "3.5-5.0",  "LOW *"),
    ]
    p.set_font("Courier", "B", 9)
    p.cell(55, 6, "TEST", border="B"); p.cell(25, 6, "RESULT", border="B")
    p.cell(25, 6, "UNIT", border="B"); p.cell(40, 6, "REFERENCE", border="B")
    p.cell(0,  6, "FLAG", border="B", ln=True)
    p.set_font("Courier", "", 9)
    for r in rows2:
        flag_color = (200, 0, 0) if "*" in r[4] else (0, 0, 0)
        p.set_text_color(*flag_color)
        p.cell(55, 6, r[0]); p.cell(25, 6, r[1]); p.cell(25, 6, r[2])
        p.cell(40, 6, r[3]); p.cell(0, 6, r[4], ln=True)
        p.set_text_color(0, 0, 0)
    p.ln(4)
    lines(p, "* Flagged values outside reference range. Clinical correlation recommended.")
    p.output(str(OUT / "lab_results_CBC_metabolic_2026-05.pdf"))
    print("  lab_results_CBC_metabolic_2026-05.pdf")


def lab_results_2():
    p = pdf("Laboratory Report -Micronutrient & Vitamin Panel")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Collected: 2026-04-03   Resulted: 2026-04-04   Ordering provider: Dr. Elena Hartley")
    section(p, "VITAMIN & MICRONUTRIENT PANEL")
    rows = [
        ("Vitamin D 25-OH",          "18",  "ng/mL",  "30-100",    "LOW *"),
        ("Vitamin B12",              "312", "pg/mL",  "200-900",   "NORMAL"),
        ("Folate (serum)",           "4.1", "ng/mL",  "3.0-17.0",  "NORMAL"),
        ("Zinc",                     "52",  "mcg/dL", "60-130",    "LOW *"),
        ("Magnesium",                "1.8", "mg/dL",  "1.7-2.4",   "NORMAL"),
        ("Vitamin A (retinol)",      "28",  "mcg/dL", "20-60",     "NORMAL"),
        ("Vitamin K1",               "0.9", "ng/mL",  "0.1-2.2",   "NORMAL"),
        ("Calprotectin (fecal)",     "890", "mcg/g",  "<50",       "HIGH *"),
        ("Lactoferrin (fecal)",      "12.4","ug/mL",  "<7.25",     "HIGH *"),
    ]
    p.set_font("Courier", "B", 9)
    p.cell(60, 6, "TEST", border="B"); p.cell(22, 6, "RESULT", border="B")
    p.cell(25, 6, "UNIT", border="B"); p.cell(38, 6, "REFERENCE", border="B")
    p.cell(0,  6, "FLAG", border="B", ln=True)
    p.set_font("Courier", "", 9)
    for r in rows:
        flag_color = (200, 0, 0) if "*" in r[4] else (0, 0, 0)
        p.set_text_color(*flag_color)
        p.cell(60, 6, r[0]); p.cell(22, 6, r[1]); p.cell(25, 6, r[2])
        p.cell(38, 6, r[3]); p.cell(0, 6, r[4], ln=True)
        p.set_text_color(0, 0, 0)
    p.ln(4)
    lines(p,
        "Clinical Note: Low Vitamin D and Zinc consistent with active UC with malabsorption.",
        "Elevated fecal calprotectin confirms active intestinal inflammation.",
        "Follow-up recommended in 8 weeks post-treatment adjustment.",
        "* Flagged values outside reference range.")
    p.output(str(OUT / "lab_results_micronutrient_2026-04.pdf"))
    print("  lab_results_micronutrient_2026-04.pdf")


# ── 2. Colonoscopy Report ─────────────────────────────────────────────────────

def colonoscopy_1():
    p = pdf("Colonoscopy Procedure Report")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Procedure date: 2026-04-22   Endoscopist: Dr. Elena Hartley, MD")
    section(p, "INDICATION")
    lines(p, "Known ulcerative colitis with worsening symptoms over 6 weeks. Bloody diarrhea 5-6x/day. "
             "Evaluate disease extent and severity for treatment escalation.")
    section(p, "FINDINGS")
    lines(p,
        "Extent of disease: Left-sided colitis (E2, Montreal Classification)",
        "Mayo Endoscopic Score: 3 (severe -spontaneous bleeding, deep ulceration)",
        "",
        "Rectum: Severe erythema, friability, continuous ulceration with contact bleeding. "
        "Pseudopolyps noted. No normal mucosal pattern visible.",
        "",
        "Sigmoid colon: Moderate-severe inflammation. Granular mucosa, loss of vascular pattern, "
        "multiple shallow ulcerations 3-8mm.",
        "",
        "Descending colon: Mild-moderate inflammation at junction. Transition zone at 55cm.",
        "",
        "Transverse, ascending colon, cecum, terminal ileum: Normal appearance. No skip lesions.")
    section(p, "BIOPSIES")
    lines(p,
        "4 biopsies taken from rectum (active inflammation, cryptitis, crypt abscesses).",
        "2 biopsies from sigmoid (active chronic inflammation).",
        "2 biopsies from descending colon junction (transition zone).",
        "Pathology pending -see separate pathology report.")
    section(p, "IMPRESSION & PLAN")
    lines(p,
        "Active moderate-to-severe left-sided ulcerative colitis (Mayo 3).",
        "Current mesalamine monotherapy inadequate. Consider biologic therapy.",
        "Prednisone bridge 40mg/day with planned taper.",
        "Repeat colonoscopy in 12 months or sooner if symptoms worsen.")
    p.output(str(OUT / "colonoscopy_report_2026-04.pdf"))
    print("  colonoscopy_report_2026-04.pdf")


def colonoscopy_2():
    p = pdf("Colonoscopy Procedure Report -Follow-up")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Procedure date: 2025-10-11   Endoscopist: Dr. Elena Hartley, MD")
    section(p, "INDICATION")
    lines(p, "Annual surveillance colonoscopy. Patient with 7-year history of ulcerative colitis, "
             "previously in clinical remission on mesalamine 2.4g/day.")
    section(p, "FINDINGS")
    lines(p,
        "Extent of disease: Left-sided colitis (E2)",
        "Mayo Endoscopic Score: 1 (mild -decreased vascular pattern, mild friability)",
        "",
        "Rectum: Mild erythema, slightly granular mucosa. Vascular pattern partially obscured. "
        "No ulceration or spontaneous bleeding.",
        "",
        "Sigmoid/descending colon: Near-normal with mild residual erythema at sigmoid. "
        "Pseudopolyps from prior disease, no active ulceration.",
        "",
        "Remainder of colon and terminal ileum: Normal. No dysplasia-suspicious lesions.")
    section(p, "IMPRESSION & PLAN")
    lines(p,
        "Mild endoscopic activity (remission vs low-grade active disease).",
        "Continue mesalamine 2.4g/day. No escalation needed at this time.",
        "Next surveillance colonoscopy in 12 months.")
    p.output(str(OUT / "colonoscopy_report_surveillance_2025-10.pdf"))
    print("  colonoscopy_report_surveillance_2025-10.pdf")


# ── 3. Clinical Notes ─────────────────────────────────────────────────────────

def clinical_notes_1():
    p = pdf("Clinic Visit Note -Gastroenterology")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Visit date: 2026-05-20   Provider: Dr. Elena Hartley, MD   Type: Follow-up")
    section(p, "CHIEF COMPLAINT")
    lines(p, "Worsening abdominal cramping, urgency, and bloody stools x 3 weeks despite mesalamine.")
    section(p, "HISTORY OF PRESENT ILLNESS")
    lines(p,
        "Jane is a 38-year-old woman with a 7-year history of left-sided UC (E2) who presents "
        "with a moderate flare. She reports 5-7 loose to watery stools per day with bright red "
        "blood and mucus. Urgency is severe, waking her at night. Abdominal cramping rated 6/10. "
        "Fatigue is marked -she has missed 3 days of work. No fever. No extra-intestinal manifestations.",
        "",
        "Current medications: Mesalamine (Lialda) 2.4g daily -reports adherence. "
        "No recent NSAID or antibiotic use. No recent travel. No sick contacts.")
    section(p, "ASSESSMENT & PLAN")
    lines(p,
        "1. Moderate-severe UC flare -starting prednisone 40mg/day with 5mg/week taper.",
        "2. Adding azathioprine 100mg/day for steroid-sparing; check TPMT before start.",
        "3. Iron deficiency anemia (Ferritin 6, Hgb 10.2) -start ferrous sulfate 325mg TID.",
        "4. Vitamin D insufficiency (18 ng/mL) -cholecalciferol 2000 IU daily.",
        "5. Nutrition referral placed. Gluten-free, low-fiber diet during active flare.",
        "6. Follow-up in 2 weeks or sooner if bleeding worsens.",
        "7. Colonoscopy scheduled to assess mucosal healing.")
    p.output(str(OUT / "clinical_notes_visit_2026-05.pdf"))
    print("  clinical_notes_visit_2026-05.pdf")


def clinical_notes_2():
    p = pdf("Clinic Visit Note -Gastroenterology")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Visit date: 2026-03-08   Provider: Dr. Elena Hartley, MD   Type: Routine follow-up")
    section(p, "SUBJECTIVE")
    lines(p,
        "Patient reports overall stable symptoms. 2-3 formed stools/day, no blood x 6 weeks. "
        "Fatigue improving. Working full time. Tolerating mesalamine without GI side effects. "
        "Mild cramping 1-2x/week, self-limiting. Stress level elevated due to work.")
    section(p, "OBJECTIVE")
    lines(p, "BP 118/74, HR 72, Weight 62 kg (stable). Abdomen soft, mild LLQ tenderness on "
             "deep palpation. No peritoneal signs.")
    section(p, "ASSESSMENT & PLAN")
    lines(p,
        "UC in clinical remission -continue mesalamine 2.4g/day.",
        "Repeat labs in 8 weeks: CBC, CMP, CRP, ferritin, Vitamin D.",
        "Counsel on stress management -correlation noted between stress spikes and symptom exacerbation.",
        "Continue gluten-free diet. Encouraged to increase soluble fiber tolerance as tolerated.",
        "RTC 3 months.")
    p.output(str(OUT / "clinical_notes_visit_2026-03.pdf"))
    print("  clinical_notes_visit_2026-03.pdf")


# ── 4. Prescription ───────────────────────────────────────────────────────────

def prescription_1():
    p = pdf("Prescription -Outpatient")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Date: 2026-05-20   DEA: AC1234563   NPI: 1234567890")
    p.ln(2)
    section(p, "MEDICATIONS PRESCRIBED")
    scripts = [
        ("Prednisone 10mg tablets",
         "Take 4 tablets (40mg) by mouth once daily with food. "
         "Taper by 5mg each week as directed. Do not stop abruptly.",
         "#140 tablets", "1 refill"),
        ("Azathioprine (Imuran) 50mg tablets",
         "Take 2 tablets (100mg) by mouth once daily with food.",
         "#60 tablets", "3 refills"),
        ("Ferrous sulfate 325mg tablets",
         "Take 1 tablet by mouth three times daily between meals. "
         "Take with vitamin C to enhance absorption. May cause dark stools.",
         "#90 tablets", "3 refills"),
        ("Cholecalciferol (Vitamin D3) 2000 IU softgels",
         "Take 1 softgel by mouth once daily with largest meal.",
         "#90 softgels", "3 refills"),
    ]
    for name, sig, qty, refill in scripts:
        p.set_font("Helvetica", "B", 11)
        p.cell(0, 7, name, ln=True)
        p.set_font("Helvetica", "", 10)
        p.multi_cell(0, 6, f"Sig: {sig}")
        p.cell(80, 6, f"Quantity: {qty}")
        p.cell(0, 6, f"Refills: {refill}", ln=True)
        p.ln(3)
    lines(p,
        "Prescriber signature: Dr. Elena Hartley, MD",
        "Substitution permitted unless otherwise noted.")
    p.output(str(OUT / "prescription_2026-05.pdf"))
    print("  prescription_2026-05.pdf")


def prescription_2():
    p = pdf("Prescription -Outpatient")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Date: 2025-12-01   DEA: AC1234563   NPI: 1234567890")
    p.ln(2)
    section(p, "MEDICATIONS PRESCRIBED")
    scripts = [
        ("Mesalamine DR (Lialda) 1.2g delayed-release tablets",
         "Take 2 tablets (2.4g) by mouth once daily with food.",
         "#60 tablets", "6 refills"),
        ("Mesalamine enema 4g/60mL",
         "Instill 1 enema rectally each night at bedtime. Retain for at least 8 hours.",
         "#28 units", "2 refills"),
    ]
    for name, sig, qty, refill in scripts:
        p.set_font("Helvetica", "B", 11)
        p.cell(0, 7, name, ln=True)
        p.set_font("Helvetica", "", 10)
        p.multi_cell(0, 6, f"Sig: {sig}")
        p.cell(80, 6, f"Quantity: {qty}")
        p.cell(0, 6, f"Refills: {refill}", ln=True)
        p.ln(3)
    lines(p,
        "Prescriber signature: Dr. Elena Hartley, MD",
        "Brand Medically Necessary: No")
    p.output(str(OUT / "prescription_maintenance_2025-12.pdf"))
    print("  prescription_maintenance_2025-12.pdf")


# ── 5. Pathology Report ───────────────────────────────────────────────────────

def pathology_1():
    p = pdf("Surgical Pathology Report")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Accession: SP-2026-04837   Received: 2026-04-23   Reported: 2026-04-25")
    lines(p, "Pathologist: Dr. M. Patel, MD   Clinical: Active UC, rule out dysplasia")
    section(p, "SPECIMENS SUBMITTED")
    lines(p,
        "A: Rectal biopsy x4",
        "B: Sigmoid biopsy x2",
        "C: Descending colon junction biopsy x2")
    section(p, "MICROSCOPIC DESCRIPTION")
    lines(p,
        "A (Rectum): Colonic mucosa with marked active chronic inflammation. Cryptitis present "
        "with multiple crypt abscesses. Crypt architectural distortion, branching, and shortening "
        "noted. Basal plasmacytosis. Goblet cell depletion. No granulomas. No dysplasia identified.",
        "",
        "B (Sigmoid): Colonic mucosa with moderate active chronic inflammation. Focal cryptitis. "
        "Mild crypt distortion. No granulomas. No dysplasia.",
        "",
        "C (Descending junction): Colonic mucosa with mild chronic inactive inflammation. "
        "Minimal architectural change. No active cryptitis. No dysplasia.")
    section(p, "DIAGNOSIS")
    lines(p,
        "A: Active chronic colitis with crypt abscesses, consistent with active ulcerative colitis.",
        "B: Chronic active colitis, moderate, consistent with ulcerative colitis.",
        "C: Chronic inactive colitis, mild -transition zone.")
    lines(p, "No dysplasia identified in any specimen. No features of Crohn's disease.")
    p.output(str(OUT / "pathology_report_biopsies_2026-04.pdf"))
    print("  pathology_report_biopsies_2026-04.pdf")


def pathology_2():
    p = pdf("Surgical Pathology Report")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Accession: SP-2025-09214   Received: 2025-10-12   Reported: 2025-10-14")
    lines(p, "Pathologist: Dr. M. Patel, MD   Clinical: Surveillance colonoscopy, UC history")
    section(p, "SPECIMENS SUBMITTED")
    lines(p,
        "A: Random colon biopsies x4 (surveillance protocol)",
        "B: Rectal biopsy x2")
    section(p, "DIAGNOSIS")
    lines(p,
        "A: Colonic mucosa with mild chronic inactive colitis. Mild crypt architectural distortion. "
        "No active cryptitis. No granulomas. NO DYSPLASIA IDENTIFIED.",
        "",
        "B: Rectal mucosa with mild chronic inactive colitis. No active inflammation. "
        "Mild basal plasmacytosis. NO DYSPLASIA IDENTIFIED.",
        "",
        "Overall: Low-grade chronic changes consistent with quiescent ulcerative colitis. "
        "No evidence of dysplasia or malignancy.")
    p.output(str(OUT / "pathology_report_surveillance_2025-10.pdf"))
    print("  pathology_report_surveillance_2025-10.pdf")


# ── 6. Imaging Report (MRI/CT) ────────────────────────────────────────────────

def imaging_1():
    p = pdf("MRI Pelvis with Contrast -Radiology Report")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Exam date: 2026-04-20   Radiologist: Dr. K. Singh, MD   Accession: MR-2026-03841")
    lines(p, "Clinical indication: Active ulcerative colitis, rule out perianal Crohn's, abscess")
    section(p, "TECHNIQUE")
    lines(p, "MRI pelvis with and without IV gadolinium contrast. Multiplanar T1, T2, and DWI sequences.")
    section(p, "FINDINGS")
    lines(p,
        "Colon: Mural thickening of the rectum and sigmoid colon up to 8mm. Increased T2 signal "
        "within the bowel wall consistent with edema and active inflammation. Mucosal enhancement "
        "pattern on post-contrast imaging confirms active colitis. No skip lesions. "
        "No transmural involvement.",
        "",
        "Perirectal region: No fistula tracts, abscesses, or sinus tracts identified. "
        "Mesorectal fat stranding minimal. No lymphadenopathy exceeding 10mm.",
        "",
        "Small bowel: Unremarkable. No terminal ileal thickening.",
        "",
        "Other structures: Uterus and ovaries unremarkable. Bladder normal. No free fluid.")
    section(p, "IMPRESSION")
    lines(p,
        "1. Active proctosigmoiditis consistent with left-sided ulcerative colitis (E2).",
        "2. No perianal fistula, abscess, or features of Crohn's disease.",
        "3. No evidence of toxic megacolon or perforation.")
    p.output(str(OUT / "imaging_MRI_pelvis_2026-04.pdf"))
    print("  imaging_MRI_pelvis_2026-04.pdf")


def imaging_2():
    p = pdf("CT Abdomen & Pelvis with Contrast -Radiology Report")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Exam date: 2025-09-05   Radiologist: Dr. K. Singh, MD   Accession: CT-2025-07293")
    lines(p, "Clinical indication: Acute abdominal pain, known UC -rule out obstruction or perforation")
    section(p, "FINDINGS")
    lines(p,
        "Colon: Wall thickening in the rectosigmoid region (6-7mm). Mucosal hyperenhancement. "
        "No pneumoperitoneum. No obstruction. Colonic haustra preserved.",
        "",
        "Small bowel: No dilation or obstruction. No wall thickening.",
        "",
        "Liver/biliary: Liver homogeneous, no focal lesion. Gallbladder unremarkable. "
        "No biliary dilation. No PSC features.",
        "",
        "Solid organs: Spleen, pancreas, adrenals, kidneys unremarkable.",
        "",
        "No free air, free fluid, or lymphadenopathy.")
    section(p, "IMPRESSION")
    lines(p,
        "1. Rectosigmoid wall thickening consistent with known active UC. No acute complication.",
        "2. No obstruction, perforation, or abscess.",
        "3. No features of extraintestinal manifestation on this exam.")
    p.output(str(OUT / "imaging_CT_abdomen_2025-09.pdf"))
    print("  imaging_CT_abdomen_2025-09.pdf")


# ── 7. Infusion Record ────────────────────────────────────────────────────────

def infusion_1():
    p = pdf("Infusion Center Record -Iron Infusion")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Infusion date: 2026-06-02   Location: GI Associates Infusion Suite, Boston")
    lines(p, "Nurse: RN Lisa Morales   Supervising MD: Dr. Elena Hartley")
    section(p, "MEDICATION ADMINISTERED")
    lines(p,
        "Drug: Ferric carboxymaltose (Injectafer) 750mg IV",
        "Diluent: 0.9% NaCl 250mL",
        "Route: Intravenous, right antecubital",
        "Rate: 100mL/hr x 2.5 hours",
        "Indication: Iron deficiency anemia (Ferritin 6 ng/mL, Hgb 10.2 g/dL) secondary to "
        "active UC with malabsorption. Oral iron not tolerated (GI cramping).")
    section(p, "PRE-INFUSION ASSESSMENT")
    lines(p,
        "BP: 122/76   HR: 80   SpO2: 98%   Temp: 98.6F",
        "IV access: 20G PIV right AC, patent, flushes well.",
        "Allergies reviewed: NKDA. Consent signed.",
        "Pre-medications: None required per protocol.")
    section(p, "INFUSION COURSE")
    lines(p,
        "Infusion started 09:15. Test dose monitored x 15 min -no reaction.",
        "Full rate initiated 09:30. Patient tolerated infusion without adverse events.",
        "Vital signs stable throughout. No flushing, urticaria, or hypotension.",
        "Infusion completed 11:45.")
    section(p, "DISCHARGE")
    lines(p,
        "Patient discharged ambulatory in stable condition.",
        "Instructions: May resume normal activities. Monitor for delayed hypophosphatemia.",
        "Follow-up labs (ferritin, CBC) in 4-6 weeks.")
    p.output(str(OUT / "infusion_record_iron_2026-06.pdf"))
    print("  infusion_record_iron_2026-06.pdf")


def infusion_2():
    p = pdf("Infusion Center Record -Hydrocortisone/IV Steroids")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Infusion date: 2026-04-28   Location: GI Associates Infusion Suite, Boston")
    lines(p, "Nurse: RN Tom Bradley   Supervising MD: Dr. Elena Hartley")
    section(p, "MEDICATION ADMINISTERED")
    lines(p,
        "Drug: Hydrocortisone sodium succinate 300mg IV",
        "Diluent: 0.9% NaCl 100mL",
        "Route: Intravenous, left antecubital",
        "Rate: Over 30 minutes",
        "Indication: Moderate-severe UC flare, insufficient response to oral prednisone.")
    section(p, "INFUSION COURSE & RESPONSE")
    lines(p,
        "Patient reports mild improvement in urgency by end of infusion.",
        "No adverse events. Vital signs stable throughout.",
        "Transitioning to oral prednisone 40mg/day as outpatient.")
    p.output(str(OUT / "infusion_record_steroids_2026-04.pdf"))
    print("  infusion_record_steroids_2026-04.pdf")


# ── 8. Dietitian Notes ────────────────────────────────────────────────────────

def dietitian_1():
    p = pdf("Dietitian Consultation Note")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Visit date: 2026-05-28   RD: Melissa Grant, RD, LD   Referral from: Dr. Elena Hartley")
    section(p, "REASON FOR REFERRAL")
    lines(p, "Active UC flare with iron deficiency anemia, low vitamin D, weight loss risk. "
             "Nutritional optimization during steroid taper.")
    section(p, "DIETARY ASSESSMENT")
    lines(p,
        "Current diet: Self-described as gluten-free due to symptom sensitivity. Avoiding "
        "raw vegetables, seeds, nuts, dairy. Predominantly rice, chicken, bananas, white bread.",
        "",
        "24-hr recall (estimated):",
        "  Calories: ~1,400 kcal (goal 1,900-2,100)",
        "  Protein: ~55g (goal 80-90g)",
        "  Iron: ~6mg (goal 18mg for premenopausal women, 27mg if deficient)",
        "  Vitamin D: ~150 IU (goal 2,000 IU with supplementation)",
        "  Fiber: ~8g (low-fiber diet appropriate during active flare)")
    section(p, "RECOMMENDATIONS")
    lines(p,
        "1. PROTEIN: Add soft-cooked eggs, canned fish (salmon/tuna), smooth nut butters "
        "(tolerated), Greek yogurt if dairy tolerated -target 25-30g per meal.",
        "",
        "2. IRON: Cook in cast iron when possible. Pair iron-rich foods with vitamin C sources "
        "(orange juice, kiwi, bell peppers). Avoid tea/coffee within 1 hour of iron-rich meals. "
        "Iron supplement (ferrous sulfate 325mg) as prescribed by Dr. Elena Hartley.",
        "",
        "3. VITAMIN D: 2000 IU supplement daily with largest meal. Salmon 2x/week if tolerated.",
        "",
        "4. CALORIES: Add calorie-dense, low-residue snacks: avocado, olive oil drizzle on rice, "
        "nut butter on white toast, protein shakes (Ensure or Boost) between meals.",
        "",
        "5. AVOID DURING FLARE: raw brassicas, legumes, high-fructose corn syrup, alcohol, "
        "carbonated beverages, excess caffeine.",
        "",
        "6. REINTRODUCTION PLAN: As flare resolves, gradually reintroduce cooked vegetables "
        "starting with zucchini, carrots, and peeled sweet potato.")
    section(p, "FOLLOW-UP")
    lines(p, "RTC in 4 weeks. Food diary requested. Monitor weight weekly.")
    p.output(str(OUT / "dietitian_notes_consultation_2026-05.pdf"))
    print("  dietitian_notes_consultation_2026-05.pdf")


def dietitian_2():
    p = pdf("Dietitian Follow-up Note")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Visit date: 2026-06-04   RD: Melissa Grant, RD, LD")
    section(p, "INTERVAL HISTORY")
    lines(p,
        "Patient reports improved oral intake since last visit. Tolerating protein shakes. "
        "Weight stable at 62 kg. Iron supplement causing mild constipation -advised to take "
        "with prune juice and increase water intake.",
        "",
        "Added salmon 1x/week. Tolerating Greek yogurt (1/2 cup/day) without worsening symptoms.")
    section(p, "CURRENT NUTRITIONAL STATUS")
    lines(p,
        "Calories: ~1,750 kcal/day (improving toward goal)",
        "Protein: ~70g/day (improving, target 85g)",
        "Adherent to gluten-free diet. Low-fiber protocol maintained.")
    section(p, "UPDATED RECOMMENDATIONS")
    lines(p,
        "Continue current plan. Add 1 Ensure Plus per day to close calorie gap.",
        "Increase Greek yogurt to 1 cup/day -good protein and calcium source.",
        "Zinc-rich foods: add pumpkin seeds (1 tbsp/day, well-chewed or ground) as tolerated.",
        "Follow-up in 6 weeks or after next labs.")
    p.output(str(OUT / "dietitian_notes_followup_2026-06.pdf"))
    print("  dietitian_notes_followup_2026-06.pdf")


# ── 9. Operative Report ───────────────────────────────────────────────────────

def operative_1():
    p = pdf("Operative Report")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Date of procedure: 2022-03-14   Surgeon: Dr. R. Hoffman, MD, FACS")
    lines(p, "Anesthesia: General   Duration: 45 min   EBL: 20mL")
    section(p, "PREOPERATIVE DIAGNOSIS")
    lines(p, "Symptomatic hemorrhoids and anal fissure, likely exacerbated by chronic diarrhea from UC.")
    section(p, "PROCEDURE PERFORMED")
    lines(p, "Hemorrhoidectomy (Ferguson technique) x2 columns, lateral internal sphincterotomy.")
    section(p, "OPERATIVE DETAILS")
    lines(p,
        "Patient placed in prone jackknife position under general anesthesia. Perineum prepped "
        "and draped in sterile fashion. Digital rectal exam performed -no masses. Anoscopy "
        "confirmed grade III internal hemorrhoids at 3 and 7 o'clock. Chronic posterior fissure noted.",
        "",
        "Hemorrhoidectomy: Ferguson (closed) technique performed at 3 and 7 o'clock positions. "
        "Hemorrhoidal tissue excised to dentate line. Wounds closed with 3-0 chromic suture.",
        "",
        "Sphincterotomy: Lateral internal sphincterotomy performed at 9 o'clock. "
        "Fissure margins freshened. Hemostasis achieved.",
        "",
        "Patient tolerated procedure well. Extubated in OR, transferred to PACU in stable condition.")
    section(p, "POSTOPERATIVE PLAN")
    lines(p,
        "Sitz baths TID, stool softeners, high-fiber diet when UC allows.",
        "Follow-up in 2 weeks. Pathology sent on hemorrhoidal tissue.")
    p.output(str(OUT / "operative_report_hemorrhoidectomy_2022-03.pdf"))
    print("  operative_report_hemorrhoidectomy_2022-03.pdf")


def operative_2():
    p = pdf("Operative Report -Diagnostic Laparoscopy")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Date of procedure: 2020-08-19   Surgeon: Dr. R. Hoffman, MD, FACS")
    lines(p, "Anesthesia: General   Duration: 35 min   EBL: Minimal")
    section(p, "INDICATION")
    lines(p, "Acute pelvic pain, rule out appendicitis vs. IBD-related complication.")
    section(p, "OPERATIVE FINDINGS")
    lines(p,
        "Abdomen entered via Hassan technique at umbilicus. Peritoneal cavity entered without "
        "complication. Systematic survey performed.",
        "",
        "Appendix: Normal appearing, no periappendiceal inflammation.",
        "Small bowel: Normal caliber and appearance throughout.",
        "Colon: Sigmoid and rectum appear thickened with serosal injection, consistent with "
        "known UC. No perforation, abscess, or fistula.",
        "Pelvis: No free fluid. Uterus and adnexa normal.")
    section(p, "CONCLUSION")
    lines(p,
        "Pelvic pain attributable to active UC, not surgical emergency.",
        "No operative intervention required. Medical management continued.",
        "Patient discharged home same day in stable condition.")
    p.output(str(OUT / "operative_report_laparoscopy_2020-08.pdf"))
    print("  operative_report_laparoscopy_2020-08.pdf")


# ── 10. Stool Test Results ────────────────────────────────────────────────────

def stool_1():
    p = pdf("Stool Test Results -Comprehensive Stool Analysis")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Collected: 2026-05-15   Lab: Quest Diagnostics   Ref: STC-2026-448291")
    section(p, "INFLAMMATORY MARKERS")
    rows = [
        ("Fecal Calprotectin",  "890",  "mcg/g",  "<50",    "HIGH *"),
        ("Fecal Lactoferrin",   "12.4", "ug/mL",  "<7.25",  "HIGH *"),
        ("Fecal Occult Blood",  "Positive", "",   "Negative","POSITIVE *"),
    ]
    p.set_font("Courier", "B", 9)
    p.cell(60, 6, "TEST", border="B"); p.cell(28, 6, "RESULT", border="B")
    p.cell(22, 6, "UNIT", border="B"); p.cell(35, 6, "REFERENCE", border="B")
    p.cell(0, 6, "FLAG", border="B", ln=True)
    p.set_font("Courier", "", 9)
    for r in rows:
        flag_color = (200, 0, 0) if "*" in r[4] else (0, 0, 0)
        p.set_text_color(*flag_color)
        p.cell(60, 6, r[0]); p.cell(28, 6, r[1]); p.cell(22, 6, r[2])
        p.cell(35, 6, r[3]); p.cell(0, 6, r[4], ln=True)
        p.set_text_color(0, 0, 0)
    p.ln(3)
    section(p, "MICROBIOLOGY")
    lines(p,
        "C. difficile toxin A/B PCR: NEGATIVE",
        "Enteric pathogens panel (Salmonella, Shigella, Campylobacter, E. coli O157): NEGATIVE",
        "Ova & parasites: NOT DETECTED",
        "Helicobacter pylori antigen: NEGATIVE")
    section(p, "INTERPRETATION")
    lines(p,
        "Markedly elevated calprotectin (890 mcg/g) and lactoferrin confirm active intestinal "
        "inflammation. No infectious etiology identified. Findings consistent with active "
        "ulcerative colitis. Clinical correlation with endoscopy recommended.")
    p.output(str(OUT / "stool_test_2026-05.pdf"))
    print("  stool_test_2026-05.pdf")


def stool_2():
    p = pdf("Stool Test Results -Monitoring Panel")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Collected: 2025-09-28   Lab: Quest Diagnostics   Ref: STC-2025-381047")
    section(p, "INFLAMMATORY MARKERS")
    rows = [
        ("Fecal Calprotectin", "142",  "mcg/g",  "<50",    "HIGH *"),
        ("Fecal Lactoferrin",  "3.1",  "ug/mL",  "<7.25",  "NORMAL"),
        ("Fecal Occult Blood", "Negative", "",   "Negative","NORMAL"),
    ]
    p.set_font("Courier", "B", 9)
    p.cell(60, 6, "TEST", border="B"); p.cell(28, 6, "RESULT", border="B")
    p.cell(22, 6, "UNIT", border="B"); p.cell(35, 6, "REFERENCE", border="B")
    p.cell(0, 6, "FLAG", border="B", ln=True)
    p.set_font("Courier", "", 9)
    for r in rows:
        flag_color = (200, 0, 0) if "*" in r[4] else (0, 0, 0)
        p.set_text_color(*flag_color)
        p.cell(60, 6, r[0]); p.cell(28, 6, r[1]); p.cell(22, 6, r[2])
        p.cell(35, 6, r[3]); p.cell(0, 6, r[4], ln=True)
        p.set_text_color(0, 0, 0)
    p.ln(3)
    section(p, "INTERPRETATION")
    lines(p,
        "Mildly elevated calprotectin (142 mcg/g) with normal lactoferrin suggests low-grade "
        "mucosal inflammation, consistent with quiescent UC or early subclinical activity. "
        "Significant improvement from previous value of 890 mcg/g. Continue current regimen.")
    p.output(str(OUT / "stool_test_monitoring_2025-09.pdf"))
    print("  stool_test_monitoring_2025-09.pdf")


# ── 11. Bone Density Scan (DEXA) ─────────────────────────────────────────────

def dexa_1():
    p = pdf("Bone Density Scan (DXA) Report")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Exam date: 2026-04-10   Radiologist: Dr. A. Torres, MD")
    lines(p, "Indication: UC on chronic corticosteroids, Vitamin D deficiency -baseline DEXA")
    section(p, "RESULTS")
    sites = [
        ("Lumbar spine L1-L4", "0.934", "-1.5", "88%", "Osteopenia"),
        ("Femoral neck (left)", "0.798", "-1.2", "91%", "Low normal"),
        ("Total hip (left)",    "0.862", "-0.9", "86%", "Low normal"),
    ]
    p.set_font("Courier", "B", 9)
    p.cell(52, 6, "SITE", border="B"); p.cell(25, 6, "BMD g/cm2", border="B")
    p.cell(20, 6, "T-score", border="B"); p.cell(20, 6, "% young", border="B")
    p.cell(0, 6, "CLASSIFICATION", border="B", ln=True)
    p.set_font("Courier", "", 9)
    for r in sites:
        color = (180, 90, 0) if "Osteopenia" in r[4] else (0, 0, 0)
        p.set_text_color(*color)
        p.cell(52, 6, r[0]); p.cell(25, 6, r[1]); p.cell(20, 6, r[2])
        p.cell(20, 6, r[3]); p.cell(0, 6, r[4], ln=True)
        p.set_text_color(0, 0, 0)
    p.ln(3)
    section(p, "IMPRESSION")
    lines(p,
        "Osteopenia at the lumbar spine (T-score -1.5). Low normal femoral neck and total hip.",
        "",
        "Risk factors: Chronic corticosteroid use, Vitamin D deficiency (18 ng/mL), active IBD "
        "with malabsorption, low dietary calcium intake.",
        "",
        "Recommendations:",
        "1. Optimize Vitamin D -target serum 25-OH Vitamin D >40 ng/mL.",
        "2. Calcium 1,200mg/day (dietary + supplement). Avoid calcium carbonate with PPI.",
        "3. Weight-bearing exercise as tolerated.",
        "4. Minimize corticosteroid use -transition to steroid-sparing agents.",
        "5. Repeat DEXA in 2 years or after significant treatment change.")
    p.output(str(OUT / "bone_density_DEXA_baseline_2026-04.pdf"))
    print("  bone_density_DEXA_baseline_2026-04.pdf")


def dexa_2():
    p = pdf("Bone Density Scan (DXA) Report -Follow-up")
    p.set_font("Helvetica", "I", 10)
    lines(p, "Exam date: 2024-02-22   Radiologist: Dr. A. Torres, MD")
    lines(p, "Indication: UC on mesalamine, prior osteopenia on DEXA 2022")
    section(p, "RESULTS")
    sites = [
        ("Lumbar spine L1-L4", "0.948", "-1.3", "90%", "Low normal"),
        ("Femoral neck (left)", "0.821", "-1.0", "93%", "Normal"),
        ("Total hip (left)",    "0.883", "-0.7", "88%", "Normal"),
    ]
    p.set_font("Courier", "B", 9)
    p.cell(52, 6, "SITE", border="B"); p.cell(25, 6, "BMD g/cm2", border="B")
    p.cell(20, 6, "T-score", border="B"); p.cell(20, 6, "% young", border="B")
    p.cell(0, 6, "CLASSIFICATION", border="B", ln=True)
    p.set_font("Courier", "", 9)
    for r in sites:
        p.cell(52, 6, r[0]); p.cell(25, 6, r[1]); p.cell(20, 6, r[2])
        p.cell(20, 6, r[3]); p.cell(0, 6, r[4], ln=True)
    p.ln(3)
    section(p, "IMPRESSION")
    lines(p,
        "Stable to mildly improved bone density compared to prior exam (2022). "
        "No longer meeting osteopenia criteria at femoral neck or total hip. "
        "Lumbar spine borderline low normal.",
        "",
        "Continue current management. Maintain Vitamin D supplementation. "
        "Repeat DEXA in 2-3 years.")
    p.output(str(OUT / "bone_density_DEXA_followup_2024-02.pdf"))
    print("  bone_density_DEXA_followup_2024-02.pdf")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Generating demo documents -> {OUT}/\n")
    lab_results_1();    lab_results_2()
    colonoscopy_1();    colonoscopy_2()
    clinical_notes_1(); clinical_notes_2()
    prescription_1();   prescription_2()
    pathology_1();      pathology_2()
    imaging_1();        imaging_2()
    infusion_1();       infusion_2()
    dietitian_1();      dietitian_2()
    operative_1();      operative_2()
    stool_1();          stool_2()
    dexa_1();           dexa_2()
    print(f"\nDone -{len(list(OUT.glob('*.pdf')))} PDFs in {OUT}")
