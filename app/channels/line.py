from __future__ import annotations

import base64
import hashlib
import hmac
import json

import httpx
from fastapi import HTTPException, Request

from app.config import settings
from app.models import ChannelReply
from app.repositories import inbound_event_repo
from app.services.channel_router import route_channel_message


def verify_signature(body: bytes, signature: str | None) -> None:
    if not settings.line_enabled:
        return
    if not signature or not settings.line_channel_secret:
        raise HTTPException(401, "missing LINE signature")
    digest = hmac.new(settings.line_channel_secret.encode(), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "invalid LINE signature")


def _quick_reply(options: list[str]) -> dict | None:
    if not options:
        return None
    return {
        "items": [
            {"type": "action", "action": {"type": "message", "label": option[:20], "text": option}}
            for option in options[:13]
        ]
    }


def _event_identity(event: dict) -> tuple[str, str]:
    canonical = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    event_id = str(
        event.get("webhookEventId")
        or event.get("message", {}).get("id")
        or f"sha256:{payload_hash}"
    )
    return event_id, payload_hash


async def reply_line(reply_token: str, text: str, options: list[str]) -> None:
    if not settings.line_enabled or not settings.line_channel_access_token:
        return
    if not reply_token:
        raise ValueError("missing LINE reply token")
    message: dict = {"type": "text", "text": text[:5000]}
    quick_reply = _quick_reply(options)
    if quick_reply:
        message["quickReply"] = quick_reply
    headers = {
        "Authorization": f"Bearer {settings.line_channel_access_token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            "https://api.line.me/v2/bot/message/reply",
            headers=headers,
            json={"replyToken": reply_token, "messages": [message]},
        )
        response.raise_for_status()


async def handle_line(request: Request) -> dict:
    if not settings.line_enabled:
        raise HTTPException(503, "LINE channel is disabled")
    if not settings.line_allowed_user_ids:
        raise HTTPException(503, "LINE allowlist is required")
    body = await request.body()
    verify_signature(body, request.headers.get("x-line-signature"))
    payload = await request.json()
    handled = 0
    duplicates = 0

    for event in payload.get("events", []):
        if event.get("type") != "message" or event.get("message", {}).get("type") != "text":
            continue
        source = event.get("source", {})
        user_id = source.get("userId", "unknown")
        if user_id not in settings.line_allowed_user_ids:
            continue

        event_id, payload_hash = _event_identity(event)
        state, saved_response = inbound_event_repo.claim("line", event_id, payload_hash)
        if state in {"delivered", "busy"}:
            duplicates += 1
            continue
        if state == "collision":
            raise HTTPException(409, "LINE event id collision")

        if state == "replay" and saved_response:
            answer = ChannelReply.model_validate(saved_response)
        else:
            session_id = f"line:{user_id}"
            answer = await route_channel_message(session_id, event["message"]["text"])
            inbound_event_repo.store_response("line", event_id, answer.model_dump(mode="json"))

        try:
            await reply_line(event.get("replyToken", ""), answer.text, answer.options)
        except Exception:
            inbound_event_repo.mark_delivery_failed("line", event_id)
            raise
        inbound_event_repo.mark_delivered("line", event_id)
        handled += 1

    return {"ok": True, "handled": handled, "duplicates": duplicates}
