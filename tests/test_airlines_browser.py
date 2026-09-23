import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.airlines import AIRLINES, official_airline_for_url
from app.db import init_db
from app.main import app
from app.models import FlightSearchRequest
from app.services.browser_result import validate_flight_search_result
from app.services.browser_tasks import browser_task_service

client = TestClient(app)


def test_airline_registry_has_pilot_eight():
    assert set(AIRLINES) == {"CI", "BR", "CX", "JX", "AE", "IT", "EK", "NH"}
    assert official_airline_for_url("https://booking.china-airlines.com/x").code == "CI"
    assert official_airline_for_url("https://evilchina-airlines.com/x") is None


def test_structured_search_creates_tasks_for_supported_airlines():
    init_db()
    req = FlightSearchRequest(
        origin="TPE", destination="NRT", depart_date="2026-10-18", return_date="2026-10-22",
        adults=2, airline_codes=["CI", "CX", "JX", "AE", "EK", "NH"],
    )
    plan = browser_task_service.create_flight_search(req)
    assert len(plan.tasks) == 6
    assert not plan.manual_handoffs
    assert all(t.expected_schema == "flight-search-v1" for t in plan.tasks)


def test_mandarin_more_than_four_occupied_is_manual_handoff():
    init_db()
    req = FlightSearchRequest(
        origin="TPE", destination="KNH", depart_date="2026-10-18", return_date="2026-10-22",
        adults=5, airline_codes=["AE", "CI"],
    )
    plan = browser_task_service.create_flight_search(req)
    assert [t.provider_code for t in plan.tasks] == ["CI"]
    assert plan.manual_handoffs[0]["airline_code"] == "AE"
    assert "最多 4" in plan.manual_handoffs[0]["reason"]


def test_unknown_domain_default_deny_and_official_domain_allow():
    with client:
        bad = client.post('/api/browser/tasks', json={
            'kind': 'flight_search', 'source_url': 'https://example.com', 'instructions': 'x'
        })
        assert bad.status_code == 400
        good = client.post('/api/browser/tasks', json={
            'kind': 'flight_search', 'source_url': 'https://www.emirates.com/tw/chinese/book/', 'instructions': 'x'
        })
        assert good.status_code == 200
        assert good.json()['provider_code'] == 'EK'


def test_round_trip_requires_return_date():
    with pytest.raises(ValidationError):
        FlightSearchRequest(origin="TPE", destination="NRT", depart_date="2026-10-18", return_date=None)


def test_flight_result_schema_and_official_domain_validation():
    payload = {
        "schema_version": "flight-search-v1",
        "airline_code": "CX",
        "airline_name": "Cathay Pacific",
        "source_url": "https://www.cathaypacific.com/cx/en_TW/book-a-trip.html",
        "status": "ok",
        "observed_at": "2026-08-25T07:00:00Z",
        "currency": "TWD",
        "options": [{
            "option_id": "cx-1", "total_amount": 19000, "currency": "TWD", "fare_family": "Economy",
            "segments": [{"flight_number": "CX451", "marketing_airline": "CX", "operating_airline": "CX", "origin": "TPE", "destination": "HKG"}],
            "stops": 0, "checked_baggage": "1pc", "carry_on": "unknown",
            "change_rule_summary": "fee applies", "refund_rule_summary": "unknown", "seat_selection": "unknown", "warnings": []
        }],
        "notes": []
    }
    result, errors = validate_flight_search_result("result:\n```json\n" + json.dumps(payload) + "\n```", "CX")
    assert result is not None
    assert errors == []

    payload["source_url"] = "https://evil.example/"
    result, errors = validate_flight_search_result(json.dumps(payload), "CX")
    assert result is not None
    assert errors


