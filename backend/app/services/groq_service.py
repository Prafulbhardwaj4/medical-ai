import json
import httpx
from app.config import settings

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """You are an AI medical scribe assistant for Indian doctors.
The transcript may be in Hindi, English, or any Indian language, or a mix (code-switching is common).
Regardless of input language, always output structured JSON in English only.
Translate all non-English terms — symptoms, medicine names, instructions — to English before structuring.

Return ONLY valid JSON with exactly these fields:
{
  "chief_complaint": "string - main symptoms/complaints in detail",
  "diagnosis": "string - diagnosis if mentioned, else empty string",
  "vitals": {
    "bp": "string - blood pressure e.g. 120/80, empty if not mentioned",
    "temperature": "string - e.g. 99°F or 37.2°C, empty if not mentioned",
    "pulse": "string - e.g. 78 bpm, empty if not mentioned",
    "weight": "string - e.g. 65 kg, empty if not mentioned",
    "spo2": "string - e.g. 98%, empty if not mentioned"
  },
  "medicines": [
    {
      "name": "string - generic medicine name e.g. Paracetamol",
      "brand_name": "string - brand name if mentioned by doctor e.g. Crocin, Dolo, empty string if not mentioned",
      "dosage": "string - strength e.g. 500mg, 10mg",
      "frequency": "string - detailed timing e.g. 'morning and night after food', 'once daily at bedtime', 'three times a day after meals', '30 minutes after first medicine'. Capture exact timing instructions including relative instructions like 'after 30 minutes of X'.",
      "duration": "string - e.g. 5 days, 1 week",
      "schedule": "string - either 'otc' or 'controlled'"
    }
  ],
  "tests": ["string - test name"],
  "advice": "string - all doctor advice, lifestyle instructions, dietary recommendations",
  "followup": "string - follow up instructions if mentioned, else empty string",
  "nurse_instructions": "string - any post-consultation tasks for the nurse mentioned by doctor: injections, dressings, IV fluids, wound care, etc. Empty string if not mentioned."
}

Rules for medicines:
- ALWAYS capture exact timing and food instructions in the frequency field — 'morning and night after food', 'at bedtime', 'on empty stomach', '30 minutes after Azithromycin' etc.
- If two medicines have a timing relationship (take one 30 min after another), capture that in the frequency field of the second medicine.
- brand_name: only fill if the doctor explicitly mentions a brand name. Leave empty string if only generic name used.
- name: always use the generic/chemical name. If only a brand name was said, convert to generic (e.g. Crocin → Paracetamol) and put the brand in brand_name.

Rules for schedule field:
- "controlled": antibiotics (azithromycin, amoxicillin etc.), benzodiazepines, opioids, sedatives, antipsychotics, steroids, habit-forming or antimicrobial-resistance-risk drugs.
- "otc": paracetamol, common antacids (pantoprazole, omeprazole), antihistamines (cetirizine, levocetirizine), vitamins, ORS, ibuprofen at standard OTC doses.
- If unsure, default to "controlled".

Other rules:
- medicines and tests must always be arrays (empty array [] if none mentioned)
- vitals fields must be empty strings if not mentioned — never invent values
- nurse_instructions: capture if doctor mentions nurse tasks — 'dressing karna hai', 'injection dena', 'IV lagana', 'wound dress karo', etc. Translate to English.
- Do not add any fields not listed above
- Do not include any explanation or markdown — only the raw JSON object
- If a field is not mentioned, use empty string or empty array
"""

