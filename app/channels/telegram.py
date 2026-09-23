from __future__ import annotations

import hashlib
import hmac
import json

import httpx
from fastapi import HTTPException

from app.config import settings
from app.models import ChannelReply
from app.repositories import inbound_event_repo
from app.services.channel_router import route_channel_message


def _callback_data(option: str) -> str:
    # Telegram callback_data is capped at 64 bytes. Current menu labels fit, but keep
    # a deterministic compact fallback for future longer labels.
    value = f"guided:{option}"
    if len(value.encode("utf-8")) <= 64:
        return value
    digest = hashlib.sha256(option.encode("utf-8")).hexdigest()[:16]
    return f"guided-hash:{digest}"


def _keyboard(options: list[str]) -> dict | None:
    if not options:
        return None
    rows = [[{"text": option, "callback_data": _callback_data(option)}] for option in options[:10]]
    return {"inline_keyboard": rows}


def _event_identity(payload: dict) -> tuple[str, str]:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    event_id = str(payload.get("update_id") or f"sha256:{payload_hash}")
    return event_id, payload_hash


def verify_webhook_secret(secret_header: str | None) -> None:
    """Require Telegram's setWebhook secret-token header when the channel is enabled."""

    if not settings.telegram_enabled:
        return
    expected = settings.telegram_webhook_secret
    if not expected:
        raise HTTPException(503, "Telegram webhook secret is required")
    if not secret_header or not hmac.compare_digest(secret_header, expected):
        raise HTTPException(401, "invalid Telegram webhook secret")


async def _telegram_call(method: str, payload: dict) -> None:
    if not settings.telegram_enabled or not settings.telegram_bot_token:
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()


async def send(chat_id: str, text: str, options: list[str]) -> None:
    payload: dict = {"chat_id": chat_id, "text": text[:4096]}
    keyboard = _keyboard(options)
    if keyboard:
        payload["reply_markup"] = keyboard
    await _telegram_call("sendMessage", payload)


async def answer_callback(callback_query_id: str) -> None:
    if callback_query_id:
        await _telegram_call("answerCallbackQuery", {"callback_query_id": callback_query_id})


async def handle_telegram(payload: dict, secret_header: str | None = None) -> dict:
    if not settings.telegram_enabled:
        return {"ok": False, "disabled": True, "handled": 0, "duplicates": 0}
    verify_webhook_secret(secret_header)
    if not settings.telegram_allowed_chat_ids:
        return {"ok": False, "misconfigured": "allowlist_required", "handled": 0, "duplicates": 0}
    message = payload.get("message")
    callback = payload.get("callback_query")
    if callback:
        chat_id = str(callback.get("message", {}).get("chat", {}).get("id", ""))
        raw_data = str(callback.get("data", ""))
        if raw_data.startswith("guided-hash:"):
            # Long labels are not currently emitted by the Mom menu. Do not guess a
            # label from a hash; ask the user to reopen the menu instead.
            text = "主選單"
        else:
            text = raw_data.removeprefix("guided:")
        await answer_callback(str(callback.get("id", "")))
    elif message:
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = str(message.get("text", ""))
    else:
        return {"ok": True, "handled": 0, "duplicates": 0}

    if chat_id not in settings.telegram_allowed_chat_ids:
        return {"ok": True, "handled": 0, "duplicates": 0}

    event_id, payload_hash = _event_identity(payload)
    state, saved_response = inbound_event_repo.claim("telegram", event_id, payload_hash)
    if state in {"delivered", "busy"}:
        return {"ok": True, "handled": 0, "duplicates": 1}
    if state == "collision":
        return {"ok": False, "handled": 0, "duplicates": 0, "error": "event_id_collision"}

    if state == "replay" and saved_response:
        answer = ChannelReply.model_validate(saved_response)
    else:
        session_id = f"telegram:{chat_id}"
        answer = await route_channel_message(session_id, text)
        inbound_event_repo.store_response("telegram", event_id, answer.model_dump(mode="json"))

    try:
        await send(chat_id, answer.text, answer.options)
    except Exception:
        inbound_event_repo.mark_delivery_failed("telegram", event_id)
        raise
    inbound_event_repo.mark_delivered("telegram", event_id)
    return {"ok": True, "handled": 1, "duplicates": 0}
