from __future__ import annotations

import json
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.db import connect
from app.models import now_iso


FORBIDDEN_KEYS = {
    "card_number", "credit_card", "creditcard", "cardnumber",
    "cvv", "cvc", "security_code", "securitycode",
}


def _find_forbidden_keys(value, path: str = "$") -> list[str]:
    """Recursively find forbidden payment-card fields in nested JSON-like data."""

    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
            if normalized in FORBIDDEN_KEYS:
                found.append(f"{path}.{key}")
            found.extend(_find_forbidden_keys(child, f"{path}.{key}"))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            found.extend(_find_forbidden_keys(child, f"{path}[{index}]"))
    return found


def _cipher() -> Fernet | None:
    return Fernet(settings.pii_fernet_key.encode()) if settings.pii_fernet_key else None


def save_pii(case_id: str, payload: dict) -> None:
    forbidden = _find_forbidden_keys(payload)
    if forbidden:
        raise ValueError("信用卡/CVV 不允許存入 Travel Desk")
    c = _cipher()
    if not c:
        raise RuntimeError("PII_FERNET_KEY 尚未設定，拒絕保存敏感資料")
    token = c.encrypt(json.dumps(payload, ensure_ascii=False).encode())
    with connect() as db:
        db.execute(
            "INSERT INTO pii_vault(case_id,encrypted_payload,updated_at) VALUES(?,?,?) ON CONFLICT(case_id) DO UPDATE SET encrypted_payload=excluded.encrypted_payload,updated_at=excluded.updated_at",
            (case_id, token, now_iso()),
        )
        db.commit()


def load_pii(case_id: str) -> dict | None:
    c = _cipher()
    if not c:
        return None
    with connect() as db:
        row = db.execute("SELECT encrypted_payload FROM pii_vault WHERE case_id=?", (case_id,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(c.decrypt(row[0]).decode())
    except InvalidToken:
        raise RuntimeError("PII vault key 不正確或資料損毀")
