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

def ensure_dir():
    os.makedirs(PRESCRIPTIONS_DIR, exist_ok=True)

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

        med_data = [["Medicine", "Brand Name", "Dosage", "Frequency", "Duration", "Type"]]
        has_controlled = False
        for m in medicines:
            schedule = m.get("schedule", "controlled")
            if schedule == "controlled":
                has_controlled = True
            type_label = "Rx" if schedule == "controlled" else "OTC"
            med_data.append([
                Paragraph(cap_sentence(m.get("name", "")), med_cell_style),
                Paragraph(cap_sentence(m.get("brand_name", "—")), med_cell_style),
                Paragraph(m.get("dosage", ""), med_cell_style),
                Paragraph(cap_sentence(m.get("frequency", "")), med_cell_style),
                Paragraph(m.get("duration", "-"), med_cell_style),
                type_label
            ])

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
            ("FONTNAME", (5, 1), (5, -1), "Helvetica-Bold"),
            ("ALIGN", (5, 0), (5, -1), "CENTER"),
        ]

        for idx, m in enumerate(medicines, start=1):
            schedule = m.get("schedule", "controlled")
            color = colors.HexColor("#dc2626") if schedule == "controlled" else colors.HexColor("#16a34a")
            med_table_style.append(("TEXTCOLOR", (5, idx), (5, idx), color))

        med_table = Table(med_data, colWidths=[38*mm, 26*mm, 20*mm, 52*mm, 22*mm, 12*mm])   
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