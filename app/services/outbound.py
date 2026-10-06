"""Bounded transports: provider acceptance is distinct from recipient delivery."""

from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTP as SMTP_POLICY
from email.headerregistry import Address
import smtplib
import ssl
from uuid import UUID

import httpx

from app.config import settings


@dataclass(frozen=True)
class Delivery:
    status: str
    error_code: str | None = None
    provider_request_id: str | None = None


def line_push(recipient, body, retry_key):
    headers = {
        "Authorization": "Bearer " + settings.line_channel_access_token,
        "X-Line-Retry-Key": retry_key,
    }
    try:
        with httpx.Client(
            timeout=15, trust_env=False, follow_redirects=False
        ) as client:
            response = client.post(
                "https://api.line.me/v2/bot/message/push",
                headers=headers,
                json={"to": recipient, "messages": [{"type": "text", "text": body}]},
            )
    except httpx.HTTPError:
        # A stable retry key is mandatory; this outcome may already have been accepted.
        return Delivery("retry", "line_connection")
    if response.status_code == 200:
        return Delivery(
            "accepted", provider_request_id=response.headers.get("x-line-request-id")
        )
    if response.status_code == 409:
        accepted = response.headers.get("x-line-accepted-request-id", "")
        try:
            UUID(accepted)
        except (ValueError, TypeError):
            return Delivery("unknown", "line_conflict_unconfirmed")
        return Delivery("accepted", provider_request_id=accepted)
    if response.status_code == 429:
        try:
            message = str(response.json().get("message", "")).lower()
        except (ValueError, AttributeError):
            message = ""
        if "monthly" in message or "quota" in message:
            return Delivery("failed", "line_quota")
        return Delivery("retry", "line_rate_limit")
    if response.status_code >= 500:
        return Delivery("retry", "line_service")
    return Delivery("failed", "line_rejected")


def smtp_send(recipient, body, message_id):
    """Never automatically repeat an email whose DATA acceptance is uncertain."""
    if settings.reminder_smtp_tls not in {"ssl", "starttls"}:
        return Delivery("failed", "smtp_tls_required")
    smtp = None
    data_started = False
    try:
        if any(
            "\n" in v or "\r" in v
            for v in (settings.reminder_smtp_from, recipient, message_id)
        ):
            return Delivery("failed", "smtp_header")
        message = EmailMessage(policy=SMTP_POLICY)
        message["From"] = Address(addr_spec=settings.reminder_smtp_from)
        message["To"] = Address(addr_spec=recipient)
        message["Subject"] = "旅行工作期限提醒"
        message["Message-ID"] = message_id
        message.set_content(body)
        tls = ssl.create_default_context()
        if settings.reminder_smtp_tls == "ssl":
            smtp = smtplib.SMTP_SSL(
                settings.reminder_smtp_host,
                settings.reminder_smtp_port,
                timeout=15,
                context=tls,
            )
        else:
            smtp = smtplib.SMTP(
                settings.reminder_smtp_host, settings.reminder_smtp_port, timeout=15
            )
        smtp.ehlo_or_helo_if_needed()
        if settings.reminder_smtp_tls == "starttls":
            smtp.starttls(context=tls)
            smtp.ehlo()
        if settings.reminder_smtp_user:
            smtp.login(settings.reminder_smtp_user, settings.reminder_smtp_password)
        code, _ = smtp.mail(settings.reminder_smtp_from)
        if not 200 <= code < 300:
            return Delivery(
                "retry" if 400 <= code < 500 else "failed", "smtp_mail_rejected"
            )
        code, _ = smtp.rcpt(recipient)
        if not 200 <= code < 300:
            return Delivery(
                "retry" if 400 <= code < 500 else "failed", "smtp_recipient_rejected"
            )
        data_started = True
        code, _ = smtp.data(message.as_bytes())
        return (
            Delivery("accepted")
            if 200 <= code < 300
            else Delivery("unknown", "smtp_data_unconfirmed")
        )
    except smtplib.SMTPResponseException as exc:
        if data_started:
            return Delivery("unknown", "smtp_data_unconfirmed")
        return Delivery(
            "retry" if 400 <= exc.smtp_code < 500 else "failed", "smtp_rejected"
        )
    except (OSError, smtplib.SMTPException):
        return Delivery("unknown" if data_started else "retry", "smtp_connection")
    except (ValueError, UnicodeError):
        return Delivery("unknown" if data_started else "failed", "smtp_invalid_message")
    finally:
        if smtp is not None:
            # A failed QUIT must not turn an explicitly accepted DATA response into uncertainty.
            try:
                smtp.close()
            except OSError:
                pass


def send(channel, recipient, body, retry_key, message_id):
    return (
        line_push(recipient, body, retry_key)
        if channel == "line"
        else smtp_send(recipient, body, message_id)
    )
