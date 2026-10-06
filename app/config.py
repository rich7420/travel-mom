from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _csv(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    return tuple(x.strip() for x in raw.split(",") if x.strip())


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "dev")
    db_path: str = os.getenv("TRAVEL_DESK_DB", "./data/travel_desk.db")
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
    auth_mode: str = os.getenv("AUTH_MODE", "token").strip().lower()
    cloudflare_access_issuer: str = os.getenv("CLOUDFLARE_ACCESS_ISSUER", "").strip().rstrip("/")
    cloudflare_access_audience: str = os.getenv("CLOUDFLARE_ACCESS_AUDIENCE", "").strip()
    cloudflare_access_emails: tuple[str, ...] = _csv("CLOUDFLARE_ACCESS_EMAILS")
    cloudflare_access_admin_emails: tuple[str, ...] = _csv("CLOUDFLARE_ACCESS_ADMIN_EMAILS")
    admin_token: str = os.getenv("TRAVEL_DESK_ADMIN_TOKEN", "")
    max_request_body_bytes: int = int(os.getenv("MAX_REQUEST_BODY_BYTES", "1000000"))
    inbound_event_lease_seconds: int = int(os.getenv("INBOUND_EVENT_LEASE_SECONDS", "120"))

    openclaw_enabled: bool = _bool("OPENCLAW_ENABLED")
    openclaw_base_url: str = os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789").rstrip("/")
    openclaw_gateway_token: str = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
    openclaw_agent_id: str = os.getenv("OPENCLAW_AGENT_ID", "mom-travel")
    openclaw_model: str = os.getenv("OPENCLAW_MODEL", "openclaw/mom-travel")
    openclaw_browser_model: str = os.getenv("OPENCLAW_BROWSER_MODEL", "openclaw/mom-travel-browser")
    openclaw_browser_profile: str = os.getenv("OPENCLAW_BROWSER_PROFILE", "openclaw")

    line_enabled: bool = _bool("LINE_ENABLED")
    line_channel_access_token: str = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    line_channel_secret: str = os.getenv("LINE_CHANNEL_SECRET", "")
    line_allowed_user_ids: tuple[str, ...] = _csv("LINE_ALLOWED_USER_IDS")

    telegram_enabled: bool = _bool("TELEGRAM_ENABLED")
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_webhook_secret: str = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    telegram_allowed_chat_ids: tuple[str, ...] = _csv("TELEGRAM_ALLOWED_CHAT_IDS")

    reminders_enabled: bool = _bool('REMINDERS_ENABLED')
    reminder_line_enabled: bool = _bool('REMINDER_LINE_ENABLED')
    reminder_smtp_enabled: bool = _bool('REMINDER_SMTP_ENABLED')
    reminder_staff_emails: tuple[str,...] = _csv('REMINDER_STAFF_EMAILS')
    reminder_grace_minutes: int = int(os.getenv('REMINDER_GRACE_MINUTES','30'))
    reminder_smtp_host: str = os.getenv('REMINDER_SMTP_HOST','')
    reminder_smtp_port: int = int(os.getenv('REMINDER_SMTP_PORT','465'))
    reminder_smtp_tls: str = os.getenv('REMINDER_SMTP_TLS','ssl')
    reminder_smtp_user: str = os.getenv('REMINDER_SMTP_USER','')
    reminder_smtp_password: str = os.getenv('REMINDER_SMTP_PASSWORD','')
    reminder_smtp_from: str = os.getenv('REMINDER_SMTP_FROM','')

    pii_fernet_key: str = os.getenv("PII_FERNET_KEY", "")
    attachments_dir: str = os.getenv("ATTACHMENTS_DIR", "")
    backup_dir: str = os.getenv("BACKUP_DIR", "")
    browser_allowed_domains: tuple[str, ...] = _csv("BROWSER_ALLOWED_DOMAINS")
    browser_lab_ingest_enabled: bool = _bool("BROWSER_LAB_INGEST_ENABLED", True)
    price_revalidation_max_age_minutes: int = int(os.getenv("PRICE_REVALIDATION_MAX_AGE_MINUTES", "20"))
    price_change_acceptance_threshold_twd: int = int(os.getenv("PRICE_CHANGE_ACCEPTANCE_THRESHOLD_TWD", "0"))
    quote_max_age_hours: int = int(os.getenv("QUOTE_MAX_AGE_HOURS", "24"))


settings = Settings()
