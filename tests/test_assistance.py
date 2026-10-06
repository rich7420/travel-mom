"""Private assistance contract tests, each isolated from the shared legacy test DB."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from uuid import uuid4
import sqlite3

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.db import connect
from app.operations_repository import encode, rows, save
from app.services import crm, reminders, notification_worker as worker, outbound
from test_case_operations import (
    family,
    accepted,
    verified_booking,
    post,
    evidence,
    intent,
    moment,
    bundle,
)
from test_travel_files import traveller


@pytest.fixture
def client(monkeypatch, tmp_path):
    import app.db as database
    import app.operations_repository as repository
    import app.services.travel_files as files
    import scripts.backup_bundle as backups

    settings = replace(
        database.settings,
        db_path=str(tmp_path / "desk.db"),
        pii_fernet_key=Fernet.generate_key().decode(),
        attachments_dir=str(tmp_path / "files"),
        backup_dir=str(tmp_path / "backups"),
        reminders_enabled=True,
        reminder_smtp_enabled=True,
        reminder_smtp_host="smtp.example.test",
        reminder_smtp_from="desk@example.test",
        reminder_staff_emails=("staff@example.test",),
    )
    for module in (database, repository, files, backups, reminders, outbound):
        monkeypatch.setattr(module, "settings", settings)
    with TestClient(app) as value:
        yield value


def profile(client, name="王女士"):
    data = evidence(
        display_name=name,
        phone="PRIVATE-PHONE",
        email="private@example.test",
        notes="PRIVATE-CRM",
    )
    result = client.post("/api/mom/customers", json=data)
    assert result.status_code == 200, result.text
    assert client.post("/api/mom/customers", json=data).json() == result.json()
    receipt = client.get("/api/mom/customer-receipts/new/" + data["request_id"]).json()
    assert (
        receipt["committed"]
        and receipt["record_id"] == result.json()["id"]
        and "PRIVATE" not in str(receipt)
    )
    return result.json()


def linked(client, case, customer):
    result = post(
        client,
        case,
        "customer-link",
        evidence(
            customer_id=customer["id"], expected_revision=0, reason="核對客戶本人"
        ),
    )
    assert result.status_code == 200, result.text
    return result.json()


def message(client, case, **changes):
    result = post(
        client,
        case,
        "communications",
        evidence(
            kind="draft", channel="email", body="PRIVATE-草稿", owner="媽媽", **changes
        ),
    )
    assert result.status_code == 200, result.text
    return result.json()


def rule(client, case, customer=None, **changes):
    due_hours = changes.pop("due_hours", 0)
    task = post(
        client,
        case,
        "work-items",
        intent(
            kind="document",
            title="補件期限",
            owner="媽媽",
            due_at=(
                datetime.fromisoformat(moment(due_hours)) + timedelta(seconds=1)
            ).isoformat(),
            source="客人",
        ),
    ).json()
    fields = {
        "source_kind": "work_item",
        "source_id": task["id"],
        "source_revision": task["revision"],
        "channel": "email",
        "recipient_kind": "staff",
        "recipient": "staff@example.test",
        "body": "PRIVATE-提醒原文",
        "offset_minutes": 0,
        "enabled": True,
    }
    if customer:
        fields.update(
            recipient_kind="customer",
            recipient="",
            customer_id=customer["id"],
            customer_revision=customer["revision"],
            consent_revision=customer["consents"]["email"]["revision"],
        )
    fields.update(changes)
    data = evidence(**fields)
    result = post(client, case, "reminders", data)
    assert result.status_code == 200, result.text
    return task, result.json()


def jobs():
    with connect() as db:
        return [
            dict(r)
            for r in db.execute(
                "SELECT * FROM agency_notification_jobs ORDER BY created_at,id"
            )
        ]


def test_closed_crm_preserves_business_and_original_customer_attribution(client):
    case, _ = family(client)
    one = profile(client)
    linked(client, case, one)
    with connect() as db:
        db.execute("UPDATE trip_cases SET status='closed' WHERE id=?", (case["id"],))
        before = dict(
            db.execute("SELECT * FROM trip_cases WHERE id=?", (case["id"],)).fetchone()
        )
        business = {
            table: rows(db, table, case["id"])
            for table in (
                "quotes",
                "work_items",
                "bookings",
                "documents",
                "ledger",
                "pretrip",
                "travellers",
                "traveller_services",
                "service_orders",
                "case_events",
            )
        }
    first = message(client, case)
    changed = client.patch(
        f"/api/mom/cases/{case['id']}/communications/{first['id']}",
        json=evidence(expected_revision=1, body="PRIVATE-修訂草稿"),
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["status"] == "draft"
    stale = client.patch(
        f"/api/mom/cases/{case['id']}/communications/{first['id']}",
        json=evidence(expected_revision=1, body="錯誤覆寫"),
    )
    assert stale.status_code == 409
    sent = post(
        client,
        case,
        f"communications/{first['id']}/attest",
        evidence(expected_revision=2, actually_sent=True),
    )
    assert sent.status_code == 200 and sent.json()["status"] == "sent"
    two = profile(client, "另一位同名客戶")
    assert two["id"] != one["id"]
    assert (
        post(
            client,
            case,
            "customer-link",
            evidence(customer_id=two["id"], expected_revision=1, reason="更正原關聯"),
        ).status_code
        == 200
    )
    old = client.get(f"/api/mom/customers/{one['id']}/history").json()
    assert old["communications"][0]["id"] == first["id"]
    assert not client.get(f"/api/mom/customers/{two['id']}/history").json()[
        "communications"
    ]
    reveal = client.get(
        f"/api/mom/cases/{case['id']}/communications/{first['id']}/reveal"
    ).json()
    assert (
        reveal["body"] == "PRIVATE-修訂草稿"
        and reveal["history"][0]["body"] == "PRIVATE-草稿"
    )
    assert (
        post(
            client,
            case,
            "work-items",
            intent(
                kind="document",
                title="不可修改",
                owner="媽媽",
                due_at=moment(),
                source="test",
            ),
        ).status_code
        == 409
    )
    with connect() as db:
        assert before == dict(
            db.execute("SELECT * FROM trip_cases WHERE id=?", (case["id"],)).fetchone()
        )
        assert business == {table: rows(db, table, case["id"]) for table in business}


def test_private_storage_summaries_receipts_actor_and_uuid_conflicts(client):
    case, _ = family(client)
    customer = profile(client)
    linked(client, case, customer)
    data = evidence(kind="incoming", body="PRIVATE-MESSAGE", owner="媽媽")
    response = post(client, case, "communications", data)
    assert response.status_code == 200, response.text
    assert response.json() == post(client, case, "communications", data).json()
    conflicted = post(client, case, "communications", {**data, "body": "DIFFERENT"})
    assert conflicted.status_code == 409
    path = f"/api/mom/cases/{case['id']}/assistance-receipts/{data['request_id']}"
    assert client.get(path).json()["committed"]
    assert (
        client.get(
            path, headers={"X-Travel-Service-Actor": "someone@example.test"}
        ).status_code
        == 412
    )
    assert client.get(path.replace(data["request_id"], "invalid")).status_code == 400
    assert (
        post(
            client,
            case,
            "communications",
            {**data, "request_id": str(uuid4()), "body": "second"},
        ).status_code
        == 200
    )
    for path in (
        f"/api/mom/cases/{case['id']}/crm",
        "/api/mom/customers",
        f"/api/mom/cases/{case['id']}/operations",
        path,
    ):
        view = client.get(path)
        assert (
            all(
                marker not in view.text
                for marker in ("PRIVATE-PHONE", "PRIVATE-MESSAGE", "PRIVATE-CRM")
            )
            and "encrypted" not in view.text
        )
    with connect() as db:
        for table in (
            "agency_customers",
            "agency_communications",
            "agency_commands",
            "customer_commands",
            "audit_log",
        ):
            assert all(
                marker not in str(db.execute(f"SELECT * FROM {table}").fetchall())
                for marker in ("PRIVATE-PHONE", "PRIVATE-MESSAGE", "PRIVATE-CRM")
            )


def test_complaint_followup_resolve_and_explicit_patch(client):
    case, _ = family(client)
    customer = profile(client)
    linked(client, case, customer)
    result = post(
        client,
        case,
        "communications",
        evidence(
            kind="complaint",
            body="PRIVATE-客訴原文",
            owner="媽媽",
            followup_at=moment(3),
        ),
    ).json()
    endpoint = f"/api/mom/cases/{case['id']}/communications/{result['id']}"
    for field in ("body", "owner", "status"):
        assert (
            client.patch(
                endpoint, json=evidence(expected_revision=1, **{field: None})
            ).status_code
            == 422
        )
    assert (
        client.patch(
            endpoint, json=evidence(expected_revision=1, body="改寫原文")
        ).status_code
        == 409
    )
    updated = client.patch(
        endpoint,
        json=evidence(
            expected_revision=1, status="resolved", owner="小李", followup_at=None
        ),
    )
    assert updated.status_code == 200 and updated.json()["status"] == "resolved"
    assert client.get(endpoint + "/reveal").json()["body"] == "PRIVATE-客訴原文"


def test_ticket_binding_stale_and_roster_fingerprint_separation(client):
    case, ids = family(client)
    accepted(client, case, ids)
    booking = verified_booking(client, case)
    person = post(client, case, "travellers", traveller()).json()
    initial = client.get(f"/api/mom/cases/{case['id']}/travel-files").json()["roster"][
        "expected_state"
    ]
    data = evidence(
        traveller_id=person["id"],
        booking_id=booking["id"],
        traveller_revision=1,
        booking_revision=1,
        segment_label="PRIVATE-航段",
        ticket_number="PRIVATE-TICKET",
        requests={
            "seat": {
                "value": "PRIVATE-走道",
                "status": "confirmed",
                "supplier_reference": "PNR通知",
            }
        },
    )
    response = post(client, case, "traveller-services", data)
    assert response.status_code == 200, response.text
    service = response.json()
    path = f"/api/mom/cases/{case['id']}/traveller-services/{service['id']}"
    b = client.get(f"/api/mom/cases/{case['id']}/travel-files").json()
    assert (
        b["traveller_services"][0]["current"]
        and b["roster"]["expected_state"] == initial
    )
    assert "PRIVATE-TICKET" not in str(b)
    assert client.get(path + "/reveal").json()["ticket_number"] == "PRIVATE-TICKET"
    edit = {
        **data,
        "request_id": str(uuid4()),
        "expected_revision": 1,
        "ticket_number": "PRIVATE-NEW",
    }
    assert client.patch(path, json=edit).status_code == 200
    revealed = client.get(path + "/reveal").json()
    assert revealed["history"][0]["content"]["ticket_number"] == "PRIVATE-TICKET"
    with connect() as db:
        old = rows(db, "bookings", case["id"])[0]
        old["revision"] += 1
        save(db, "bookings", old)
    assert not client.get(f"/api/mom/cases/{case['id']}/travel-files").json()[
        "traveller_services"
    ][0]["current"]
    assert (
        client.patch(
            path, json={**edit, "request_id": str(uuid4()), "expected_revision": 2}
        ).status_code
        == 409
    )
    assert (
        post(
            client,
            case,
            f"traveller-services/{service['id']}/archive",
            evidence(expected_revision=2),
        ).status_code
        == 200
    )


def test_lease_fence_no_lock_during_transport_and_one_accepted_history(client):
    case, _ = family(client)
    customer = profile(client)
    linked(client, case, customer)
    customer = client.post(
        f"/api/mom/customers/{customer['id']}/consents",
        json=evidence(expected_revision=customer["revision"], granted=True),
    ).json()
    task, policy = rule(client, case, customer)
    now = datetime.now(timezone.utc) + timedelta(seconds=3)
    calls = []

    def send(*args):
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")  # transport holds no DB lock
        calls.append(args)
        return outbound.Delivery("accepted", provider_request_id="provider-id")

    assert worker.tick("test", now, send)["sent"] == 1
    assert worker.tick("test", now, send)["sent"] == 0 and len(calls) == 1
    assert jobs()[0]["status"] == "accepted"
    messages = client.get(f"/api/mom/cases/{case['id']}/crm").json()["communications"]
    assert len(messages) == 1 and messages[0]["status"] == "provider_accepted"
    body = client.get(
        f"/api/mom/cases/{case['id']}/communications/{messages[0]['id']}/reveal"
    ).json()["body"]
    assert body == "PRIVATE-提醒原文"
    _, _ = rule(client, case)
    now = datetime.now(timezone.utc) + timedelta(seconds=3)
    claimed, _ = worker.claim("test", now)
    job, _ = claimed
    assert not worker.finish(
        job, outbound.Delivery("accepted"), now + timedelta(seconds=301)
    )
    # Expiry happens on next claim; SMTP is unknown, never auto retried.
    assert worker.tick("test", now + timedelta(seconds=302), send)["sent"] == 0
    assert any(j["status"] == "unknown" for j in jobs()) and len(calls) == 1


def test_consent_email_source_and_closure_cancel_queued(client):
    case, _ = family(client)
    customer = profile(client)
    linked(client, case, customer)
    consent = client.post(
        f"/api/mom/customers/{customer['id']}/consents",
        json=evidence(expected_revision=1, granted=True),
    ).json()
    task, policy = rule(client, case, consent)
    now = datetime.now(timezone.utc) + timedelta(seconds=3)
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        worker.create_jobs(db, now)
    assert jobs()[0]["status"] == "queued"
    changed = client.patch(
        f"/api/mom/customers/{customer['id']}",
        json=evidence(
            display_name="王女士",
            phone="PRIVATE-PHONE",
            email="new@example.test",
            notes="",
            expected_revision=consent["revision"],
        ),
    )
    assert changed.status_code == 200, changed.text
    assert (
        not changed.json()["consents"]["email"]["granted"]
        and jobs()[0]["status"] == "cancelled"
    )
    _, policy = rule(client, case)
    with connect() as db:
        db.execute("UPDATE trip_cases SET status='closed' WHERE id=?", (case["id"],))
    calls = []
    assert (
        worker.tick("test", now, lambda *args: calls.append(args))["sent"] == 0
        and not calls
    )
    assert not client.get(f"/api/mom/cases/{case['id']}/reminders").json()["rules"][-1][
        "enabled"
    ]


def test_manual_unknown_confirmation_idempotent_retry_and_duplicate_guard(client):
    case, _ = family(client)
    customer = profile(client)
    linked(client, case, customer)
    customer = client.post(
        f"/api/mom/customers/{customer['id']}/consents",
        json=evidence(expected_revision=customer["revision"], granted=True),
    ).json()
    rule(client, case, customer)
    now = datetime.now(timezone.utc) + timedelta(seconds=3)
    assert (
        worker.tick(
            "test",
            now,
            lambda *args: outbound.Delivery("unknown", "smtp_data_unconfirmed"),
        )["sent"]
        == 0
    )
    job = jobs()[0]
    endpoint = f"reminder-jobs/{job['id']}/confirm"
    assert (
        post(
            client,
            case,
            endpoint,
            evidence(expected_revision=job["revision"], decision="retry"),
        ).status_code
        == 422
    )
    data = evidence(expected_revision=job["revision"], decision="accepted")
    first = post(client, case, endpoint, data)
    assert first.status_code == 200, first.text
    assert post(client, case, endpoint, data).json() == first.json()
    assert (
        len(client.get(f"/api/mom/cases/{case['id']}/crm").json()["communications"])
        == 1
    )


def test_encrypted_backup_send_restore_tick_zero_and_no_job_rule_pause(
    client, tmp_path, monkeypatch
):
    from scripts.backup_bundle import backup, restore
    import app.db as database

    case, _ = family(client)
    customer = profile(client)
    linked(client, case, customer)
    rule(client, case)
    rule(client, case, due_hours=2)
    now = datetime.now(timezone.utc) + timedelta(seconds=3)
    with connect() as db:
        worker.create_jobs(db, now)
    bundle = backup()["bundle"]
    assert (
        worker.tick("test", now, lambda *args: outbound.Delivery("accepted"))["sent"]
        == 1
    )
    restored = tmp_path / "restored.db"
    restore(
        bundle, restored, tmp_path / "restored-files", database.settings.pii_fernet_key
    )
    monkeypatch.setattr(
        database, "settings", replace(database.settings, db_path=str(restored))
    )
    sent = []
    assert (
        worker.tick("restored", now, lambda *args: sent.append(args))["status"]
        == "restore_paused"
        and not sent
    )
    with connect() as db:
        assert all(
            not json.loads(r[0])["enabled"]
            for r in db.execute("SELECT payload_json FROM agency_reminders")
        )
        assert db.execute("SELECT COUNT(*) FROM agency_reminders").fetchone()[0] == 2
        assert (
            db.execute("SELECT status FROM agency_notification_jobs").fetchone()[0]
            == "paused_after_restore"
        )
    from app.operations_models import Evidence

    assert reminders.acknowledge_restore(Evidence(**evidence()), "operator")[
        "rules_remain_paused"
    ]
    assert (
        worker.tick("restored", now, lambda *args: sent.append(args))["sent"] == 0
        and not sent
    )
    assert crm.reveal_customer(customer["id"], "operator")["phone"] == "PRIVATE-PHONE"


def test_daily_reminder_does_not_replay_backlog(client):
    case, _ = family(client)
    task, policy = rule(client, case, repeat_hours=24)
    now = (datetime.now(timezone.utc) + timedelta(seconds=3)) + timedelta(days=2)
    calls = []
    assert (
        worker.tick(
            "test",
            now,
            lambda *args: calls.append(args) or outbound.Delivery("accepted"),
        )["sent"]
        == 1
    )
    assert (
        len(calls) == 1
        and len(jobs()) == 3
        and sum(j["status"] == "missed" for j in jobs()) == 2
    )
    assert worker.tick("test", now, lambda *args: calls.append(args))["sent"] == 0


def test_manual_smtp_retry_retains_exact_bytes_and_message_id(client):
    case, _ = family(client)
    rule(client, case)
    now = datetime.now(timezone.utc) + timedelta(seconds=3)
    calls = []

    def uncertain(*args):
        calls.append(args)
        return outbound.Delivery("unknown")

    worker.tick("test", now, uncertain)
    job = jobs()[0]
    response = post(
        client,
        case,
        f"reminder-jobs/{job['id']}/confirm",
        evidence(
            expected_revision=job["revision"],
            decision="retry",
            duplicate_risk_checked=True,
        ),
    )
    assert response.status_code == 200, response.text
    assert (
        worker.tick(
            "test",
            (datetime.now(timezone.utc) + timedelta(seconds=3)),
            lambda *args: calls.append(args) or outbound.Delivery("accepted"),
        )["sent"]
        == 1
    )
    assert calls[0] == calls[1]


def test_line_expired_window_manual_retry_uses_new_key_without_grace_deadend(
    client, monkeypatch
):
    monkeypatch.setattr(
        reminders,
        "settings",
        replace(
            reminders.settings,
            reminder_line_enabled=True,
            line_channel_access_token="synthetic",
            line_allowed_user_ids=("known-user",),
        ),
    )
    case, _ = family(client)
    rule(client, case, channel="line", recipient="known-user")
    now = datetime.now(timezone.utc) + timedelta(seconds=3)
    calls = []
    worker.tick(
        "test", now, lambda *args: calls.append(args) or outbound.Delivery("unknown")
    )
    job = jobs()[0]
    with connect() as db:
        db.execute(
            "UPDATE agency_notification_jobs SET first_attempt_at=? WHERE id=?",
            ((now - timedelta(days=2)).isoformat(), job["id"]),
        )
    response = post(
        client,
        case,
        f"reminder-jobs/{job['id']}/confirm",
        evidence(
            expected_revision=job["revision"],
            decision="retry",
            duplicate_risk_checked=True,
        ),
    )
    assert response.status_code == 200, response.text
    assert (
        worker.tick(
            "test",
            (datetime.now(timezone.utc) + timedelta(seconds=3)),
            lambda *args: calls.append(args) or outbound.Delivery("accepted"),
        )["sent"]
        == 1
    )
    assert calls[0][:3] == calls[1][:3] and calls[0][3] != calls[1][3]


def test_outbox_payload_and_attempts_are_immutable_and_encrypted(client):
    case, _ = family(client)
    rule(client, case)
    worker.tick(
        "test",
        (datetime.now(timezone.utc) + timedelta(seconds=3)),
        lambda *args: outbound.Delivery("accepted"),
    )
    job = jobs()[0]
    assert "PRIVATE-提醒" not in job["payload_json"]
    with connect() as db:
        for sql in (
            "UPDATE agency_notification_jobs SET payload_json='{}'",
            "UPDATE agency_notification_attempts SET status='unknown'",
            "DELETE FROM agency_notification_attempts",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql)


def test_legacy_pack_hash_unchanged_and_bound_service_summary_matches_delivery(client):
    from app.services.case_operations import pack_source, pack_source_from, fingerprint
    from app.services.travel_files import roster_state
    from app.repositories import _case_from_row
    from test_case_operations import ready_document

    case, ids = family(client)
    q = accepted(client, case, ids)
    booking = verified_booking(client, case)
    hotel = verified_booking(client, case, "hotel")
    ready_document(client, case, booking, "e_ticket")
    ready_document(client, case, hotel, "hotel_voucher")
    with connect() as db:
        value = _case_from_row(
            db.execute("SELECT * FROM trip_cases WHERE id=?", (case["id"],)).fetchone()
        )
        original = pack_source_from(
            value,
            q,
            rows(db, "bookings", case["id"]),
            rows(db, "documents", case["id"]),
            roster_state(db, value),
            rows(db, "service_orders", case["id"]),
        )
        assert "traveller_services" not in original and fingerprint(
            original
        ) == fingerprint(pack_source(db, value, q))
    prepared = post(client, case, "pretrip", intent(title="無逐人服務版本")).json()
    assert prepared["status"] == "prepared"
    assert not bundle(client, case)["pretrip"][0]["stale"]
    person = post(client, case, "travellers", traveller()).json()
    # Family has four people; identity setup used only to prove private-summary filtering here.
    data = evidence(
        traveller_id=person["id"],
        booking_id=booking["id"],
        traveller_revision=1,
        booking_revision=1,
        segment_label="PRIVATE-航段",
        ticket_number="PRIVATE-TICKET",
    )
    assert post(client, case, "traveller-services", data).status_code == 200
    response = client.get(f"/api/mom/cases/{case['id']}/operations")
    assert (
        "encrypted" not in response.text
        and "PRIVATE-TICKET" not in response.text
        and "traveller_services" not in response.json()
    )
    assert response.json()["pretrip"][0]["stale"]


def test_private_command_fingerprint_is_original_hmac_format(client):
    import hmac
    import app.operations_repository as repository
    from app.assistance_models import CommunicationPatch

    data = CommunicationPatch(
        **evidence(expected_revision=1, body="  PRIVATE-body\n\n")
    )
    payload = data.model_dump(mode="json", exclude={"request_id"}, exclude_unset=True)
    content = encode(
        {
            "action": "crm.message.record.patch",
            "payload": payload,
            "actor": "mom@example.test",
        }
    ).encode()
    key = hmac.new(
        repository.settings.pii_fernet_key.encode(),
        b"command-fingerprint-v1",
        hashlib.sha256,
    ).digest()
    assert repository.command_fingerprint(
        data, "mom@example.test", "crm.message.record.patch", private=True
    ) == (payload, hmac.new(key, content, hashlib.sha256).hexdigest())
    assert payload["body"] == "  PRIVATE-body\n\n"


def test_direct_source_sql_change_cancels_queued_without_command_hook(client):
    case, _ = family(client)
    task, policy = rule(client, case)
    now = datetime.now(timezone.utc) + timedelta(seconds=3)
    with connect() as db:
        worker.create_jobs(db, now)
        changed = rows(db, "work_items", case["id"])[0]
        changed.update(status="done", revision=2)
        save(db, "work_items", changed)
    calls = []
    assert (
        worker.tick("test", now, lambda *args: calls.append(args))["sent"] == 0
        and not calls
    )
    assert jobs()[0]["status"] == "cancelled"


def test_flags_pause_then_grace_prevents_old_job_burst(client, monkeypatch):
    case, _ = family(client)
    rule(client, case)
    now = datetime.now(timezone.utc) + timedelta(seconds=3)
    with connect() as db:
        worker.create_jobs(db, now)
    enabled = reminders.settings
    monkeypatch.setattr(
        reminders, "settings", replace(enabled, reminders_enabled=False)
    )
    calls = []
    worker.tick("test", now + timedelta(hours=1), lambda *args: calls.append(args))
    assert jobs()[0]["status"] == "paused" and not calls
    monkeypatch.setattr(reminders, "settings", enabled)
    worker.tick("test", now + timedelta(hours=1), lambda *args: calls.append(args))
    assert jobs()[0]["status"] == "missed" and not calls


def test_stale_traveller_service_blocks_change_resolution_until_rechecked(client):
    from test_service_orders import create, assessed, start, result, resolve, ok
    from test_case_operations import ready_document

    case, ids = family(client)
    accepted(client, case, ids)
    booking = verified_booking(client, case)
    hotel = verified_booking(client, case, "hotel")
    people = [
        post(client, case, "travellers", traveller(category)).json()
        for category in ("adult", "adult", "child", "infant")
    ]
    roster = client.get(f"/api/mom/cases/{case['id']}/travel-files").json()["roster"]
    assert (
        post(
            client,
            case,
            "roster/verify",
            evidence(expected_state=roster["expected_state"]),
        ).status_code
        == 200
    )
    ready_document(client, case, booking, "e_ticket")
    ready_document(client, case, hotel, "hotel_voucher")
    data = evidence(
        traveller_id=people[0]["id"],
        booking_id=booking["id"],
        traveller_revision=1,
        booking_revision=1,
        segment_label="私人航段",
        ticket_number="PRIVATE-TICKET",
    )
    binding = post(client, case, "traveller-services", data).json()
    initial = post(client, case, "pretrip", intent(title="目前行前摘要")).json()
    assert initial["status"] == "prepared"
    assert not bundle(client, case)["pretrip"][0]["stale"]
    order = start(
        client, case, assessed(client, case, create(client, case, "change", [booking]))
    )
    updated = ok(
        post(
            client,
            case,
            f"bookings/{booking['id']}/rebind",
            evidence(reason="重新確認", customer_details="人工核對"),
        )
    )
    order = result(client, case, order, result_booking_ids=[updated["id"]])
    for doc in bundle(client, case)["documents"]:
        assert (
            client.patch(
                f"/api/mom/cases/{case['id']}/documents/{doc['id']}",
                json=evidence(
                    expected_revision=doc["revision"],
                    status="ready",
                    customer_text="已核對新版",
                ),
            ).status_code
            == 200
        )
    assert any(
        "票號" in reason
        for reason in bundle(client, case)["service_orders"][0]["resolution_blockers"]
    )
    assert resolve(client, case, order).status_code == 409
    updated_data = {
        **data,
        "request_id": str(uuid4()),
        "booking_revision": updated["revision"],
        "expected_revision": binding["revision"],
    }
    response = client.patch(
        f"/api/mom/cases/{case['id']}/traveller-services/{binding['id']}",
        json=updated_data,
    )
    assert response.status_code == 200, response.text
    assert resolve(client, case, order).status_code == 200


def test_accepted_occurrence_is_not_replayed_after_body_edit(client):
    case, _ = family(client)
    task, policy = rule(client, case)
    now = datetime.now(timezone.utc) + timedelta(seconds=3)
    sent = []
    transport = lambda *args: sent.append(args) or outbound.Delivery("accepted")
    assert worker.tick("test", now, transport)["sent"] == 1
    data = evidence(
        source_kind="work_item",
        source_id=task["id"],
        source_revision=task["revision"],
        channel="email",
        recipient_kind="staff",
        recipient="staff@example.test",
        body="更新提醒文字",
        offset_minutes=0,
        enabled=True,
        expected_revision=policy["revision"],
    )
    response = client.patch(
        f"/api/mom/cases/{case['id']}/reminders/{policy['id']}", json=data
    )
    assert response.status_code == 200, response.text
    assert (
        worker.tick("test", now + timedelta(minutes=10), transport)["sent"] == 0
        and len(sent) == 1
    )
    assert len(jobs()) == 1


def test_staff_notification_does_not_become_customer_contact(client):
    case, _ = family(client)
    customer = profile(client)
    linked(client, case, customer)
    rule(client, case)
    assert (
        worker.tick(
            "test",
            datetime.now(timezone.utc) + timedelta(seconds=3),
            lambda *args: outbound.Delivery("accepted"),
        )["sent"]
        == 1
    )
    assert not client.get(f"/api/mom/customers/{customer['id']}/history").json()[
        "communications"
    ]
    assert jobs()[0]["status"] == "accepted"


def test_due_batch_drains_and_on_time_queue_is_not_dropped_later(client):
    case, _ = family(client)
    task = post(
        client,
        case,
        "work-items",
        intent(
            kind="document",
            title="大量同時補件",
            owner="媽媽",
            due_at=moment(1),
            source="合成",
        ),
    ).json()
    for i in range(70):
        result = post(
            client,
            case,
            "reminders",
            evidence(
                source_kind="work_item",
                source_id=task["id"],
                source_revision=task["revision"],
                channel="email",
                recipient_kind="staff",
                recipient="staff@example.test",
                body=f"合成提醒{i}",
                offset_minutes=0,
                enabled=True,
            ),
        )
        assert result.status_code == 200, result.text
    now = datetime.fromisoformat(task["due_at"])
    sent = []
    transport = lambda *args: sent.append(args) or outbound.Delivery("accepted")
    assert worker.tick("test", now, transport)["sent"] == 50
    assert worker.tick("test", now + timedelta(minutes=40), transport)["sent"] == 20
    assert len(sent) == 70 and all(j["status"] == "accepted" for j in jobs())


def test_restore_rearm_does_not_replay_pre_restore_occurrence(
    client, tmp_path, monkeypatch
):
    from scripts.backup_bundle import backup, restore
    import app.db as database

    case, _ = family(client)
    task, policy = rule(client, case)
    now = datetime.now(timezone.utc) + timedelta(seconds=3)
    with connect() as db:
        worker.create_jobs(db, now)
    snapshot = backup()["bundle"]
    assert (
        worker.tick("test", now, lambda *args: outbound.Delivery("accepted"))["sent"]
        == 1
    )
    destination = tmp_path / "restored-rearm.db"
    restore(
        snapshot,
        destination,
        tmp_path / "restored-rearm-files",
        database.settings.pii_fernet_key,
    )
    monkeypatch.setattr(
        database, "settings", replace(database.settings, db_path=str(destination))
    )
    from app.operations_models import Evidence

    reminders.acknowledge_restore(Evidence(**evidence()), "operator")
    restored_rule = client.get(f"/api/mom/cases/{case['id']}/reminders").json()[
        "rules"
    ][0]
    # Advance arming clock past the original send, as in a real later restore.
    monkeypatch.setattr(
        reminders, "now_iso", lambda: (now + timedelta(minutes=2)).isoformat()
    )
    response = client.patch(
        f"/api/mom/cases/{case['id']}/reminders/{policy['id']}",
        json=evidence(
            source_kind="work_item",
            source_id=task["id"],
            source_revision=task["revision"],
            channel="email",
            recipient_kind="staff",
            recipient="staff@example.test",
            body="PRIVATE-提醒原文",
            offset_minutes=0,
            enabled=True,
            expected_revision=restored_rule["revision"],
        ),
    )
    assert response.status_code == 200, response.text
    sent = []
    assert (
        worker.tick(
            "test", now + timedelta(minutes=3), lambda *args: sent.append(args)
        )["sent"]
        == 0
        and not sent
    )


@pytest.mark.parametrize("change", ["withdraw", "link", "owner"])
def test_recipient_and_owner_changes_cancel_jobs_in_same_transaction(client, change):
    case, _ = family(client)
    customer = profile(client)
    linked(client, case, customer)
    customer = client.post(
        f"/api/mom/customers/{customer['id']}/consents",
        json=evidence(expected_revision=customer["revision"], granted=True),
    ).json()
    task, policy = rule(client, case, customer)
    now = datetime.now(timezone.utc) + timedelta(seconds=3)
    with connect() as db:
        worker.create_jobs(db, now)
    assert jobs()[0]["status"] == "queued"
    if change == "withdraw":
        response = client.post(
            f"/api/mom/customers/{customer['id']}/consents",
            json=evidence(expected_revision=customer["revision"], granted=False),
        )
    elif change == "link":
        other = profile(client, "另一位客人")
        response = post(
            client,
            case,
            "customer-link",
            evidence(
                customer_id=other["id"], expected_revision=1, reason="核對關聯更正"
            ),
        )
    else:
        response = client.patch(
            f"/api/mom/cases/{case['id']}/work-items/{task['id']}",
            json=intent(
                expected_revision=task["revision"], owner="小李", reason="交接"
            ),
        )
    assert response.status_code == 200, response.text
    assert jobs()[0]["status"] == "cancelled"
    assert not client.get(f"/api/mom/cases/{case['id']}/reminders").json()["rules"][0][
        "enabled"
    ]


def test_two_workers_cannot_claim_same_message(client):
    from concurrent.futures import ThreadPoolExecutor
    import threading

    case, _ = family(client)
    rule(client, case)
    now = datetime.now(timezone.utc) + timedelta(seconds=3)
    started = threading.Event()
    release = threading.Event()
    sent = []

    def transport(*args):
        started.set()
        release.wait(timeout=5)
        sent.append(args)
        return outbound.Delivery("accepted")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(worker.tick, "first", now, transport)
        assert started.wait(timeout=3)
        second = pool.submit(worker.tick, "second", now, transport)
        try:
            assert second.result(timeout=3)["sent"] == 0
        finally:
            release.set()
        assert first.result(timeout=3)["sent"] == 1
    assert len(sent) == 1 and len(jobs()) == 1