async def structure_transcript(transcript: str, patient_history: str = "") -> dict:
    """Send transcript to Groq and return structured prescription as dict."""

    user_message = f"Consultation transcript:\n{transcript}"
    if patient_history:
        user_message = f"Patient history summary:\n{patient_history}\n\n{user_message}"

    headers = {
        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.1,
        "max_tokens": 1000
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(GROQ_API_URL, headers=headers, json=payload)

    if response.status_code != 200:
        raise Exception(f"Groq API error {response.status_code}: {response.text}")

    content = response.json()["choices"][0]["message"]["content"].strip()

    # Strip markdown code fences if model wraps response in them
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        raise Exception(f"Groq returned invalid JSON: {content}")


MEDICINE_EXTRACTION_PROMPT = """You are extracting a hospital's medicine formulary from raw text taken from a PDF or Excel file.
The text may be messy, tabular, or inconsistently formatted.

Return ONLY a valid JSON array. Each element must have exactly these fields:
{
  "generic_name": "string - generic/chemical name, required",
  "brand_names": "string - comma separated brand names if present, else empty string",
  "category": "string - drug category e.g. Antibiotic, Analgesic, empty string if unclear",
  "dosage_forms": "string - e.g. Tablet, Syrup, Injection, empty string if unclear",
  "schedule": "string - one of: otc, h, h1, x. Default to 'h' if unclear, 'otc' for common OTC drugs.",
  "pack_size": "number - units per strip/pack (e.g. 10 tablets per strip). Default to 1 if the source only gives a single item like a syrup bottle or injection vial, or if unclear.",
  "price_per_pack": "number or null - price for the whole strip/pack/bottle as printed in the source, else null",
  "gst_percent": "number or null - GST rate if explicitly present in source, else null",
  "stock_quantity": "number or null - stock count if present in source, else null"
}

Rules:
- Skip rows that are clearly headers, blank, or not medicines.
- Do not invent prices, pack sizes, or stock values that are not present in the source text.
- Do not include any explanation or markdown — only the raw JSON array.
"""


async def extract_medicines(raw_text: str) -> list:
    """Send raw extracted text (from PDF/Excel) to Groq and return a structured medicine list."""

    truncated = raw_text[:15000]

    headers = {
        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": MEDICINE_EXTRACTION_PROMPT},
            {"role": "user", "content": f"Source text:\n{truncated}"}
        ],
        "temperature": 0.1,
        "max_tokens": 4000
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(GROQ_API_URL, headers=headers, json=payload)

    if response.status_code != 200:
        raise Exception(f"Groq API error {response.status_code}: {response.text}")

    content = response.json()["choices"][0]["message"]["content"].strip()

    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        raise Exception(f"Groq returned invalid JSON: {content}")

    if not isinstance(result, list):
        raise Exception("Groq did not return a JSON array")

    return result


TEST_EXTRACTION_PROMPT = """You are extracting a hospital's diagnostic test/lab catalog from raw text taken from a PDF or Excel file.
The text may be messy, tabular, or inconsistently formatted.

Return ONLY a valid JSON array. Each element must have exactly these fields:
{
  "test_name": "string - name of the test, required",
  "category": "string - e.g. Hematology, Biochemistry, Radiology, empty string if unclear",
  "price": "number or null - test fee if present in source, else null",
  "reference_range_male": "string - normal reference range for male patients, empty string if not present",
  "reference_range_female": "string - normal reference range for female patients, empty string if not present",
  "unit": "string - unit of measurement e.g. mg/dL, empty string if not present",
  "turnaround_hours": "number or null - turnaround time in hours if present, else null"
}

Rules:
- Skip rows that are clearly headers, blank, or not tests.
- Do not invent prices, ranges, or turnaround times that are not present in the source text.
- Do not include any explanation or markdown — only the raw JSON array.
"""


async def extract_tests(raw_text: str) -> list:
    """Send raw extracted text (from PDF/Excel) to Groq and return a structured test list."""

    truncated = raw_text[:15000]

    headers = {
        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": TEST_EXTRACTION_PROMPT},
            {"role": "user", "content": f"Source text:\n{truncated}"}
        ],
        "temperature": 0.1,
        "max_tokens": 4000
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(GROQ_API_URL, headers=headers, json=payload)

    if response.status_code != 200:
        raise Exception(f"Groq API error {response.status_code}: {response.text}")

    content = response.json()["choices"][0]["message"]["content"].strip()

    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        raise Exception(f"Groq returned invalid JSON: {content}")

    if not isinstance(result, list):
        raise Exception("Groq did not return a JSON array")

    return result