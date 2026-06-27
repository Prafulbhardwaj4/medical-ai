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

    pending_chunks = []
    done = False

    while not done:
        try:
            async with websockets.connect(
                url,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=30,
                close_timeout=10
            ) as ws:

                async def send_audio():
                    nonlocal done
                    # Send any pending chunks from previous connection
                    for chunk in pending_chunks:
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
                            return
                    pending_chunks.clear()

                    while True:
                        chunk = await audio_queue.get()
                        if chunk is None:
                            done = True
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
                            # Connection dropped — save chunk and reconnect
                            pending_chunks.append(chunk)
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

        except Exception as e:
            if done:
                break
            # Wait briefly before reconnecting
            await asyncio.sleep(1)

    await transcript_queue.put({"type": "end"})