import json
import httpx
from app.config import settings

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """You are an AI medical scribe assistant. 
The transcript may be in Hindi, English, Tamil, Telugu, Bengali, Marathi, Gujarati, Kannada, Malayalam, Punjabi, or any other Indian language, or a mix of multiple languages.
Regardless of the input language, always extract and output the structured JSON in English only.
Translate any non-English medical terms, symptoms, medicine names, and instructions to English before structuring.
Extract and structure the following medical consultation transcript into a JSON object.

Return ONLY valid JSON with exactly these fields:
{
  "chief_complaint": "string - main symptoms/complaints",
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
      "name": "string - medicine name",
      "dosage": "string - e.g. 500mg",
      "frequency": "string - e.g. twice daily",
      "duration": "string - e.g. 5 days",
      "schedule": "string - either 'otc' or 'controlled'"
    }
  ],
  "tests": ["string - test name", "string - test name"],
  "advice": "string - doctor advice/notes",
  "followup": "string - follow up instructions if mentioned, else empty string"
}

Rules for "schedule" field on each medicine:
- Mark as "controlled" if the medicine is commonly a Schedule H1/X drug in India — includes: most antibiotics (azithromycin, amoxicillin, etc.), benzodiazepines (alprazolam, diazepam, clonazepam), opioids (tramadol, codeine), sedatives, antipsychotics, steroids (prednisolone, dexamethasone), and any habit-forming or antimicrobial-resistance-risk drugs.
- Mark as "otc" for: paracetamol, common antacids (pantoprazole, omeprazole), antihistamines (cetirizine, levocetirizine), vitamins, ORS, common topical creams/lotions, ibuprofen at standard OTC doses.
- If unsure, default to "controlled" (safer default).

Other rules:
- medicines and tests must always be arrays (empty array if none mentioned)
- vitals fields should be empty strings if not mentioned in transcript — do not invent values
- Do not add any fields not listed above
- Do not include any explanation or markdown, only the raw JSON object
- If a field is not mentioned in the transcript, use empty string or empty array
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