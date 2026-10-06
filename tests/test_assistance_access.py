"""Every private API path has an exact operator grant and mutation Origin guard."""

from uuid import uuid4

import pytest
from test_access_auth import (
    headers,
    access_client as access_client,
    signing_keys as signing_keys,
)
from test_travel_files import crypto_settings as crypto_settings
from test_case_operations import evidence

ROUTES = [
    ("GET", "/api/mom/customers"),
    ("POST", "/api/mom/customers"),
    ("GET", "/api/mom/customers/missing"),
    ("PATCH", "/api/mom/customers/missing"),
    ("GET", "/api/mom/customers/missing/reveal"),
    ("GET", "/api/mom/customers/missing/history"),
    ("POST", "/api/mom/customers/missing/consents"),
    ("GET", "/api/mom/customer-receipts/new/" + str(uuid4())),
    ("GET", "/api/mom/reminder-status"),
    *[
        (method, "/api/mom/cases/missing/" + suffix)
        for method, suffix in [
            ("GET", "crm"),
            ("POST", "customer-link"),
            ("POST", "communications"),
            ("PATCH", "communications/missing"),
            ("GET", "communications/missing/reveal"),
            ("POST", "communications/missing/attest"),
            ("GET", "traveller-services"),
            ("POST", "traveller-services"),
            ("PATCH", "traveller-services/missing"),
            ("GET", "traveller-services/missing/reveal"),
            ("POST", "traveller-services/missing/archive"),
            ("GET", "reminders"),
            ("POST", "reminders"),
            ("PATCH", "reminders/missing"),
            ("GET", "reminders/missing/reveal"),
            ("GET", "reminder-jobs/missing/reveal"),
            ("POST", "reminder-jobs/missing/confirm"),
            ("GET", "assistance-receipts/" + str(uuid4())),
        ]
    ],
]


@pytest.mark.parametrize("method,path", ROUTES)
def test_exact_operator_grants_and_origin_guards(
    access_client, signing_keys, method, path
):
    signed = headers(signing_keys[0])
    kwargs = {"json": {}} if method != "GET" else {}
    response = access_client.request(method, path, headers=signed, **kwargs)
    assert response.status_code not in {401, 403}, response.text
    assert response.headers["cache-control"] == "no-store"
    if method != "GET":
        for origin in ("", "null", "https://attacker.test"):
            assert (
                access_client.request(
                    method, path, headers={**signed, "Origin": origin}, json={}
                ).status_code
                == 403
            )
    assert access_client.request("DELETE", path, headers=signed).status_code == 403
    assert (
        access_client.request(
            method, path + "/unexpected/unexpected", headers=signed, **kwargs
        ).status_code
        == 403
    )


def test_signed_actor_binding_and_customer_receipt_ownership(
    access_client, signing_keys, crypto_settings, monkeypatch, tmp_path
):
    from dataclasses import replace
    import app.db as database

    monkeypatch.setattr(
        database,
        "settings",
        replace(database.settings, db_path=str(tmp_path / "access.db")),
    )
    database.init_db()
    mom = headers(signing_keys[0])
    data = evidence(
        display_name="合成私密客戶",
        phone="PRIVATE-電話",
        email="synthetic@example.test",
    )
    mismatched = {**mom, "X-Travel-Service-Actor": "admin%40example.com"}
    assert (
        access_client.post(
            "/api/mom/customers", headers=mismatched, json=data
        ).status_code
        == 412
    )
    saved = access_client.post(
        "/api/mom/customers",
        headers={**mom, "X-Travel-Service-Actor": "mom%40example.com"},
        json=data,
    )
    assert saved.status_code == 200, saved.text
    path = "/api/mom/customer-receipts/new/" + data["request_id"]
    assert access_client.get(path, headers=mom).json()["committed"]
    assert (
        access_client.get(
            path, headers=headers(signing_keys[0], email="admin@example.com")
        ).status_code
        == 409
    )
    assert "PRIVATE-電話" not in access_client.get(path, headers=mom).text
    assert (
        access_client.post(
            "/api/system/reminders/acknowledge-restore", headers=mom, json=evidence()
        ).status_code
        == 403
    )
