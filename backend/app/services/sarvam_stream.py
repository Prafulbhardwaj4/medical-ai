import asyncio
import base64
import json
import websockets
from urllib.parse import urlencode
from app.config import settings

SARVAM_STT_BASE = "wss://api.sarvam.ai/speech-to-text/ws"
SARVAM_TRANSLATE_BASE = "wss://api.sarvam.ai/speech-to-text-translate/ws"

async def stream_transcribe(
    audio_queue: asyncio.Queue,
    transcript_queue: asyncio.Queue,
    language_code: str = "unknown",
    translate: bool = True,
):
    params = {
        "model": "saaras:v3",
        "language-code": language_code,
        "sample_rate": 16000,
        "input_audio_codec": "wav",
    }
    if translate:
        base_url = SARVAM_TRANSLATE_BASE
    else:
        params["mode"] = "transcribe"
        base_url = SARVAM_STT_BASE

    url = f"{base_url}?{urlencode(params)}"
    headers = {"api-subscription-key": settings.SARVAM_API_KEY}

    try:
        async with websockets.connect(
            url,
            additional_headers=headers,
            ping_interval=None,
            close_timeout=10,
            max_size=10 * 1024 * 1024
        ) as ws:

            async def send_audio():
                while True:
                    chunk = await audio_queue.get()
                    if chunk is None:
                        try:
                            await ws.close()
                        except Exception:
                            pass
                        break
                    try:
                        payload = {
                            "audio": {
                                "data": base64.b64encode(chunk).decode(),
                                "sample_rate": 16000,
                                "encoding": "audio/wav",
                            }
                        }
                        await ws.send(json.dumps(payload))
                    except Exception:
                        break

            async def receive_transcript():
                try:
                    async for message in ws:
                        try:
                            data = json.loads(message)
                            if data.get("type") == "data":
                                inner = data.get("data", {})
                                text = inner.get("transcript", "")
                                if text:
                                    await transcript_queue.put({
                                        "type": "transcript",
                                        "text": text,
                                    })
                        except Exception:
                            continue
                except Exception:
                    pass

            await asyncio.gather(send_audio(), receive_transcript())

    except websockets.exceptions.ConnectionClosedError as e:
        await transcript_queue.put({"type": "error", "message": f"Connection closed: code={e.code} reason={e.reason}"})
    except Exception as e:
        await transcript_queue.put({"type": "error", "message": str(e)})
    finally:
        await transcript_queue.put({"type": "end"})