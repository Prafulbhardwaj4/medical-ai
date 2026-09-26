import os
import re
import json
import base64
import hashlib
from app.utils.auth import now_ist
from app.config import settings
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
import qrcode
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image
from reportlab.pdfgen import canvas as pdfcanvas
import io

PRESCRIPTIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "prescriptions")
REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "reports")
TOKEN_SLIPS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "token_slips")

def ensure_dir():
    os.makedirs(PRESCRIPTIONS_DIR, exist_ok=True)

def ensure_reports_dir():
    os.makedirs(REPORTS_DIR, exist_ok=True)

def ensure_token_slips_dir():
    os.makedirs(TOKEN_SLIPS_DIR, exist_ok=True)

def cap_sentence(text: str) -> str:
    if not text:
        return text
    import re
    sentences = re.split(r'([.!?]\s+)', text)
    result = []
    for s in sentences:
        if s and s[0].isalpha():
            result.append(s[0].upper() + s[1:])
        else:
            result.append(s)
    return "".join(result)

def _num_to_words_below_1000(n: int) -> str:
    ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
            "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
            "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
    if n == 0:
        return ""
    if n < 20:
        return ones[n]
    if n < 100:
        return (tens[n // 10] + (" " + ones[n % 10] if n % 10 else "")).strip()
    return (ones[n // 100] + " Hundred" + (" " + _num_to_words_below_1000(n % 100) if n % 100 else "")).strip()

def amount_to_words_inr(amount: float) -> str:
    """Converts a rupee amount into words using the Indian numbering system
    (lakh/crore) — the mandatory 'Amount in Words' line on a GST tax invoice."""
    try:
        rupees = int(round(amount or 0))
    except (TypeError, ValueError):
        return ""
    if rupees == 0:
        return "Rupees Zero Only"
    parts = []
    crore, rupees = divmod(rupees, 10000000)
    lakh, rupees = divmod(rupees, 100000)
    thousand, rupees = divmod(rupees, 1000)
    hundred = rupees
    if crore:
        parts.append(_num_to_words_below_1000(crore) + " Crore")
    if lakh:
        parts.append(_num_to_words_below_1000(lakh) + " Lakh")
    if thousand:
        parts.append(_num_to_words_below_1000(thousand) + " Thousand")
    if hundred:
        parts.append(_num_to_words_below_1000(hundred))
    return "Rupees " + " ".join(parts) + " Only"

def _decode_logo_image(logo_base64):
    """Decode a data URI (data:image/...;base64,...) into a small ReportLab Image flowable.
    Returns None if missing or unreadable — logo is optional everywhere it's used."""
    if not logo_base64:
        return None
    try:
        raw = logo_base64.split(",", 1)[1] if "," in logo_base64 else logo_base64
        img_bytes = base64.b64decode(raw)
        img = Image(io.BytesIO(img_bytes))
        max_h = 16 * mm
        ratio = (img.imageWidth / img.imageHeight) if img.imageHeight else 1
        img.drawHeight = max_h
        img.drawWidth = max_h * ratio
        img.hAlign = "CENTER"
        return img
    except Exception:
        return None

def _make_numbered_canvas(header_text: str):
    """Returns a reportlab Canvas subclass bound to `header_text` — a
    compact repeating identity line (hospital + patient/ID + document
    reference) drawn on every page in the top margin, with a "Page X of Y"
    footer (item 0). The two-pass page-buffering is the standard reportlab
    approach for a total page count that isn't known until save() — pass
    this to doc.build(elements, canvasmaker=...); no per-function changes
    to onFirstPage/onLaterPages needed since canvasmaker covers every page
    uniformly, first and later alike."""
    class _NumberedCanvas(pdfcanvas.Canvas):
        def __init__(self, *args, **kwargs):
            pdfcanvas.Canvas.__init__(self, *args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            num_pages = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self._draw_header_footer(num_pages)
                pdfcanvas.Canvas.showPage(self)
            pdfcanvas.Canvas.save(self)

        def _draw_header_footer(self, page_count):
            width, height = A4
            self.saveState()
            self.setFont("Helvetica", 7.5)
            self.setFillColor(colors.grey)
            self.drawString(20*mm, height - 10*mm, (header_text or "")[:130])
            self.drawRightString(width - 20*mm, 10*mm, f"Page {self._pageNumber} of {page_count}")
            self.restoreState()

    return _NumberedCanvas


def build_letterhead(hospital, subtitle=None):
    """Shared header for every PDF: logo (if set) + hospital name + address/city/state
    + phone/GSTIN (only whichever are actually set), optional subtitle line under it."""
    header_style = ParagraphStyle("lh_header", fontSize=18, fontName="Helvetica-Bold", alignment=TA_CENTER, textColor=colors.HexColor("#1a237e"), spaceAfter=8, spaceBefore=2, leading=22)
    sub_style = ParagraphStyle("lh_sub", fontSize=9.5, fontName="Helvetica", alignment=TA_CENTER, textColor=colors.grey, spaceAfter=2, leading=12)

    elements = []

    logo_img = _decode_logo_image(getattr(hospital, "logo_base64", None))
    if logo_img:
        elements.append(logo_img)
        elements.append(Spacer(1, 1.5*mm))

    elements.append(Paragraph(hospital.name, header_style))

    location_bits = []
    if hospital.address:
        location_bits.append(hospital.address)
    city_state = ", ".join([p for p in [hospital.city, hospital.state] if p])
    if city_state:
        location_bits.append(city_state)
    if location_bits:
        elements.append(Paragraph(" | ".join(location_bits), sub_style))

    contact_bits = []
    if getattr(hospital, "phone", None):
        contact_bits.append(f"Ph: {hospital.phone}")
    if hospital.gstin:
        contact_bits.append(f"GSTIN: {hospital.gstin}")
    if contact_bits:
        elements.append(Paragraph(" | ".join(contact_bits), sub_style))

    if subtitle:
        elements.append(Spacer(1, 1.5*mm))
        elements.append(Paragraph(subtitle, sub_style))

    return elements

def generate_token_slip_pdf(checkin, patient, doctor, hospital, nurse_name=None) -> str:
    """The WhatsApp-bound token slip — a real A4 PDF, deliberately NOT the
    80mm receipt format used by receptionist.html's print flow (.receipt-slip).
    This is read on a phone screen, not torn off a thermal printer, so it
    gets the same letterhead treatment as the invoice/prescription PDFs.
    display_token is still THE big number; token_number appears once, small,
    as the internal reference (consistent with the print slip's philosophy).

    TEMP: currently only wired to a manual preview endpoint
    (/patients/checkins/{id}/token-slip-pdf) so it can be checked before
    WhatsApp sending exists. Remove the preview button/endpoint once real
    WhatsApp delivery calls this function directly."""
    ensure_token_slips_dir()
    filepath = os.path.join(TOKEN_SLIPS_DIR, f"token_slip_{checkin.id}.pdf")

    doc = SimpleDocTemplate(
        filepath, pagesize=A4,
        rightMargin=25*mm, leftMargin=25*mm, topMargin=20*mm, bottomMargin=20*mm
    )
    elements = []

    elements.extend(build_letterhead(hospital, subtitle="OPD Token Confirmation"))
    elements.append(Spacer(1, 6*mm))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a237e")))
    elements.append(Spacer(1, 10*mm))

    label_style = ParagraphStyle("tok_label", fontSize=10, fontName="Helvetica", alignment=TA_CENTER, textColor=colors.grey, spaceAfter=2)
    big_style = ParagraphStyle("tok_big", fontSize=48, fontName="Helvetica-Bold", alignment=TA_CENTER, textColor=colors.HexColor("#1a237e"), leading=54)
    ref_style = ParagraphStyle("tok_ref", fontSize=8, fontName="Helvetica", alignment=TA_CENTER, textColor=colors.grey, spaceBefore=2)

    display_value = checkin.display_token if checkin.display_token is not None else checkin.token_number
    elements.append(Paragraph("YOUR TOKEN NUMBER", label_style))
    elements.append(Paragraph(str(display_value), big_style))
    elements.append(Paragraph(f"Ref: {checkin.token_number}", ref_style))
    elements.append(Spacer(1, 10*mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    elements.append(Spacer(1, 6*mm))

    row_label_style = ParagraphStyle("row_label", fontSize=9, fontName="Helvetica-Bold", textColor=colors.HexColor("#334155"))
    row_value_style = ParagraphStyle("row_value", fontSize=10, fontName="Helvetica", textColor=colors.HexColor("#111827"))

    rows = [
        ("Patient", patient.name),
        ("Doctor", f"{doctor.title} {doctor.name}" if doctor else "—"),
        ("Category", checkin.issue_category or "—"),
        ("Date", checkin.visit_date.strftime("%d %b %Y")),
        ("Checked in", checkin.created_at.strftime("%I:%M %p") if checkin.created_at else "—"),
    ]
    if nurse_name:
        rows.append(("Nurse/Assistant", nurse_name))

    table_data = [[Paragraph(f"{lbl}", row_label_style), Paragraph(f"{val}", row_value_style)] for lbl, val in rows]
    info_table = Table(table_data, colWidths=[40*mm, 110*mm])
    info_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3*mm),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 10*mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    elements.append(Spacer(1, 3*mm))

    footer_style = ParagraphStyle("footer", fontSize=8, fontName="Helvetica", alignment=TA_CENTER, textColor=colors.grey)
    elements.append(Paragraph(f"Please keep this for your visit. Generated by MedScribe | {now_ist().strftime('%d %b %Y %H:%M')}", footer_style))

    doc.build(elements)
    return filepath

def generate_prescription_pdf(
    doctor: object,
    patient: object,
    consultation: object,
    token_number: str,
    verify_hash: str = ""
) -> str:
    ensure_dir()

    filename = f"{token_number}.pdf"
    filepath = os.path.join(PRESCRIPTIONS_DIR, filename)

    doc = SimpleDocTemplate(
        filepath,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=15*mm,
        bottomMargin=15*mm
    )

    styles = getSampleStyleSheet()
    elements = []

    # ── Header ──
    header_style = ParagraphStyle("header", fontSize=18, fontName="Helvetica-Bold", alignment=TA_CENTER, textColor=colors.HexColor("#1a237e"))
    sub_style = ParagraphStyle("sub", fontSize=10, fontName="Helvetica", alignment=TA_CENTER, textColor=colors.grey)
    token_style = ParagraphStyle("token", fontSize=11, fontName="Helvetica-Bold", alignment=TA_RIGHT, textColor=colors.HexColor("#1a237e"))

    if doctor.hospital:
        elements.extend(build_letterhead(doctor.hospital))
    else:
        elements.append(Paragraph(doctor.clinic_name, header_style))
    elements.append(Spacer(1, 2*mm))
    elements.append(Paragraph(f"{doctor.title} {doctor.name} | {doctor.specialization}", sub_style))
    reg_text = f" | Reg. No: {doctor.registration_number}" if doctor.registration_number else ""
    elements.append(Paragraph(f"Contact: {doctor.phone}{reg_text}", sub_style))
    elements.append(Spacer(1, 3*mm))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1a237e")))
    elements.append(Spacer(1, 3*mm))

    bg = f" | Blood Group: {patient.blood_group}" if patient.blood_group else ""

    # ── Token + Date ──
    meta_data = [
        [
            Paragraph(f"<b>Patient:</b> {patient.name.title()} | {patient.age}yr | {patient.gender.capitalize()}{bg}", styles["Normal"]),
            Paragraph(f"<b>Token:</b> {token_number}<br/><b>Date:</b> {now_ist().strftime('%d %b %Y')}", token_style)
        ]
    ]
    meta_table = Table(meta_data, colWidths=[95*mm, 75*mm])
    meta_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 2*mm))
    pid_style = ParagraphStyle("pid", fontSize=9, fontName="Helvetica", textColor=colors.HexColor("#334155"))
    elements.append(Paragraph(f"<b>Patient ID:</b> {patient.patient_uid}", pid_style))
    elements.append(Spacer(1, 4*mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    elements.append(Spacer(1, 4*mm))

    # ── Section styles ──
    section_style = ParagraphStyle("section", fontSize=11, fontName="Helvetica-Bold", textColor=colors.HexColor("#1a237e"), spaceAfter=2*mm)
    body_style = ParagraphStyle("body", fontSize=10, fontName="Helvetica", leading=14)

    # ── Chief Complaint ──
    if consultation.chief_complaint:
        elements.append(Paragraph("Chief Complaint / Symptoms", section_style))
        elements.append(Paragraph(cap_sentence(consultation.chief_complaint), body_style))
        elements.append(Spacer(1, 3*mm))

    # ── Vitals ──
    vitals = json.loads(consultation.vitals or "{}")
    vital_items = [
        ("Blood Pressure", vitals.get("bp", "")),
        ("Temperature", vitals.get("temperature", "")),
        ("Pulse", vitals.get("pulse", "")),
        ("Weight", vitals.get("weight", "")),
        ("SpO2", vitals.get("spo2", "")),
    ]
    vital_items = [(k, v) for k, v in vital_items if v]
    fixed_keys = {"bp", "temperature", "pulse", "weight", "spo2"}
    for k, v in vitals.items():
        if k not in fixed_keys and v:
            vital_items.append((k, v))

    if vital_items:
        elements.append(Paragraph("Vitals", section_style))
        vital_data = [[k, v] for k, v in vital_items]
        vital_table = Table(vital_data, colWidths=[55*mm, 115*mm])
        vital_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(vital_table)
        elements.append(Spacer(1, 4*mm))

    # ── Diagnosis ──
    if consultation.diagnosis:
        elements.append(Paragraph("Diagnosis", section_style))
        elements.append(Paragraph(cap_sentence(consultation.diagnosis), body_style))
        elements.append(Spacer(1, 3*mm))

    # ── Medicines ──
    medicines = json.loads(consultation.medicines or "[]")
    if medicines:
        elements.append(Paragraph("Medicines", section_style))
        med_cell_style = ParagraphStyle("medcell", fontSize=9, fontName="Helvetica", leading=11)

        has_brand = any((m.get("brand_name") or "").strip() for m in medicines)

        if has_brand:
            med_data = [["Medicine", "Brand Name", "Dosage", "Frequency", "Duration", "Type"]]
        else:
            med_data = [["Medicine", "Dosage", "Frequency", "Duration", "Type"]]

        has_controlled = False
        for m in medicines:
            schedule = m.get("schedule", "controlled")
            if schedule == "controlled":
                has_controlled = True
            type_label = "Rx" if schedule == "controlled" else "OTC"
            row = [Paragraph(cap_sentence(m.get("name", "")), med_cell_style)]
            if has_brand:
                brand = (m.get("brand_name") or "").strip()
                row.append(Paragraph(cap_sentence(brand) if brand else "-", med_cell_style))
            row.extend([
                Paragraph(m.get("dosage", ""), med_cell_style),
                Paragraph(cap_sentence(m.get("frequency", "")), med_cell_style),
                Paragraph(m.get("duration") or "As advised", med_cell_style),
                type_label
            ])
            med_data.append(row)

        type_col = 5 if has_brand else 4
        med_table_style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a237e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("FONTNAME", (type_col, 1), (type_col, -1), "Helvetica-Bold"),
            ("ALIGN", (type_col, 0), (type_col, -1), "CENTER"),
        ]

        for idx, m in enumerate(medicines, start=1):
            schedule = m.get("schedule", "controlled")
            color = colors.HexColor("#dc2626") if schedule == "controlled" else colors.HexColor("#16a34a")
            med_table_style.append(("TEXTCOLOR", (type_col, idx), (type_col, idx), color))

        col_widths = [38*mm, 26*mm, 20*mm, 52*mm, 22*mm, 12*mm] if has_brand else [38*mm, 20*mm, 78*mm, 22*mm, 12*mm]
        med_table = Table(med_data, colWidths=col_widths)
        med_table.setStyle(TableStyle(med_table_style))
        elements.append(med_table)
        elements.append(Spacer(1, 2*mm))

        if has_controlled:
            warning_style = ParagraphStyle("warning", fontSize=8, fontName="Helvetica-Oblique", textColor=colors.HexColor("#dc2626"))
            elements.append(Paragraph(
                "⚠ Rx (Red) medicines are prescription-controlled. Pharmacies must verify via QR code or verification code below before dispensing.",
                warning_style
            ))
            elements.append(Spacer(1, 3*mm))
        else:
            elements.append(Spacer(1, 2*mm))

    # ── Tests ──
    try:
        ordered_tests = json.loads(consultation.ordered_tests or "[]")
    except Exception:
        ordered_tests = []

    if ordered_tests:
        elements.append(Paragraph("Tests / Investigations", section_style))
        test_data = [["#", "Test Name"]]
        for i, t in enumerate(ordered_tests, 1):
            test_data.append([str(i), cap_sentence(t.get("test_name", ""))])
        test_table = Table(test_data, colWidths=[15*mm, 155*mm])
        test_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a237e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(test_table)
        elements.append(Spacer(1, 4*mm))
    else:
        tests = json.loads(consultation.tests or "[]")
        if tests:
            elements.append(Paragraph("Tests / Investigations", section_style))
            test_data = [["#", "Test Name"]]
            for i, t in enumerate(tests, 1):
                test_data.append([str(i), cap_sentence(t)])
            test_table = Table(test_data, colWidths=[15*mm, 155*mm])
            test_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a237e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]))
            elements.append(test_table)
            elements.append(Spacer(1, 4*mm))

    # ── Imaging / Radiology ── (mirrors the Tests block exactly, ordered_radiology
    # is the confirmed/catalog-matched list, same relationship ordered_tests has to tests)
    try:
        ordered_radiology = json.loads(consultation.ordered_radiology or "[]")
    except Exception:
        ordered_radiology = []

    if ordered_radiology:
        elements.append(Paragraph("Imaging / Radiology", section_style))
        rad_data = [["#", "Study Name"]]
        for i, r in enumerate(ordered_radiology, 1):
            rad_data.append([str(i), cap_sentence(r.get("study_name", ""))])
        rad_table = Table(rad_data, colWidths=[15*mm, 155*mm])
        rad_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a237e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(rad_table)
        elements.append(Spacer(1, 4*mm))

    # ── Advice ──
    if consultation.advice:
        elements.append(Paragraph("Doctor's Advice", section_style))
        elements.append(Paragraph(cap_sentence(consultation.advice), body_style))
        elements.append(Spacer(1, 3*mm))

    # ── Follow-up ──
    if consultation.followup:
        elements.append(Paragraph("Follow-up", section_style))
        elements.append(Paragraph(cap_sentence(consultation.followup), body_style))
        elements.append(Spacer(1, 3*mm))

    # ── QR Code + Verification ──
    if verify_hash:
        elements.append(Spacer(1, 4*mm))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
        elements.append(Spacer(1, 3*mm))

        verify_url = f"{settings.PUBLIC_FRONTEND_URL}/pages/verify.html?token={token_number}&hash={verify_hash}"
        verify_url_display = verify_url.replace("&", "&amp;")

        qr = qrcode.QRCode(version=1, box_size=4, border=1)
        qr.add_data(verify_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="#0f1f3d", back_color="white")
        qr_buffer = io.BytesIO()
        qr_img.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)
        qr_image = Image(qr_buffer, width=22*mm, height=22*mm)

        verify_text_style = ParagraphStyle("verifytext", fontSize=8, fontName="Helvetica", leading=12, textColor=colors.HexColor("#334155"))

        verify_block = [
            [
                qr_image,
                Paragraph(
                    f"<b>Verify this prescription</b><br/>"
                    f"Scan QR code to verify.<br/>"
                    f"Token: <b>{token_number}</b><br/>"
                    f"Verification Code: <b>{verify_hash}</b><br/>"
                    f"Link: {verify_url_display}",
                    verify_text_style
                )
            ]
        ]
        verify_table = Table(verify_block, colWidths=[28*mm, 142*mm])
        verify_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        elements.append(verify_table)
        elements.append(Spacer(1, 3*mm))

    # ── Footer ──
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    elements.append(Spacer(1, 2*mm))
    footer_style = ParagraphStyle("footer", fontSize=8, fontName="Helvetica", alignment=TA_CENTER, textColor=colors.grey)
    elements.append(Paragraph(f"Token No: {token_number} | Generated by MedScribe | {now_ist().strftime('%d %b %Y %H:%M')}", footer_style))
    elements.append(Paragraph("This prescription is digitally generated and valid without a physical signature.", footer_style))

    header_text = f"{doctor.hospital.name if doctor.hospital else doctor.clinic_name}  |  {patient.name.title()} ({patient.patient_uid})  |  Rx {token_number}"
    doc.build(elements, canvasmaker=_make_numbered_canvas(header_text))
    return filepath

def generate_test_report_pdf(
    order: object,
    patient: object,
    catalog_item: object,
    ordering_doctor: object,
    lab_staff: object,
    hospital: object,
    verify_hash: str = None,
    mlc_custody_count: int = 0,
) -> str:
    ensure_reports_dir()

    filename = f"report_{order.id}.pdf"
    filepath = os.path.join(REPORTS_DIR, filename)

    doc = SimpleDocTemplate(
        filepath,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=15*mm,
        bottomMargin=15*mm
    )

    styles = getSampleStyleSheet()
    elements = []

    header_style = ParagraphStyle("header", fontSize=18, fontName="Helvetica-Bold", alignment=TA_CENTER, textColor=colors.HexColor("#1a237e"))
    sub_style = ParagraphStyle("sub", fontSize=10, fontName="Helvetica", alignment=TA_CENTER, textColor=colors.grey)
    section_style = ParagraphStyle("section", fontSize=11, fontName="Helvetica-Bold", textColor=colors.HexColor("#1a237e"), spaceAfter=2*mm)
    body_style = ParagraphStyle("body", fontSize=10, fontName="Helvetica", leading=14)

    elements.extend(build_letterhead(hospital, subtitle="Laboratory Test Report"))
    elements.append(Spacer(1, 3*mm))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1a237e")))
    elements.append(Spacer(1, 4*mm))

    bg = f" | Blood Group: {patient.blood_group}" if patient.blood_group else ""
    elements.append(Paragraph(
        f"<b>Patient:</b> {patient.name.title()} | {patient.age}yr | {patient.gender.capitalize()}{bg}",
        styles["Normal"]
    ))
    elements.append(Paragraph(f"<b>Patient ID:</b> {patient.patient_uid}", styles["Normal"]))
    if getattr(patient, "address", None):
        elements.append(Paragraph(f"<b>Address:</b> {patient.address}", styles["Normal"]))
    if getattr(order, "collected_at", None):
        elements.append(Paragraph(f"<b>Specimen Collected:</b> {order.collected_at.strftime('%d %b %Y, %I:%M %p')}", styles["Normal"]))
    if getattr(order, "accession_number", None):
        acc_time = f" ({order.accessioned_at.strftime('%d %b %Y, %I:%M %p')})" if order.accessioned_at else ""
        elements.append(Paragraph(f"<b>Accession No:</b> {order.accession_number}{acc_time}", styles["Normal"]))
    if getattr(order, "report_reference", None):
        elements.append(Paragraph(f"<b>Report Ref:</b> {order.report_reference}", styles["Normal"]))
    report_dt = order.verified_at if getattr(order, "verified_at", None) else now_ist()
    elements.append(Paragraph(f"<b>Report Date:</b> {report_dt.strftime('%d %b %Y, %I:%M %p')}", styles["Normal"]))
    elements.append(Spacer(1, 4*mm))

    # ── MLC banner (item 2) — proposed wording/placement, for review ──
    if getattr(order, "is_mlc_sample", False):
        mlc_style = ParagraphStyle("mlc", fontSize=10, fontName="Helvetica-Bold", textColor=colors.HexColor("#991b1b"), alignment=TA_CENTER)
        case_type_label = (order.mlc_case_type or "Not specified").replace("_", " ").title()
        case_ref = order.mlc_reference_number or "Not yet recorded"
        mlc_table = Table([[Paragraph(
            f"MEDICO-LEGAL CASE&nbsp;&nbsp;|&nbsp;&nbsp;Case Type: {case_type_label}&nbsp;&nbsp;|&nbsp;&nbsp;"
            f"Police/Case Ref: {case_ref}&nbsp;&nbsp;|&nbsp;&nbsp;Chain-of-Custody: {mlc_custody_count} entr{'y' if mlc_custody_count == 1 else 'ies'} logged",
            mlc_style
        )]], colWidths=[170*mm])
        mlc_table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 1.2, colors.HexColor("#991b1b")),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fee2e2")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(mlc_table)
        elements.append(Spacer(1, 4*mm))

    if getattr(catalog_item, "is_nabl_accredited", False):
        accreditation_style = ParagraphStyle("accreditation", fontSize=8.5, fontName="Helvetica-Oblique", textColor=colors.HexColor("#065f46"))
        elements.append(Paragraph("This test is performed within our NABL-accredited scope.", accreditation_style))
    elements.append(Spacer(1, 2*mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    elements.append(Spacer(1, 4*mm))

    elements.append(Paragraph("Test Result", section_style))

    reference_range = ""
    unit = ""
    if catalog_item:
        reference_range = (
            catalog_item.reference_range_male if patient.gender.lower() == "male"
            else catalog_item.reference_range_female
        ) or ""
        unit = catalog_item.unit or ""

    try:
        result_data = json.loads(order.result_data or "{}")
    except Exception:
        result_data = {}

    value = result_data.get("value", "—")
    flag = result_data.get("flag", "N")
    notes = result_data.get("notes", "")

    flag_labels = {"H": "High", "L": "Low", "N": "Normal"}
    flag_colors = {"H": colors.HexColor("#b45309"), "L": colors.HexColor("#1e40af"), "N": colors.HexColor("#065f46")}

    table_data = [
        ["Test Name", "Result", "Unit", "Reference Range", "Flag"],
        [order.test_name, value, unit, reference_range or "—", flag_labels.get(flag, flag)]
    ]
    result_table = Table(table_data, colWidths=[45*mm, 25*mm, 20*mm, 45*mm, 20*mm])
    result_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TEXTCOLOR", (4, 1), (4, 1), flag_colors.get(flag, colors.black)),
        ("FONTNAME", (4, 1), (4, 1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(result_table)
    elements.append(Spacer(1, 4*mm))

    if getattr(order, "fasting_confirmed", None) is False or getattr(order, "drawn_from_iv_line", False) or getattr(order, "sample_condition_caveat", None):
        caveat_style = ParagraphStyle("caveat", fontSize=9.5, fontName="Helvetica-Bold", textColor=colors.HexColor("#b45309"), spaceAfter=2*mm)
        if getattr(order, "fasting_confirmed", None) is False:
            elements.append(Paragraph("⚠ Sample was NOT drawn after fasting — interpret this result with this in mind.", caveat_style))
        if getattr(order, "drawn_from_iv_line", False):
            elements.append(Paragraph("⚠ Sample drawn from an IV-line arm — may affect interpretation on certain analytes.", caveat_style))
        if getattr(order, "sample_condition_caveat", None):
            elements.append(Paragraph(f"⚠ Sample condition note: {order.sample_condition_caveat} — reported as-is per irreplaceable-sample policy.", caveat_style))

    if notes:
        elements.append(Paragraph("Notes", section_style))
        elements.append(Paragraph(notes, body_style))
        elements.append(Spacer(1, 4*mm))

    # ── QR Code + Verification (item 1) ──
    if verify_hash:
        elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
        elements.append(Spacer(1, 3*mm))
        verify_url = f"{settings.PUBLIC_FRONTEND_URL}/pages/verify.html?type=lab_report&id={order.id}&hash={verify_hash}"
        verify_url_display = verify_url.replace("&", "&amp;")
        qr = qrcode.QRCode(version=1, box_size=4, border=1)
        qr.add_data(verify_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="#0f1f3d", back_color="white")
        qr_buffer = io.BytesIO()
        qr_img.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)
        qr_image = Image(qr_buffer, width=22*mm, height=22*mm)
        verify_text_style = ParagraphStyle("verifytext", fontSize=8, fontName="Helvetica", leading=12, textColor=colors.HexColor("#334155"))
        verify_table = Table([[qr_image, Paragraph(
            f"<b>Verify this report</b><br/>Scan QR code to verify authenticity.<br/>"
            f"Verification Code: <b>{verify_hash}</b><br/>Link: {verify_url_display}",
            verify_text_style
        )]], colWidths=[28*mm, 142*mm])
        verify_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        elements.append(Spacer(1, 3*mm))
        elements.append(verify_table)
        elements.append(Spacer(1, 3*mm))

    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    elements.append(Spacer(1, 4*mm))

    footer_style = ParagraphStyle("footer", fontSize=9, fontName="Helvetica", textColor=colors.HexColor("#334155"))
    doctor_line = f"<b>Ordering Doctor:</b> {ordering_doctor.title} {ordering_doctor.name}" if ordering_doctor else "<b>Ordering Doctor:</b> —"
    if ordering_doctor and getattr(ordering_doctor, "registration_number", None):
        doctor_line += f" (Reg. No: {ordering_doctor.registration_number})"
    elements.append(Paragraph(doctor_line, footer_style))
    if lab_staff:
        verified_line = f"<b>Verified By:</b> {lab_staff.title} {lab_staff.name}" if getattr(lab_staff, "title", None) else f"<b>Verified By:</b> {lab_staff.name}"
        if getattr(order, "verified_at", None):
            verified_line += f" on {order.verified_at.strftime('%d %b %Y, %I:%M %p')}"
        elements.append(Paragraph(verified_line, footer_style))
    else:
        elements.append(Paragraph("<b>Verified By:</b> —", footer_style))
    # Item 4 — proposed wording, for review
    disclaimer_name = f"{lab_staff.title} {lab_staff.name}" if lab_staff and getattr(lab_staff, "title", None) else (lab_staff.name if lab_staff else "the verifying lab officer")
    elements.append(Paragraph(
        f"This report is generated by MedScribe's laboratory information system and electronically verified by {disclaimer_name} — no physical signature is required.",
        ParagraphStyle("disclaimer", fontSize=7.5, fontName="Helvetica-Oblique", textColor=colors.grey)
    ))

    ref = getattr(order, "report_reference", None) or f"ORD-{order.id}"
    header_text = f"{hospital.name}  |  {patient.name.title()} ({patient.patient_uid})  |  {ref}"
    doc.build(elements, canvasmaker=_make_numbered_canvas(header_text))
    return filepath

def _parse_range_bounds(range_str):
    if not range_str:
        return None
    cleaned = range_str.replace(",", "").strip()
    low_txt = cleaned.lower()
    if cleaned.startswith("<") or "less" in low_txt or "upto" in low_txt or "up to" in low_txt:
        nums = re.findall(r'\d+\.?\d*', cleaned)
        return (None, float(nums[0])) if nums else None
    if cleaned.startswith(">") or "greater" in low_txt or "above" in low_txt:
        nums = re.findall(r'\d+\.?\d*', cleaned)
        return (float(nums[0]), None) if nums else None

    # Split only on a hyphen that directly follows a digit, so "0.6-1.1"
    # splits into two positive bounds instead of the "-1.1" being read
    # as a negative number.
    parts = re.split(r'(?<=\d)\s*-\s*', cleaned)
    if len(parts) == 2:
        try:
            low_nums = re.findall(r'\d+\.?\d*', parts[0])
            high_nums = re.findall(r'\d+\.?\d*', parts[1])
            if low_nums and high_nums:
                return float(low_nums[0]), float(high_nums[0])
        except ValueError:
            return None
    return None

def _is_out_of_range(value_str, range_str):
    bounds = _parse_range_bounds(range_str)
    if not bounds or not value_str:
        return False
    nums = re.findall(r'\d+\.?\d*', str(value_str).replace(",", ""))
    if not nums:
        return False
    try:
        val = float(nums[0])
    except ValueError:
        return False
    low, high = bounds
    if low is not None and val < low:
        return True
    if high is not None and val > high:
        return True
    return False

def generate_combined_test_report_pdf(order_id_key, tests_payload, patient, ordering_doctor, lab_staff, hospital, verify_hash: str = None) -> str:
    ensure_reports_dir()

    filename = f"combined_report_{order_id_key}.pdf"
    filepath = os.path.join(REPORTS_DIR, filename)

    doc = SimpleDocTemplate(
        filepath,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=15*mm,
        bottomMargin=15*mm
    )

    styles = getSampleStyleSheet()
    elements = []

    header_style = ParagraphStyle("header", fontSize=18, fontName="Helvetica-Bold", alignment=TA_CENTER, textColor=colors.HexColor("#1a237e"))
    sub_style = ParagraphStyle("sub", fontSize=10, fontName="Helvetica", alignment=TA_CENTER, textColor=colors.grey)
    section_style = ParagraphStyle("section", fontSize=12, fontName="Helvetica-Bold", textColor=colors.HexColor("#1a237e"), spaceAfter=2*mm, spaceBefore=4*mm)
    body_style = ParagraphStyle("body", fontSize=10, fontName="Helvetica", leading=14)

    elements.extend(build_letterhead(hospital, subtitle="Laboratory Test Report"))
    elements.append(Spacer(1, 4*mm))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1a237e")))
    elements.append(Spacer(1, 5*mm))

    bg = f" | Blood Group: {patient.blood_group}" if patient.blood_group else ""
    elements.append(Paragraph(
        f"<b>Patient:</b> {patient.name.title()} | {patient.age}yr | {patient.gender.capitalize()}{bg}",
        styles["Normal"]
    ))
    elements.append(Paragraph(f"<b>Patient ID:</b> {patient.patient_uid}", styles["Normal"]))
    if getattr(patient, "address", None):
        elements.append(Paragraph(f"<b>Address:</b> {patient.address}", styles["Normal"]))
    latest_verified = max((t["verified_at"] for t in tests_payload if t.get("verified_at")), default=None)
    report_dt = latest_verified if latest_verified else now_ist()
    elements.append(Paragraph(f"<b>Report Date:</b> {report_dt.strftime('%d %b %Y, %I:%M %p')}", styles["Normal"]))
    elements.append(Spacer(1, 4*mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))

    caveat_style = ParagraphStyle("caveat", fontSize=9.5, fontName="Helvetica-Bold", textColor=colors.HexColor("#b45309"), spaceAfter=2*mm)
    ref_style = ParagraphStyle("ref", fontSize=8, fontName="Helvetica-Oblique", textColor=colors.grey, spaceAfter=2*mm)

    for test in tests_payload:
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph(test["test_name"], section_style))
        # Item 2's MLC banner isn't repeated per-test here — combined reports
        # only ever bundle routine (non-MLC) results in current usage; flag
        # to Praful if that assumption is wrong before extending this.
        if test.get("report_reference"):
            elements.append(Paragraph(f"Report Ref: {test['report_reference']}", ref_style))
        meta_bits = []
        if test.get("collected_at"):
            meta_bits.append(f"Specimen Collected: {test['collected_at'].strftime('%d %b %Y, %I:%M %p')}")
        if test.get("accession_number"):
            acc_time = f" ({test['accessioned_at'].strftime('%d %b %Y, %I:%M %p')})" if test.get("accessioned_at") else ""
            meta_bits.append(f"Accession No: {test['accession_number']}{acc_time}")
        if meta_bits:
            elements.append(Paragraph(" | ".join(meta_bits), ParagraphStyle("meta", fontSize=8.5, textColor=colors.grey, spaceAfter=2*mm)))
        if test.get("fasting_confirmed") is False:
            elements.append(Paragraph("⚠ Sample was NOT drawn after fasting — interpret this result with this in mind.", caveat_style))
        if test.get("drawn_from_iv_line"):
            elements.append(Paragraph("⚠ Sample drawn from an IV-line arm — may affect interpretation on certain analytes.", caveat_style))
        if test.get("sample_condition_caveat"):
            elements.append(Paragraph(f"⚠ Sample condition note: {test['sample_condition_caveat']} — reported as-is per irreplaceable-sample policy.", caveat_style))

        if test.get("is_nabl_accredited"):
            accreditation_style = ParagraphStyle("accreditation", fontSize=8, fontName="Helvetica-Oblique", textColor=colors.HexColor("#065f46"))
            elements.append(Paragraph("Within our NABL-accredited scope.", accreditation_style))

        table_data = [["Parameter", "Result", "Unit", "Reference Range"]]
        row_styles = []
        for i, row in enumerate(test["rows"]):
            out = _is_out_of_range(row["value"], row["range"])
            table_data.append([row["name"], row["value"] or "—", row["unit"] or "—", row["range"] or "—"])
            if out:
                row_styles.append(("FONTNAME", (1, i+1), (1, i+1), "Helvetica-Bold"))
                row_styles.append(("TEXTCOLOR", (1, i+1), (1, i+1), colors.HexColor("#ef4444")))
            elif row["value"]:
                row_styles.append(("TEXTCOLOR", (1, i+1), (1, i+1), colors.HexColor("#065f46")))

        result_table = Table(table_data, colWidths=[55*mm, 30*mm, 25*mm, 45*mm])
        result_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ] + row_styles))
        elements.append(result_table)

        if test.get("notes"):
            elements.append(Spacer(1, 2*mm))
            elements.append(Paragraph(f"<b>Notes:</b> {test['notes']}", body_style))

    elements.append(Spacer(1, 5*mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    elements.append(Spacer(1, 4*mm))

    # ── QR Code + Verification (item 1) ──
    if verify_hash:
        elements.append(Spacer(1, 4*mm))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
        elements.append(Spacer(1, 3*mm))
        ids_key = order_id_key.split("_", 1)[-1] if "_" in order_id_key else order_id_key
        verify_url = f"{settings.PUBLIC_FRONTEND_URL}/pages/verify.html?type=combined_lab_report&ids={ids_key}&hash={verify_hash}"
        verify_url_display = verify_url.replace("&", "&amp;")
        qr = qrcode.QRCode(version=1, box_size=4, border=1)
        qr.add_data(verify_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="#0f1f3d", back_color="white")
        qr_buffer = io.BytesIO()
        qr_img.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)
        qr_image = Image(qr_buffer, width=22*mm, height=22*mm)
        verify_text_style = ParagraphStyle("verifytext", fontSize=8, fontName="Helvetica", leading=12, textColor=colors.HexColor("#334155"))
        verify_table = Table([[qr_image, Paragraph(
            f"<b>Verify this report</b><br/>Scan QR code to verify authenticity.<br/>"
            f"Verification Code: <b>{verify_hash}</b><br/>Link: {verify_url_display}",
            verify_text_style
        )]], colWidths=[28*mm, 142*mm])
        verify_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        elements.append(verify_table)
        elements.append(Spacer(1, 3*mm))

    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    elements.append(Spacer(1, 4*mm))

    footer_style = ParagraphStyle("footer", fontSize=9, fontName="Helvetica", textColor=colors.HexColor("#334155"))
    doctor_line = f"<b>Ordering Doctor:</b> {ordering_doctor.title} {ordering_doctor.name}" if ordering_doctor else "<b>Ordering Doctor:</b> —"
    if ordering_doctor and ordering_doctor.registration_number:
        doctor_line += f" (Reg. No: {ordering_doctor.registration_number})"
    elements.append(Paragraph(doctor_line, footer_style))
    if lab_staff:
        verified_line = f"<b>Verified By:</b> {lab_staff.title} {lab_staff.name}" if getattr(lab_staff, "title", None) else f"<b>Verified By:</b> {lab_staff.name}"
        if latest_verified:
            verified_line += f" on {latest_verified.strftime('%d %b %Y, %I:%M %p')}"
        elements.append(Paragraph(verified_line, footer_style))
    else:
        elements.append(Paragraph("<b>Verified By:</b> —", footer_style))
    disclaimer_name = f"{lab_staff.title} {lab_staff.name}" if lab_staff and getattr(lab_staff, "title", None) else (lab_staff.name if lab_staff else "the verifying lab officer")
    elements.append(Paragraph(
        f"This report is generated by MedScribe's laboratory information system and electronically verified by {disclaimer_name} — no physical signature is required.",
        ParagraphStyle("disclaimer", fontSize=7.5, fontName="Helvetica-Oblique", textColor=colors.grey)
    ))

    header_text = f"{hospital.name}  |  {patient.name.title()} ({patient.patient_uid})  |  Combined Lab Report"
    doc.build(elements, canvasmaker=_make_numbered_canvas(header_text))
    return filepath

def generate_radiology_report_pdf(order: object, patient: object, ordering_doctor: object, radiology_staff: object, hospital: object, verify_hash: str = None, reporting_staff: object = None) -> str:
    ensure_reports_dir()

    filename = f"radiology_report_{order.id}.pdf"
    filepath = os.path.join(REPORTS_DIR, filename)

    doc = SimpleDocTemplate(
        filepath, pagesize=A4,
        rightMargin=20*mm, leftMargin=20*mm, topMargin=15*mm, bottomMargin=15*mm
    )

    styles = getSampleStyleSheet()
    elements = []

    section_style = ParagraphStyle("section", fontSize=11, fontName="Helvetica-Bold", textColor=colors.HexColor("#1a237e"), spaceAfter=2*mm, spaceBefore=3*mm)
    label_style = ParagraphStyle("label", fontSize=10, fontName="Helvetica-Bold", textColor=colors.HexColor("#1a237e"))
    body_style = ParagraphStyle("body", fontSize=10, fontName="Helvetica", leading=14)
    STUDY_TYPE_LABEL = {"xray": "X-Ray", "ct": "CT", "mri": "MRI", "ultrasound": "Ultrasound"}

    elements.extend(build_letterhead(hospital, subtitle="Radiology Report"))
    elements.append(Spacer(1, 3*mm))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1a237e")))
    elements.append(Spacer(1, 4*mm))

    bg = f" | Blood Group: {patient.blood_group}" if patient.blood_group else ""
    elements.append(Paragraph(
        f"<b>Patient:</b> {patient.name.title()} | {patient.age}yr | {patient.gender.capitalize()}{bg}",
        styles["Normal"]
    ))
    elements.append(Paragraph(f"<b>Patient ID:</b> {patient.patient_uid}", styles["Normal"]))
    if getattr(patient, "address", None):
        elements.append(Paragraph(f"<b>Address:</b> {patient.address}", styles["Normal"]))
    if getattr(order, "report_reference", None):
        elements.append(Paragraph(f"<b>Report Ref:</b> {order.report_reference}", styles["Normal"]))
    report_dt = order.verified_at if order.verified_at else now_ist()
    elements.append(Paragraph(f"<b>Report Date:</b> {report_dt.strftime('%d %b %Y, %I:%M %p')}", styles["Normal"]))
    elements.append(Spacer(1, 4*mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    elements.append(Spacer(1, 4*mm))

    study_label = f"{STUDY_TYPE_LABEL.get(order.study_type, order.study_type)} — {order.study_name}"
    elements.append(Paragraph(study_label.upper(), section_style))
    if order.clinical_indication:
        elements.append(Paragraph(f"<b>Clinical Indication:</b> {order.clinical_indication}", body_style))
    elements.append(Spacer(1, 3*mm))

    try:
        sections = json.loads(order.sections_data or "{}")
    except Exception:
        sections = {}

    # Narrative sections (Liver, Kidneys, etc.), not a value/range table —
    # imaging findings are prose per section, not numeric values (Part 1 item 1).
    for name, text in sections.items():
        elements.append(Paragraph(
            f'<font name="Helvetica-Bold" color="#1a237e">{name.upper()}:</font> {text or "—"}',
            body_style
        ))
        elements.append(Spacer(1, 1.5*mm))

    elements.append(Spacer(1, 2*mm))
    elements.append(Paragraph("IMPRESSION", label_style))
    elements.append(Paragraph(order.impression or "—", body_style))
    elements.append(Spacer(1, 3*mm))

    elements.append(Paragraph("ADVISED", label_style))
    elements.append(Paragraph(order.advised or "—", body_style))
    elements.append(Spacer(1, 4*mm))

    # ── QR Code + Verification (item 1) ──
    if verify_hash:
        elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
        elements.append(Spacer(1, 3*mm))
        verify_url = f"{settings.PUBLIC_FRONTEND_URL}/pages/verify.html?type=radiology_report&id={order.id}&hash={verify_hash}"
        verify_url_display = verify_url.replace("&", "&amp;")
        qr = qrcode.QRCode(version=1, box_size=4, border=1)
        qr.add_data(verify_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="#0f1f3d", back_color="white")
        qr_buffer = io.BytesIO()
        qr_img.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)
        qr_image = Image(qr_buffer, width=22*mm, height=22*mm)
        verify_text_style = ParagraphStyle("verifytext", fontSize=8, fontName="Helvetica", leading=12, textColor=colors.HexColor("#334155"))
        verify_table = Table([[qr_image, Paragraph(
            f"<b>Verify this report</b><br/>Scan QR code to verify authenticity.<br/>"
            f"Verification Code: <b>{verify_hash}</b><br/>Link: {verify_url_display}",
            verify_text_style
        )]], colWidths=[28*mm, 142*mm])
        verify_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        elements.append(Spacer(1, 3*mm))
        elements.append(verify_table)
        elements.append(Spacer(1, 3*mm))

    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    elements.append(Spacer(1, 4*mm))

    footer_style = ParagraphStyle("footer", fontSize=9, fontName="Helvetica", textColor=colors.HexColor("#334155"))
    doctor_line = f"<b>Referring Doctor:</b> {ordering_doctor.title} {ordering_doctor.name}" if ordering_doctor else "<b>Referring Doctor:</b> —"
    if ordering_doctor and getattr(ordering_doctor, "registration_number", None):
        doctor_line += f" (Reg. No: {ordering_doctor.registration_number})"
    elements.append(Paragraph(doctor_line, footer_style))
    # Item 5c: the model has reported_by (who wrote the findings) and
    # verified_by (who signed off) — not "Performed By" in the sense you
    # meant (the technician who captured the images). That field doesn't
    # exist; flagging per your instruction rather than inventing one. Both
    # of the roles that DO exist are now shown, where the old code only
    # ever rendered verified_by.
    if reporting_staff:
        reported_line = f"<b>Reported By:</b> {reporting_staff.title} {reporting_staff.name}" if getattr(reporting_staff, "title", None) else f"<b>Reported By:</b> {reporting_staff.name}"
        if order.reported_at:
            reported_line += f" on {order.reported_at.strftime('%d %b %Y, %I:%M %p')}"
        elements.append(Paragraph(reported_line, footer_style))
    if radiology_staff:
        verified_line = f"<b>Verified By:</b> {radiology_staff.title} {radiology_staff.name}" if getattr(radiology_staff, "title", None) else f"<b>Verified By:</b> {radiology_staff.name}"
        if order.verified_at:
            verified_line += f" on {order.verified_at.strftime('%d %b %Y, %I:%M %p')}"
        elements.append(Paragraph(verified_line, footer_style))
    else:
        elements.append(Paragraph("<b>Verified By:</b> —", footer_style))
    disclaimer_name = f"{radiology_staff.title} {radiology_staff.name}" if radiology_staff and getattr(radiology_staff, "title", None) else (radiology_staff.name if radiology_staff else "the verifying radiologist")
    elements.append(Paragraph(
        f"This report is generated by MedScribe's radiology information system and electronically verified by {disclaimer_name} — no physical signature is required.",
        ParagraphStyle("disclaimer", fontSize=7.5, fontName="Helvetica-Oblique", textColor=colors.grey)
    ))

    ref = getattr(order, "report_reference", None) or f"RAD-{order.id}"
    header_text = f"{hospital.name}  |  {patient.name.title()} ({patient.patient_uid})  |  {ref}"
    doc.build(elements, canvasmaker=_make_numbered_canvas(header_text))
    return filepath


def generate_invoice_pdf(
    invoice_id: int, hospital, items: list, grand_total: float, patient, doctor=None,
    receipt_number=None, place_of_supply=None, admission_date=None, discharge_date=None,
    subtotal=None, gst_total=None, verify_hash=None, is_duplicate=False,
    deposit_paid=None, amount_collected_now=None, refund_due=None,
) -> str:
    ensure_reports_dir()
    invoices_dir = os.path.join(os.path.dirname(__file__), "..", "..", "invoices")
    os.makedirs(invoices_dir, exist_ok=True)

    filepath = os.path.join(invoices_dir, f"invoice_{invoice_id}.pdf")

    doc = SimpleDocTemplate(
        filepath, pagesize=A4,
        rightMargin=20*mm, leftMargin=20*mm, topMargin=15*mm, bottomMargin=15*mm
    )
    styles = getSampleStyleSheet()
    elements = []

    gst_registered = bool(hospital and hospital.gstin)

    elements.extend(build_letterhead(hospital))
    elements.append(Spacer(1, 3*mm))
    elements.append(Paragraph("TAX INVOICE" if gst_registered else "INVOICE",
                               ParagraphStyle("inv", fontSize=13, fontName="Helvetica-Bold", alignment=TA_CENTER)))
    elements.append(Paragraph("DUPLICATE COPY" if is_duplicate else "ORIGINAL FOR RECIPIENT",
                               ParagraphStyle("copy", fontSize=8, fontName="Helvetica-Oblique", alignment=TA_CENTER, textColor=colors.grey)))
    elements.append(Spacer(1, 4*mm))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a237e")))
    elements.append(Spacer(1, 4*mm))

    # ── Bill To ──
    bill_to_style = ParagraphStyle("billto", fontSize=9.5, fontName="Helvetica", leading=13)
    elements.append(Paragraph("<b>Bill To:</b>", bill_to_style))
    elements.append(Paragraph(patient.name.title(), bill_to_style))
    elements.append(Paragraph(f"{patient.age}yr | {patient.gender.capitalize()} | Patient ID: {patient.patient_uid}", bill_to_style))
    if getattr(patient, "address", None):
        elements.append(Paragraph(patient.address, bill_to_style))
    if getattr(patient, "phone", None):
        elements.append(Paragraph(f"Ph: {patient.phone}", bill_to_style))
    elements.append(Spacer(1, 3*mm))

    if receipt_number:
        elements.append(Paragraph(f"<b>Receipt No:</b> {receipt_number} &nbsp;&nbsp; <b>Date:</b> {now_ist().strftime('%d %b %Y, %I:%M %p')}", styles["Normal"]))
    else:
        invoice_hash = hashlib.sha256(f"invoice-{invoice_id}-{settings.SECRET_KEY}".encode()).hexdigest()[:8].upper()
        elements.append(Paragraph(f"<b>Invoice #:</b> INV-{invoice_hash} &nbsp;&nbsp; <b>Date:</b> {now_ist().strftime('%d %b %Y, %I:%M %p')}", styles["Normal"]))
    if doctor:
        elements.append(Paragraph(f"<b>Consulting Doctor:</b> {doctor.title} {doctor.name}", styles["Normal"]))
    # Only present on IPD (admission/discharge) invoices — admission_date and
    # discharge_date are passed in only from that call site.
    if admission_date:
        elements.append(Paragraph(f"<b>Admission Date:</b> {admission_date.strftime('%d %b %Y, %I:%M %p')}", styles["Normal"]))
    if discharge_date:
        elements.append(Paragraph(f"<b>Discharge Date:</b> {discharge_date.strftime('%d %b %Y, %I:%M %p')}", styles["Normal"]))
    if place_of_supply:
        elements.append(Paragraph(f"<b>Place of Supply:</b> {place_of_supply}", styles["Normal"]))
    elements.append(Spacer(1, 5*mm))

    payable_items = [i for i in items if i.get("payable_here", True) is not False]
    pharmacy_items = [i for i in items if i.get("payable_here", True) is False]

    gst_enabled = gst_registered and any(i.get("gst_rate") for i in payable_items)
    desc_style = ParagraphStyle("desc", fontSize=8 if gst_enabled else 9.5, fontName="Helvetica", leading=11)
    desc_note_style = ParagraphStyle("desc_note", fontSize=7.5, fontName="Helvetica-Oblique", textColor=colors.grey, leading=9)

    if gst_enabled:
        # ── Full GST breakdown per line item — item 1/2 fix ──
        table_data = [["#", "Description", "HSN/SAC", "Qty", "Rate", "Taxable", "GST%", "CGST", "SGST", "Amount"]]
        for idx, item in enumerate(payable_items, 1):
            table_data.append([
                str(idx),
                Paragraph(item["name"], desc_style),
                item.get("hsn_sac") or "-",
                str(item.get("qty", 1)),
                f"{item.get('unit_price', 0):.2f}",
                f"{item.get('taxable_amount', item.get('line_total', 0)):.2f}",
                f"{item.get('gst_rate', 0):.1f}%" if item.get("gst_rate") else "-",
                f"{item.get('cgst_amount', 0):.2f}",
                f"{item.get('sgst_amount', 0):.2f}",
                f"{item.get('total_with_tax', item.get('line_total', 0)):.2f}",
            ])
        subtotal_val = subtotal if subtotal is not None else sum(i.get("taxable_amount", i.get("line_total", 0)) for i in payable_items)
        gst_total_val = gst_total if gst_total is not None else sum(i.get("tax_amount", 0) for i in payable_items)
        table_data.append(["", "", "", "", "", "Subtotal", f"{subtotal_val:.2f}", "GST", "", f"{gst_total_val:.2f}"])
        table_data.append(["", "", "", "", "", "", "", "", "Grand Total", f"Rs.{grand_total:.2f}"])
        col_widths = [8*mm, 38*mm, 15*mm, 9*mm, 15*mm, 17*mm, 12*mm, 16*mm, 16*mm, 24*mm]
        footer_rows = 2
    else:
        table_data = [["Description", "Qty", "Unit Price", "Amount"]]
        for item in payable_items:
            table_data.append([
                Paragraph(item["name"], desc_style),
                str(item.get("qty", 1)),
                f"Rs.{item.get('unit_price', 0):.2f}",
                f"Rs.{item.get('line_total', 0):.2f}"
            ])
        table_data.append(["", "", "Grand Total", f"Rs.{grand_total:.2f}"])
        col_widths = [85*mm, 20*mm, 30*mm, 30*mm]
        footer_rows = 1

    t = Table(table_data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -footer_rows), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5 if gst_enabled else 9.5),
        ("GRID", (0, 0), (-1, -footer_rows - 1), 0.4, colors.lightgrey),
        ("LINEABOVE", (0, -footer_rows), (-1, -footer_rows), 1, colors.HexColor("#1a237e")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 3*mm))
    elements.append(Paragraph(f"<b>Amount Chargeable (in words):</b> {amount_to_words_inr(grand_total)}",
                               ParagraphStyle("words", fontSize=8.5, fontName="Helvetica-Oblique")))
    elements.append(Spacer(1, 6*mm))

    # ── Items dispensed at pharmacy — unambiguous "not included" section (item 6) ──
    if pharmacy_items:
        elements.append(Paragraph("Dispensed at Pharmacy Counter — Not Included in This Bill",
                                   ParagraphStyle("pharmnote", fontSize=9, fontName="Helvetica-Bold", textColor=colors.HexColor("#92400e"))))
        ph_data = [["Description", "Qty", "Unit Price", "Amount"]]
        ph_subtotal = 0.0
        for item in pharmacy_items:
            ph_subtotal += item.get("line_total", 0)
            ph_data.append([
                Paragraph(item["name"], desc_style),
                str(item.get("qty", 1)),
                f"Rs.{item.get('unit_price', 0):.2f}",
                f"Rs.{item.get('line_total', 0):.2f}"
            ])
        ph_data.append(["", "", "Billed separately at Pharmacy", f"Rs.{ph_subtotal:.2f}"])
        ph_table = Table(ph_data, colWidths=[85*mm, 20*mm, 30*mm, 30*mm])
        ph_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#fef3c7")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Oblique"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("GRID", (0, 0), (-1, -2), 0.4, colors.HexColor("#fde68a")),
            ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#f59e0b")),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(Spacer(1, 2*mm))
        elements.append(ph_table)
        elements.append(Spacer(1, 6*mm))

    # ── Payment summary — deposit / collected / refund (item 7) ──
    if deposit_paid is not None or amount_collected_now is not None or refund_due is not None:
        elements.append(Paragraph("Payment Summary", ParagraphStyle("paysum", fontSize=9.5, fontName="Helvetica-Bold")))
        pay_rows = []
        if deposit_paid is not None:
            pay_rows.append(["Deposit Paid (during stay)", f"Rs.{deposit_paid:.2f}"])
        pay_rows.append(["Total Bill (Grand Total)", f"Rs.{grand_total:.2f}"])
        if amount_collected_now is not None:
            pay_rows.append(["Amount Collected at Discharge", f"Rs.{amount_collected_now:.2f}"])
        if refund_due and refund_due > 0:
            pay_rows.append(["Refund Due to Patient", f"Rs.{refund_due:.2f}"])
        pay_table = Table(pay_rows, colWidths=[110*mm, 50*mm])
        pay_table.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(Spacer(1, 2*mm))
        elements.append(pay_table)
        elements.append(Spacer(1, 6*mm))

    # ── Declaration / signatory (item 8) ──
    decl_style = ParagraphStyle("decl", fontSize=7.5, fontName="Helvetica", textColor=colors.grey, leading=10)
    elements.append(Paragraph(
        "Declaration: We hereby certify that the goods/services described above are true and correct, "
        "and the amount charged does not exceed the amount permissible under applicable GST law. "
        "This is a computer-generated invoice and does not require a physical signature.",
        decl_style
    ))
    elements.append(Spacer(1, 8*mm))
    sig_style = ParagraphStyle("sig", fontSize=9, fontName="Helvetica", alignment=TA_RIGHT)
    elements.append(Paragraph(f"For {hospital.name if hospital else ''}", sig_style))
    elements.append(Spacer(1, 10*mm))
    elements.append(Paragraph("Authorized Signatory", sig_style))
    elements.append(Spacer(1, 6*mm))

    # ── QR Code + Verification (item 9) ──
    if verify_hash:
        elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
        elements.append(Spacer(1, 3*mm))
        verify_url = f"{settings.PUBLIC_FRONTEND_URL}/pages/verify.html?type=invoice&id={invoice_id}&hash={verify_hash}"
        verify_url_display = verify_url.replace("&", "&amp;")
        qr = qrcode.QRCode(version=1, box_size=4, border=1)
        qr.add_data(verify_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="#0f1f3d", back_color="white")
        qr_buffer = io.BytesIO()
        qr_img.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)
        qr_image = Image(qr_buffer, width=22*mm, height=22*mm)
        verify_text_style = ParagraphStyle("verifytext", fontSize=8, fontName="Helvetica", leading=12, textColor=colors.HexColor("#334155"))
        verify_block = [[
            qr_image,
            Paragraph(
                f"<b>Verify this invoice</b><br/>"
                f"Scan QR code to verify authenticity.<br/>"
                f"Verification Code: <b>{verify_hash}</b><br/>"
                f"Link: {verify_url_display}",
                verify_text_style
            )
        ]]
        verify_table = Table(verify_block, colWidths=[28*mm, 142*mm])
        verify_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        elements.append(verify_table)
        elements.append(Spacer(1, 4*mm))

    elements.append(Paragraph("Thank you for visiting.", ParagraphStyle("thanks", fontSize=9, alignment=TA_CENTER, textColor=colors.grey)))

    ref = receipt_number or f"INV-{invoice_id}"
    header_text = f"{hospital.name if hospital else ''}  |  {patient.name.title()} ({patient.patient_uid})  |  {ref}"
    doc.build(elements, canvasmaker=_make_numbered_canvas(header_text))
    return filepath

