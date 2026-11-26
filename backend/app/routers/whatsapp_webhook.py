"""Meta WhatsApp Cloud API webhook: verification handshake (GET) and delivery/status events (POST)."""
import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.config import settings

logger = logging.getLogger("whatsapp_webhook")
router = APIRouter(prefix="/webhooks/whatsapp", tags=["whatsapp-webhook"])


def _mask(phone: str) -> str:
    return ("*" * max(len(phone) - 4, 0)) + phone[-4:] if phone else ""


@router.get("")
def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta calls this once when you press Verify and save."""
    expected = settings.WHATSAPP_VERIFY_TOKEN
    if hub_mode == "subscribe" and expected and hmac.compare_digest(hub_verify_token or "", expected):
        return PlainTextResponse(hub_challenge or "")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("")
async def receive_webhook(request: Request):
    """Delivery receipts (sent / delivered / read / failed). Only calls signed by Meta are accepted."""
    secret = settings.WHATSAPP_APP_SECRET
    if not secret:
        raise HTTPException(status_code=403, detail="Webhook is not configured")
    raw = await request.body()
    sent_sig = request.headers.get("x-hub-signature-256", "")
    expected_sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sent_sig, expected_sig):
        raise HTTPException(status_code=403, detail="Bad signature")

    try:
        payload = json.loads(raw)
    except ValueError:
        return {"status": "ignored"}

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for st in change.get("value", {}).get("statuses", []):
                errors = st.get("errors") or []
                logger.info(
                    "WA status id=%s status=%s to=%s error=%s",
                    st.get("id"), st.get("status"), _mask(st.get("recipient_id", "")),
                    errors[0].get("code") if errors else None,
                )
    return {"status": "ok"}