def test_skills_frontmatter_audit():
    proc = subprocess.run([sys.executable, "scripts/audit_skills.py"], cwd=".", capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "local skills audited" in proc.stdout


def test_airline_recipe_audit():
    proc = subprocess.run([sys.executable, "scripts/audit_airline_recipes.py"], cwd=".", capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "airline recipes audited" in proc.stdout


def test_result_validation_checks_requested_round_trip_route_and_dates():
    payload = {
        "schema_version": "flight-search-v1",
        "airline_code": "CI",
        "airline_name": "China Airlines",
        "source_url": "https://booking.china-airlines.com/booking/Index",
        "status": "ok",
        "observed_at": "2026-08-25T07:00:00Z",
        "currency": "TWD",
        "options": [{
            "option_id": "ci-1", "total_amount": 18000, "currency": "TWD", "fare_family": "Economy",
            "segments": [
                {"flight_number": "CI100", "marketing_airline": "CI", "operating_airline": "CI", "origin": "TPE", "destination": "NRT", "departure_local": "2026-10-18T08:00"},
                {"flight_number": "CI101", "marketing_airline": "CI", "operating_airline": "CI", "origin": "NRT", "destination": "TPE", "departure_local": "2026-10-22T14:00"}
            ],
            "stops": 0, "checked_baggage": "23kg", "carry_on": "7kg",
            "change_rule_summary": "fee applies", "refund_rule_summary": "fee applies", "seat_selection": "unknown", "warnings": []
        }],
        "notes": []
    }
    expected = {"origin": "TPE", "destination": "NRT", "depart_date": "2026-10-18", "return_date": "2026-10-22", "trip_type": "round_trip"}
    result, errors = validate_flight_search_result(json.dumps(payload), "CI", expected)
    assert result is not None
    assert errors == []

    payload["options"][0]["segments"][1]["departure_local"] = "2026-10-23T14:00"
    _, errors = validate_flight_search_result(json.dumps(payload), "CI", expected)
    assert any("回程日期" in e for e in errors)


def test_official_compare_only_uses_auto_validated_results():
    from app.repositories import browser_task_repo
    from app.services.official_compare import compare_official_flight_tasks

    init_db()
    req = FlightSearchRequest(
        origin="TPE", destination="NRT", depart_date="2026-10-18", return_date="2026-10-22",
        adults=1, airline_codes=["CI", "CX"], nonstop_preferred=True,
    )
    plan = browser_task_service.create_flight_search(req)
    for idx, task in enumerate(plan.tasks):
        code = task.provider_code
        source = "https://booking.china-airlines.com/booking/Index" if code == "CI" else "https://www.cathaypacific.com/cx/zh_TW.html"
        payload = {
            "schema_version": "flight-search-v1",
            "airline_code": code,
            "airline_name": "China Airlines" if code == "CI" else "Cathay Pacific",
            "source_url": source,
            "status": "ok",
            "observed_at": "2026-08-25T07:00:00Z",
            "currency": "TWD",
            "options": [{
                "option_id": f"{code}-1", "total_amount": 15000 + idx * 2500, "currency": "TWD", "fare_family": "Economy",
                "segments": [
                    {"flight_number": f"{code}100", "marketing_airline": code, "operating_airline": code, "origin": "TPE", "destination": "NRT", "departure_local": "2026-10-18T08:00", "duration_minutes": 190 + idx * 30},
                    {"flight_number": f"{code}101", "marketing_airline": code, "operating_airline": code, "origin": "NRT", "destination": "TPE", "departure_local": "2026-10-22T14:00", "duration_minutes": 210 + idx * 30}
                ],
                "stops": 0, "total_duration_minutes": 400 + idx * 60,
                "checked_baggage": "23kg", "carry_on": "7kg", "change_rule_summary": "fee applies", "refund_rule_summary": "fee applies", "seat_selection": "unknown", "warnings": []
            }],
            "notes": []
        }
        browser_task_repo.update(task.id, "completed", json.dumps(payload), payload, review_state="auto_validated")

    comparison = compare_official_flight_tasks([t.id for t in plan.tasks])
    assert comparison["schema_version"] == "flight-comparison-v1"
    assert comparison["mixed_currency"] is False
    ranked = comparison["currency_groups"][0]["ranked"]
    assert ranked[0]["airline_code"] == "CI"
    assert len(ranked) == 2


def test_same_origin_and_destination_rejected():
    with pytest.raises(ValidationError):
        FlightSearchRequest(
            origin="TPE",
            destination="TPE",
            depart_date="2026-10-18",
            return_date="2026-10-22",
        )


def test_official_browser_tasks_require_https():
    with client:
        response = client.post(
            "/api/browser/tasks",
            json={
                "kind": "flight_search",
                "source_url": "http://www.emirates.com/tw/chinese/book/",
                "instructions": "x",
            },
        )
    assert response.status_code == 400
