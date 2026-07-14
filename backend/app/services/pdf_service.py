import os
import json
from app.utils.auth import now_ist
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
import qrcode
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image
import io

PRESCRIPTIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "prescriptions")
REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "reports")

def ensure_dir():
    os.makedirs(PRESCRIPTIONS_DIR, exist_ok=True)

def ensure_reports_dir():
    os.makedirs(REPORTS_DIR, exist_ok=True)

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
                Paragraph(m.get("duration", "-"), med_cell_style),
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

        verify_url = f"https://medical-s-ai.vercel.app/pages/verify.html?token={token_number}&hash={verify_hash}"
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

    doc.build(elements)
    return filepath

def generate_test_report_pdf(
    order: object,
    patient: object,
    catalog_item: object,
    ordering_doctor: object,
    lab_staff: object,
    hospital_name: str
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

    elements.append(Paragraph(hospital_name, header_style))
    elements.append(Spacer(1, 2*mm))
    elements.append(Paragraph("Laboratory Test Report", sub_style))
    elements.append(Spacer(1, 3*mm))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1a237e")))
    elements.append(Spacer(1, 4*mm))

    bg = f" | Blood Group: {patient.blood_group}" if patient.blood_group else ""
    elements.append(Paragraph(
        f"<b>Patient:</b> {patient.name.title()} | {patient.age}yr | {patient.gender.capitalize()}{bg}",
        styles["Normal"]
    ))
    elements.append(Paragraph(f"<b>Patient ID:</b> {patient.patient_uid}", styles["Normal"]))
    elements.append(Paragraph(f"<b>Report Date:</b> {now_ist().strftime('%d %b %Y')}", styles["Normal"]))
    elements.append(Spacer(1, 4*mm))
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

    if notes:
        elements.append(Paragraph("Notes", section_style))
        elements.append(Paragraph(notes, body_style))
        elements.append(Spacer(1, 4*mm))

    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    elements.append(Spacer(1, 4*mm))

    footer_style = ParagraphStyle("footer", fontSize=9, fontName="Helvetica", textColor=colors.HexColor("#334155"))
    elements.append(Paragraph(
        f"<b>Ordering Doctor:</b> {ordering_doctor.title} {ordering_doctor.name}" if ordering_doctor else "<b>Ordering Doctor:</b> —",
        footer_style
    ))
    elements.append(Paragraph(
        f"<b>Lab Staff:</b> {lab_staff.name}" if lab_staff else "<b>Lab Staff:</b> —",
        footer_style
    ))

    doc.build(elements)
    return filepath

def generate_invoice_pdf(invoice_id: int, hospital, items: list, grand_total: float, patient) -> str:
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

    header_style = ParagraphStyle("header", fontSize=18, fontName="Helvetica-Bold", alignment=TA_CENTER, textColor=colors.HexColor("#1a237e"))
    sub_style = ParagraphStyle("sub", fontSize=9, fontName="Helvetica", alignment=TA_CENTER, textColor=colors.grey)

    elements.append(Paragraph(hospital.name, header_style))
    if hospital.address:
        elements.append(Paragraph(hospital.address, sub_style))
    if hospital.gstin:
        elements.append(Paragraph(f"GSTIN: {hospital.gstin}", sub_style))
    elements.append(Spacer(1, 3*mm))
    elements.append(Paragraph("INVOICE", ParagraphStyle("inv", fontSize=13, fontName="Helvetica-Bold", alignment=TA_CENTER)))
    elements.append(Spacer(1, 4*mm))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a237e")))
    elements.append(Spacer(1, 4*mm))

    elements.append(Paragraph(f"<b>Patient:</b> {patient.name.title()} | {patient.age}yr | {patient.gender.capitalize()}", styles["Normal"]))
    elements.append(Paragraph(f"<b>Patient ID:</b> {patient.patient_uid}", styles["Normal"]))
    elements.append(Paragraph(f"<b>Invoice #:</b> INV-{invoice_id} &nbsp;&nbsp; <b>Date:</b> {now_ist().strftime('%d %b %Y, %I:%M %p')}", styles["Normal"]))
    elements.append(Spacer(1, 5*mm))

    table_data = [["Description", "Qty", "Unit Price", "Amount"]]
    for item in items:
        table_data.append([
            item["name"],
            str(item.get("qty", 1)),
            f"Rs.{item['unit_price']:.2f}",
            f"Rs.{item['line_total']:.2f}"
        ])
    table_data.append(["", "", "Grand Total", f"Rs.{grand_total:.2f}"])

    t = Table(table_data, colWidths=[85*mm, 20*mm, 30*mm, 30*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("GRID", (0, 0), (-1, -2), 0.4, colors.lightgrey),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#1a237e")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 8*mm))
    elements.append(Paragraph("Thank you for visiting.", ParagraphStyle("thanks", fontSize=9, alignment=TA_CENTER, textColor=colors.grey)))

    doc.build(elements)
    return filepath