"""Transport acceptance and phase uncertainty tested without external accounts."""

from dataclasses import replace
import smtplib
from uuid import uuid4

import httpx
import pytest
from app.services import outbound


@pytest.mark.parametrize(
    "status,headers,payload,expected",
    [
        (200, {"x-line-request-id": "abc"}, {}, "accepted"),
        (409, {"x-line-accepted-request-id": str(uuid4())}, {}, "accepted"),
        (409, {}, {}, "unknown"),
        (429, {}, {"message": "Monthly limit exceeded"}, "failed"),
        (429, {}, {"message": "Rate limit exceeded"}, "retry"),
        (500, {}, {}, "retry"),
        (403, {}, {}, "failed"),
        (400, {}, {}, "failed"),
    ],
)
def test_line_retry_key_status_acceptance(
    monkeypatch, status, headers, payload, expected
):
    key = str(uuid4())
    requests = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs == {
                "timeout": 15,
                "trust_env": False,
                "follow_redirects": False,
            }

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            requests.append(kwargs)
            assert url == "https://api.line.me/v2/bot/message/push"
            return httpx.Response(status, headers=headers, json=payload)

    monkeypatch.setattr(outbound.httpx, "Client", Client)
    assert outbound.line_push("configured-id", "message", key).status == expected
    assert requests[0]["headers"]["X-Line-Retry-Key"] == key


@pytest.mark.parametrize(
    "phase,expected",
    [
        ("connect", "retry"),
        ("mail4", "retry"),
        ("mail5", "failed"),
        ("rcpt4", "retry"),
        ("rcpt5", "failed"),
        ("data_disconnect", "unknown"),
        ("data5", "unknown"),
        ("accepted", "accepted"),
    ],
)
def test_smtp_explicit_tls_envelope_data_boundary(monkeypatch, phase, expected):
    events = []
    monkeypatch.setattr(
        outbound,
        "settings",
        replace(
            outbound.settings,
            reminder_smtp_tls="starttls",
            reminder_smtp_host="smtp.test",
            reminder_smtp_from="desk@example.test",
            reminder_smtp_user="desk",
            reminder_smtp_password="secret",
        ),
    )

    class SMTP:
        def __init__(self, *args, **kwargs):
            events.append("connect")
            if phase == "connect":
                raise OSError("synthetic")

        def ehlo_or_helo_if_needed(self):
            events.append("ehlo")

        def starttls(self, context):
            events.append("tls")

        def ehlo(self):
            events.append("ehlo2")

        def login(self, *args):
            events.append("auth")

        def mail(self, *args):
            events.append("mail")
            return (450 if phase == "mail4" else 550 if phase == "mail5" else 250, b"")

        def rcpt(self, *args):
            events.append("rcpt")
            return (450 if phase == "rcpt4" else 550 if phase == "rcpt5" else 250, b"")

        def data(self, body):
            events.append("data")
            assert b"Message-ID: <stable@travel.test>" in body
            if phase == "data_disconnect":
                raise smtplib.SMTPServerDisconnected("synthetic")
            return (550 if phase == "data5" else 250, b"")

        def close(self):
            events.append("close")

    monkeypatch.setattr(outbound.smtplib, "SMTP", SMTP)
    assert (
        outbound.smtp_send(
            "guest@example.test", "message", "<stable@travel.test>"
        ).status
        == expected
    )
    if phase != "connect":
        assert events[:5] == ["connect", "ehlo", "tls", "ehlo2", "auth"]
    if phase.startswith(("mail", "rcpt")):
        assert "data" not in events
