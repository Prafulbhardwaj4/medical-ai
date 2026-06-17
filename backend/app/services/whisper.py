import httpx
from app.config import settings


async def transcribe_audio(file_bytes: bytes, filename: str) -> str:
    """Send audio to Groq Whisper API and return transcript."""

    url = "https://api.groq.com/openai/v1/audio/transcriptions"

    headers = {
        "Authorization": f"Bearer {settings.GROQ_API_KEY}"
    }

    files = {
        "file": (filename, file_bytes, "audio/webm")
    }

    data = {
        "model": "whisper-large-v3-turbo",
        "response_format": "text"
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, headers=headers, files=files, data=data)

    if response.status_code != 200:
        raise Exception(f"Groq Whisper error {response.status_code}: {response.text}")

    return response.text.strip()


async def translate_to_english(transcript: str) -> str:
    """Translate any Indian language transcript to English using Groq."""
    if not transcript or not transcript.strip():
        return transcript

    # Skip if already mostly English
    english_chars = sum(1 for c in transcript if ord(c) < 128)
    if english_chars / len(transcript) > 0.8:
        return transcript

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    groq_payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {
                "role": "system",
                "content": "You are a medical translator. Translate the following doctor-patient conversation transcript to English. Keep all medical terms, medicine names, dosages, and numbers exactly as they are. Output only the translated text, nothing else."
            },
            {
                "role": "user",
                "content": transcript
            }
        ],
        "temperature": 0.1,
        "max_tokens": 2000
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, headers=headers, json=groq_payload)

    if response.status_code != 200:
        return transcript

    return response.json()["choices"][0]["message"]["content"].strip()