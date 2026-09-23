from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet

from app.db import connect, init_db
from app.repositories import browser_attempt_repo, inbound_event_repo
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_sqlite_context_always_closes_connection():
    init_db()
    raw = None
    with connect() as db:
        raw = db
        assert db.execute("SELECT 1").fetchone()[0] == 1
    assert raw is not None
    with pytest.raises(sqlite3.ProgrammingError):
        raw.execute("SELECT 1")


def test_recursive_payment_card_fields_are_rejected(monkeypatch):
    import app.services.pii as pii

    monkeypatch.setattr(
        pii,
        "settings",
        replace(pii.settings, pii_fernet_key=Fernet.generate_key().decode()),
    )
    with pytest.raises(ValueError, match="信用卡"):
        pii.save_pii(
            "trip_nested_card",
            {
                "traveler": {"name": "測試"},
                "payment": {
                    "wallet": [
                        {"provider": "manual"},
                        {"card_number": "4111111111111111", "cvv": "123"},
                    ]
                },
            },
        )


def test_stale_webhook_processing_lease_can_be_reclaimed(monkeypatch):
    import app.repositories as repositories

    monkeypatch.setattr(
        repositories,
        "settings",
        replace(repositories.settings, inbound_event_lease_seconds=1),
    )
    event_id = "review-stale-event"
    state, _ = inbound_event_repo.claim("line", event_id, "hash-1")
    assert state == "new"

    old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    with connect() as db:
        db.execute(
            "UPDATE inbound_events SET updated_at=? WHERE channel=? AND event_id=?",
            (old, "line", event_id),
        )

    reclaimed, response = inbound_event_repo.claim("line", event_id, "hash-1")
    assert reclaimed == "new"
    assert response is None


def test_browser_attempt_numbers_are_atomic_under_concurrency():
    created = client.post(
        "/api/browser/flight-search",
        json={
            "origin": "TPE",
            "destination": "NRT",
            "depart_date": "2026-10-18",
            "return_date": "2026-10-22",
            "adults": 1,
            "airline_codes": ["CI"],
        },
    )
    assert created.status_code == 200
    task_id = created.json()["tasks"][0]["id"]

    def start_one(_):
        return browser_attempt_repo.start(task_id, "openclaw", "openclaw")

    with ThreadPoolExecutor(max_workers=8) as pool:
        attempts = list(pool.map(start_one, range(8)))

    numbers = sorted(item.attempt_no for item in attempts)
    assert numbers == list(range(1, 9))
    assert len({item.id for item in attempts}) == 8


def test_operator_api_auth_and_security_headers(monkeypatch):
    import app.main as main_module
    import app.security as security_module

    secured = replace(main_module.settings, admin_token="review-secret")
    monkeypatch.setattr(main_module, "settings", secured)
    monkeypatch.setattr(security_module, "settings", secured)

    denied = client.get("/api/airlines")
    assert denied.status_code == 401
    assert denied.headers["www-authenticate"] == "Bearer"

    allowed = client.get(
        "/api/airlines",
        headers={"X-Travel-Desk-Admin-Token": "review-secret"},
    )
    assert allowed.status_code == 200
    assert allowed.headers["x-content-type-options"] == "nosniff"
    assert allowed.headers["x-frame-options"] == "DENY"
    assert allowed.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in allowed.headers["content-security-policy"]


def test_request_body_limit_is_enforced(monkeypatch):
    import app.main as main_module

    limited = replace(main_module.settings, max_request_body_bytes=64)
    monkeypatch.setattr(main_module, "settings", limited)

    response = client.post(
        "/api/agent/ask",
        content=b"x" * 128,
        headers={"Content-Type": "application/json", "Content-Length": "128"},
    )
    assert response.status_code == 413


def test_production_requires_operator_token(monkeypatch):
    import app.security as security_module

    production = replace(
        security_module.settings,
        app_env="production",
        admin_token="",
    )
    monkeypatch.setattr(security_module, "settings", production)
    with pytest.raises(RuntimeError, match="TRAVEL_DESK_ADMIN_TOKEN"):
        security_module.validate_runtime_settings()