def generate_credit_debit_note_pdf(note, invoice, hospital, patient) -> str:
    """Credit/debit note PDF — mirrors generate_invoice_pdf's letterhead
    conventions (item 4). `note` is a CreditDebitNote row, `invoice` the
    original Invoice it corrects (may be None if that row was later purged
    — the invoice_number/invoice_date snapshot on the note covers that)."""
    ensure_reports_dir()
    invoices_dir = os.path.join(os.path.dirname(__file__), "..", "..", "invoices")
    os.makedirs(invoices_dir, exist_ok=True)
    filepath = os.path.join(invoices_dir, f"note_{note.id}.pdf")

    doc = SimpleDocTemplate(
        filepath, pagesize=A4,
        rightMargin=20*mm, leftMargin=20*mm, topMargin=15*mm, bottomMargin=15*mm
    )
    elements = []
    elements.extend(build_letterhead(hospital))
    elements.append(Spacer(1, 3*mm))

    title = "CREDIT NOTE" if note.note_type == "credit" else "DEBIT NOTE"
    elements.append(Paragraph(title, ParagraphStyle("cdn", fontSize=13, fontName="Helvetica-Bold", alignment=TA_CENTER, textColor=colors.HexColor("#1a237e"))))
    elements.append(Spacer(1, 4*mm))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a237e")))
    elements.append(Spacer(1, 4*mm))

    body_style = ParagraphStyle("body", fontSize=9.5, fontName="Helvetica", leading=13)
    elements.append(Paragraph(f"<b>{title.title()} No:</b> {note.note_number} &nbsp;&nbsp; <b>Date:</b> {note.created_at.strftime('%d %b %Y, %I:%M %p')}", body_style))
    elements.append(Paragraph(
        f"<b>Against Invoice:</b> {note.invoice_number or (invoice.receipt_number if invoice else note.invoice_id)} "
        f"dated {note.invoice_date.strftime('%d %b %Y') if note.invoice_date else '-'}", body_style))
    elements.append(Spacer(1, 3*mm))
    if patient:
        elements.append(Paragraph(f"<b>Bill To:</b> {patient.name.title()} | {patient.age}yr | {patient.gender.capitalize()}", body_style))
        elements.append(Paragraph(f"<b>Patient ID:</b> {patient.patient_uid}", body_style))
    elements.append(Spacer(1, 5*mm))

    table_data = [
        ["Description", "Amount"],
        [Paragraph(note.reason, body_style), f"Rs.{note.amount:.2f}"],
        [f"Total {'Credited' if note.note_type == 'credit' else 'Debited'}", f"Rs.{note.amount:.2f}"],
    ]
    t = Table(table_data, colWidths=[130*mm, 40*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("GRID", (0, 0), (-1, 1), 0.4, colors.lightgrey),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#1a237e")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 6*mm))
    elements.append(Paragraph(
        f"This {title.lower()} is issued under GST law to "
        f"{'reduce' if note.note_type == 'credit' else 'increase'} the value of the original invoice referenced above. "
        f"This is a computer-generated document and does not require a physical signature.",
        ParagraphStyle("decl", fontSize=7.5, fontName="Helvetica", textColor=colors.grey, leading=10)
    ))

    header_text = f"{hospital.name if hospital else ''}  |  {patient.name.title() if patient else ''}  |  {note.note_number}"
    doc.build(elements, canvasmaker=_make_numbered_canvas(header_text))
    return filepath