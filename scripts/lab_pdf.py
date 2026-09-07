"""Reusable clinical lab-report PDF generator for demo patients.

Renders a clean, realistic lab report with fpdf2 (core fonts, latin-1 only).
The public function `write_lab_report_pdf` is importable; running this module
directly produces a sample PDF to a temp path for a quick self-test.

Encoding note: fpdf2 core fonts are latin-1 only. Every string written to the
PDF is sanitized to latin-1 (with replacement) so a stray non-latin-1 char
cannot crash rendering. No em dashes, arrows, or comparison glyphs are used
anywhere. The data already uses "mcg" and "<"/">", which are latin-1 safe.

Run:  venv/Scripts/python.exe scripts/lab_pdf.py
"""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF


def _latin1(text) -> str:
    """Coerce any value to a latin-1 safe string for the core fonts."""
    s = "" if text is None else str(text)
    return s.encode("latin-1", "replace").decode("latin-1")


def title_from_filename(filename) -> str:
    """Derive a human report title from a lab filename, deterministically.

    Strips the .pdf extension and a trailing date token, replaces underscores
    with spaces. Example: "Crohns_Flare_Panel_2026-05.pdf" -> "Crohns Flare Panel".
    """
    name = str(filename or "Laboratory Report")
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    parts = [p for p in name.split("_") if p]
    # Drop a trailing date-like token (digits and hyphens only).
    if parts and all(ch.isdigit() or ch == "-" for ch in parts[-1]):
        parts = parts[:-1]
    title = " ".join(parts).strip()
    return title or "Laboratory Report"


class _LabPDF(FPDF):
    """FPDF subclass with a fixed footer disclaimer on every page."""

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(130, 130, 130)
        disclaimer = (
            "Generated demo document for the Absorbd educational tool. "
            "Not a real clinical laboratory report."
        )
        self.cell(0, 5, _latin1(disclaimer), align="C")
        self.set_text_color(0, 0, 0)


def write_lab_report_pdf(
    out_path,
    *,
    patient_name,
    condition,
    report_title,
    panel,
    lab_date,
    lab_name="Absorbd Clinical Laboratory",
    summary=None,
) -> str:
    """Write a clinical lab report PDF and return its path as a string.

    panel: list of dicts with keys test_name, value, unit, reference_range,
           status, test_date.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = _LabPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(15, 15, 15)
    pdf.add_page()

    epw = pdf.w - pdf.l_margin - pdf.r_margin  # effective page width

    # ── Header band: lab name ────────────────────────────────────────────────
    pdf.set_fill_color(31, 73, 125)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(epw, 11, _latin1("  " + lab_name), align="L", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    # ── Report title ─────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(epw, 8, _latin1(report_title), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)

    # ── Boxed patient/collection info block ──────────────────────────────────
    info_rows = [
        ("Patient", patient_name),
        ("Condition", condition),
        ("Collected", lab_date),
        ("Reported", lab_date),
    ]
    box_top = pdf.get_y()
    pdf.set_draw_color(170, 170, 170)
    pdf.set_line_width(0.3)
    label_w = 30
    pdf.set_font("Helvetica", "", 10)
    for label, value in info_rows:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(label_w, 6, _latin1(label + ":"), new_x="RIGHT", new_y="TOP")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(epw - label_w, 6, _latin1(value), new_x="LMARGIN", new_y="NEXT")
    box_bottom = pdf.get_y()
    pdf.rect(pdf.l_margin, box_top - 1, epw, (box_bottom - box_top) + 2)
    pdf.ln(5)

    # ── Results table ────────────────────────────────────────────────────────
    # Columns: Test | Result | Reference Range | Flag
    c_test = epw * 0.40
    c_result = epw * 0.22
    c_ref = epw * 0.23
    c_flag = epw * 0.15
    row_h = 7

    # Header row
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(225, 232, 240)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(c_test, row_h, _latin1("  Test"), border=1, fill=True)
    pdf.cell(c_result, row_h, _latin1("Result"), border=1, fill=True)
    pdf.cell(c_ref, row_h, _latin1("Reference Range"), border=1, fill=True)
    pdf.cell(c_flag, row_h, _latin1("Flag"), border=1, fill=True, new_x="LMARGIN", new_y="NEXT")

    for i, lv in enumerate(panel):
        test_name = lv.get("test_name", "")
        value = lv.get("value", "")
        unit = lv.get("unit", "") or ""
        ref = lv.get("reference_range", "") or ""
        status = (lv.get("status", "") or "").upper()
        result = (str(value) + " " + unit).strip()

        flagged = status in ("LOW", "HIGH")
        flag_text = status if flagged else ("NORMAL" if status == "NORMAL" else "")

        # Zebra striping for readability.
        if i % 2 == 0:
            pdf.set_fill_color(248, 250, 252)
            fill = True
        else:
            pdf.set_fill_color(255, 255, 255)
            fill = True

        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(c_test, row_h, _latin1("  " + test_name), border="LR", fill=fill)
        pdf.set_font("Courier", "B" if flagged else "", 10)
        pdf.cell(c_result, row_h, _latin1(result), border="LR", fill=fill)
        pdf.set_font("Courier", "", 9)
        pdf.cell(c_ref, row_h, _latin1(ref), border="LR", fill=fill)

        # Flag column, bold and red for HIGH/LOW.
        pdf.set_font("Helvetica", "B" if flagged else "", 10)
        if flagged:
            pdf.set_text_color(192, 32, 32)
        else:
            pdf.set_text_color(110, 110, 110)
        pdf.cell(c_flag, row_h, _latin1(" " + flag_text), border="LR", fill=fill,
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)

    # Bottom border to close the table.
    pdf.cell(epw, 0, "", border="T", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # ── Impression / summary ─────────────────────────────────────────────────
    if summary:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(epw, 7, _latin1("Impression"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(epw, 5.5, _latin1(summary))
        pdf.ln(2)

    pdf.output(str(out_path))
    return str(out_path)


if __name__ == "__main__":
    import tempfile

    sample_panel = [
        {"test_name": "Ferritin", "value": "6", "unit": "ng/mL",
         "reference_range": "20-250", "status": "LOW", "test_date": "2026-05-23"},
        {"test_name": "Hemoglobin", "value": "10.2", "unit": "g/dL",
         "reference_range": "12.0-16.0", "status": "LOW", "test_date": "2026-05-23"},
        {"test_name": "Folate", "value": "4.1", "unit": "ng/mL",
         "reference_range": "3.0-17.0", "status": "NORMAL", "test_date": "2026-05-23"},
        {"test_name": "Calprotectin (fecal)", "value": "890", "unit": "mcg/g",
         "reference_range": "<50", "status": "HIGH", "test_date": "2026-05-23"},
    ]
    tmp = Path(tempfile.gettempdir()) / "absorbd_lab_sample.pdf"
    path = write_lab_report_pdf(
        tmp,
        patient_name="Alex Morgan",
        condition="ulcerative colitis",
        report_title="CBC and Metabolic Panel",
        panel=sample_panel,
        lab_date="2026-05-23",
        summary=(
            "CBC and metabolic panel showing anemia, low ferritin, elevated CRP, "
            "low Vitamin D and Zinc. Findings consistent with active disease."
        ),
    )
    print("Wrote sample lab report to:", path)
