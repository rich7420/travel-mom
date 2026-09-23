from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.db import init_db
from app.models import (
    BookingPreflightRequest,
    BrowserTaskIngestRequest,
    FlightRevalidationCreateRequest,
    FlightSearchRequest,
)
from app.repositories import browser_attempt_repo, browser_task_repo, flight_search_run_repo
from app.services.booking_preflight import build_booking_preflight
from app.services.browser_lab import build_browser_lab_summary
from app.services.browser_tasks import browser_task_service
from app.services.channel_router import route_channel_message
from app.services.flight_revalidation import summarize_revalidation
from app.services.official_compare import compare_official_flight_tasks


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _search_payload(code: str, source_url: str, amount: float = 15000, observed_at: str | None = None) -> dict:
    return {
        "schema_version": "flight-search-v1",
        "airline_code": code,
        "airline_name": code,
        "source_url": source_url,
        "status": "ok",
        "observed_at": observed_at or _iso_now(),
        "currency": "TWD",
        "options": [
            {
                "option_id": f"{code}-option-1",
                "total_amount": amount,
                "currency": "TWD",
                "fare_family": "Economy Flex",
                "cabin": "economy",
                "segments": [
                    {
                        "flight_number": f"{code}100",
                        "marketing_airline": code,
                        "operating_airline": code,
                        "origin": "TPE",
                        "destination": "NRT",
                        "departure_local": "2026-10-18T08:00+08:00",
                        "arrival_local": "2026-10-18T12:00+09:00",
                        "duration_minutes": 180,
                    },
                    {
                        "flight_number": f"{code}101",
                        "marketing_airline": code,
                        "operating_airline": code,
                        "origin": "NRT",
                        "destination": "TPE",
                        "departure_local": "2026-10-22T14:00+09:00",
                        "arrival_local": "2026-10-22T17:00+08:00",
                        "duration_minutes": 240,
                    },
                ],
                "stops": 0,
                "total_duration_minutes": 420,
                "checked_baggage": "23kg x 1",
                "carry_on": "7kg x 1",
                "change_rule_summary": "fee applies",
                "refund_rule_summary": "fee applies",
                "seat_selection": "paid",
                "warnings": [],
            }
        ],
        "notes": [],
    }


def _revalidation_payload(
    code: str,
    source_url: str,
    original_option: dict,
    current_amount: float,
    observed_at: str | None = None,
) -> dict:
    current = json.loads(json.dumps(original_option))
    current["total_amount"] = current_amount
    return {
        "schema_version": "flight-revalidation-v1",
        "airline_code": code,
        "airline_name": code,
        "source_url": source_url,
        "status": "found",
        "observed_at": observed_at or _iso_now(),
        "original_option_id": original_option["option_id"],
        "match_confidence": "exact",
        "current_option": current,
        "differences": [],
        "notes": [],
    }


def _create_ci_run():
    init_db()
    req = FlightSearchRequest(
        origin="TPE",
        destination="NRT",
        depart_date="2026-10-18",
        return_date="2026-10-22",
        adults=2,
        airline_codes=["CI"],
        nonstop_preferred=True,
    )
    return browser_task_service.create_flight_search(req)


def test_search_run_persists_and_groups_tasks():
    plan = _create_ci_run()
    assert plan.run is not None
    assert plan.run.task_ids == [plan.tasks[0].id]
    persisted = flight_search_run_repo.get(plan.run.id)
    assert persisted is not None
    assert persisted.request.origin == "TPE"
    assert persisted.task_ids == [plan.tasks[0].id]
    assert browser_task_repo.list(search_run_id=plan.run.id)[0].search_run_id == plan.run.id


def test_ingest_records_attempt_completes_run_and_compares():
    plan = _create_ci_run()
    task = plan.tasks[0]
    payload = _search_payload("CI", "https://booking.china-airlines.com/booking/Index")
    updated = browser_task_service.ingest(task.id, BrowserTaskIngestRequest(raw_text=json.dumps(payload)))
    assert updated.review_state == "auto_validated"
    attempts = browser_attempt_repo.list_for_task(task.id)
    assert attempts[-1].source == "lab_ingest"
    assert attempts[-1].outcome == "completed"
    run = flight_search_run_repo.get(plan.run.id)  # type: ignore[union-attr]
    assert run is not None and run.status.value == "completed"
    comparison = compare_official_flight_tasks([task.id])
    assert comparison["currency_groups"][0]["ranked"][0]["option"]["option_id"] == "CI-option-1"


def test_ingest_wrong_route_needs_review_and_telemetry():
    plan = _create_ci_run()
    task = plan.tasks[0]
    payload = _search_payload("CI", "https://booking.china-airlines.com/booking/Index")
    payload["options"][0]["segments"][0]["destination"] = "KIX"
    updated = browser_task_service.ingest(task.id, BrowserTaskIngestRequest(raw_text=json.dumps(payload)))
    assert updated.status == "needs_review"
    attempts = browser_attempt_repo.list_for_task(task.id)
    assert any("去程" in err for err in attempts[-1].validation_errors)
    lab = build_browser_lab_summary()
    ci = next(row for row in lab["providers"] if row["airline_code"] == "CI")
    assert ci["validation_error_attempts"] >= 1


def test_revalidation_unchanged_and_booking_preflight_ready():
    plan = _create_ci_run()
    search_task = plan.tasks[0]
    search_payload = _search_payload("CI", "https://booking.china-airlines.com/booking/Index")
    browser_task_service.ingest(search_task.id, BrowserTaskIngestRequest(raw_text=json.dumps(search_payload)))

    reval = browser_task_service.create_revalidation(
        FlightRevalidationCreateRequest(search_task_id=search_task.id, option_id="CI-option-1")
    )
    payload = _revalidation_payload(
        "CI",
        "https://booking.china-airlines.com/booking/Index",
        search_payload["options"][0],
        current_amount=15000,
    )
    browser_task_service.ingest(reval.id, BrowserTaskIngestRequest(raw_text=json.dumps(payload)))
    summary = summarize_revalidation(reval.id)
    assert summary.status == "unchanged"
    assert summary.requires_human_acceptance is False
    preflight = build_booking_preflight(BookingPreflightRequest(revalidation_task_id=reval.id))
    assert preflight.ready is True
    assert preflight.status == "ready_for_human_checkout"
    assert preflight.payment_handled_by_agent is False


def test_revalidation_price_change_requires_explicit_acceptance():
    plan = _create_ci_run()
    search_task = plan.tasks[0]
    search_payload = _search_payload("CI", "https://booking.china-airlines.com/booking/Index")
    browser_task_service.ingest(search_task.id, BrowserTaskIngestRequest(raw_text=json.dumps(search_payload)))
    reval = browser_task_service.create_revalidation(
        FlightRevalidationCreateRequest(search_task_id=search_task.id, option_id="CI-option-1")
    )
    payload = _revalidation_payload(
        "CI",
        "https://booking.china-airlines.com/booking/Index",
        search_payload["options"][0],
        current_amount=15600,
    )
    browser_task_service.ingest(reval.id, BrowserTaskIngestRequest(raw_text=json.dumps(payload)))
    summary = summarize_revalidation(reval.id)
    assert summary.status == "changed"
    assert summary.delta_amount == 600
    blocked = build_booking_preflight(BookingPreflightRequest(revalidation_task_id=reval.id))
    assert blocked.ready is False
    assert any("尚未明確接受" in reason for reason in blocked.blockers)
    accepted = build_booking_preflight(
        BookingPreflightRequest(revalidation_task_id=reval.id, accept_price_change=True)
    )
    assert accepted.ready is True


def test_stale_revalidation_blocks_preflight():
    plan = _create_ci_run()
    search_task = plan.tasks[0]
    search_payload = _search_payload("CI", "https://booking.china-airlines.com/booking/Index")
    browser_task_service.ingest(search_task.id, BrowserTaskIngestRequest(raw_text=json.dumps(search_payload)))
    reval = browser_task_service.create_revalidation(
        FlightRevalidationCreateRequest(search_task_id=search_task.id, option_id="CI-option-1")
    )
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(microsecond=0).isoformat()
    payload = _revalidation_payload(
        "CI",
        "https://booking.china-airlines.com/booking/Index",
        search_payload["options"][0],
        current_amount=15000,
        observed_at=stale,
    )
    browser_task_service.ingest(reval.id, BrowserTaskIngestRequest(raw_text=json.dumps(payload)))
    preflight = build_booking_preflight(BookingPreflightRequest(revalidation_task_id=reval.id))
    assert preflight.ready is False
    assert any("已過期" in reason for reason in preflight.blockers)


@pytest.mark.asyncio
async def test_channel_router_has_menu_and_guided_mode():
    menu = await route_channel_message("line:test-router", "開始")
    assert "旅行社工作助理" in menu.text
    assert "➕ 新客人" in menu.options
    first = await route_channel_message("line:test-router", "新客人")
    assert "哪一位客人" in first.text
    second = await route_channel_message("line:test-router", "林小姐")
    assert "想去哪裡" in second.text

@pytest.mark.asyncio
async def test_channel_cancel_clears_guided_state():
    session_id = "line:test-cancel"
    first = await route_channel_message(session_id, "新客人")
    assert "哪一位客人" in first.text
    cancelled = await route_channel_message(session_id, "取消")
    assert cancelled.source == "cancelled"
    after = await route_channel_message(session_id, "今日工作")
    assert after.source == "radar"


def test_inbound_event_idempotency_replays_without_reprocessing():
    from app.repositories import inbound_event_repo

    channel = "test"
    event_id = "evt-001"
    payload_hash = "abc123"
    state, saved = inbound_event_repo.claim(channel, event_id, payload_hash)
    assert state == "new" and saved is None
    inbound_event_repo.store_response(channel, event_id, {"text": "same answer", "options": [], "source": "test"})
    state, saved = inbound_event_repo.claim(channel, event_id, payload_hash)
    assert state == "replay"
    assert saved["text"] == "same answer"
    inbound_event_repo.mark_delivered(channel, event_id)
    state, _ = inbound_event_repo.claim(channel, event_id, payload_hash)
    assert state == "delivered"


def test_connecting_itinerary_is_valid_when_segment_chain_matches():
    plan = _create_ci_run()
    task = plan.tasks[0]
    payload = _search_payload("CI", "https://booking.china-airlines.com/booking/Index")
    payload["options"][0]["segments"] = [
        {
            "flight_number": "CI900",
            "marketing_airline": "CI",
            "operating_airline": "CI",
            "origin": "TPE",
            "destination": "HKG",
            "departure_local": "2026-10-18T08:00+08:00",
            "arrival_local": "2026-10-18T10:00+08:00",
            "duration_minutes": 120,
        },
        {
            "flight_number": "CI910",
            "marketing_airline": "CI",
            "operating_airline": "CI",
            "origin": "HKG",
            "destination": "NRT",
            "departure_local": "2026-10-18T12:00+08:00",
            "arrival_local": "2026-10-18T17:00+09:00",
            "duration_minutes": 240,
        },
        {
            "flight_number": "CI911",
            "marketing_airline": "CI",
            "operating_airline": "CI",
            "origin": "NRT",
            "destination": "HKG",
            "departure_local": "2026-10-22T10:00+09:00",
            "arrival_local": "2026-10-22T14:00+08:00",
            "duration_minutes": 300,
        },
        {
            "flight_number": "CI901",
            "marketing_airline": "CI",
            "operating_airline": "CI",
            "origin": "HKG",
            "destination": "TPE",
            "departure_local": "2026-10-22T16:00+08:00",
            "arrival_local": "2026-10-22T18:00+08:00",
            "duration_minutes": 120,
        },
    ]
    payload["options"][0]["stops"] = 2
    updated = browser_task_service.ingest(task.id, BrowserTaskIngestRequest(raw_text=json.dumps(payload)))
    assert updated.status == "completed"
    assert updated.review_state == "auto_validated"


def test_comparison_marks_twd_budget_tradeoff_without_hiding_option():
    init_db()
    req = FlightSearchRequest(
        origin="TPE",
        destination="NRT",
        depart_date="2026-10-18",
        return_date="2026-10-22",
        adults=1,
        airline_codes=["CI", "JX"],
        max_total_twd=15200,
    )
    plan = browser_task_service.create_flight_search(req)
    amounts = {"CI": 15000, "JX": 16000}
    urls = {
        "CI": "https://booking.china-airlines.com/booking/Index",
        "JX": "https://www.starlux-airlines.com/flights/en-tw/",
    }
    for task in plan.tasks:
        payload = _search_payload(task.provider_code or "", urls[task.provider_code or ""], amounts[task.provider_code or ""])
        browser_task_service.ingest(task.id, BrowserTaskIngestRequest(raw_text=json.dumps(payload)))
    comparison = compare_official_flight_tasks([task.id for task in plan.tasks])
    rows = comparison["currency_groups"][0]["ranked"]
    assert len(rows) == 2
    ci = next(row for row in rows if row["airline_code"] == "CI")
    jx = next(row for row in rows if row["airline_code"] == "JX")
    assert any("預算內" in reason for reason in ci["reasons"])
    assert any("超過" in reason for reason in jx["reasons"])


def test_browser_lab_rates_are_attempt_specific_after_retry():
    plan = _create_ci_run()
    task = plan.tasks[0]

    no_results = _search_payload("CI", "https://booking.china-airlines.com/booking/Index")
    no_results["status"] = "no_results"
    no_results["currency"] = None
    no_results["options"] = []
    browser_task_service.ingest(task.id, BrowserTaskIngestRequest(raw_text=json.dumps(no_results)))

    ok = _search_payload("CI", "https://booking.china-airlines.com/booking/Index")
    browser_task_service.ingest(task.id, BrowserTaskIngestRequest(raw_text=json.dumps(ok)))

    attempts = browser_attempt_repo.list_for_task(task.id)
    assert [attempt.result_status for attempt in attempts] == ["no_results", "ok"]

    lab = build_browser_lab_summary(task_ids={task.id})
    ci = next(row for row in lab["providers"] if row["airline_code"] == "CI")
    assert ci["contract_validation_rate"] == 1.0
    assert ci["usable_success_rate"] == 0.5
    assert ci["result_statuses"]["no_results"] == 1
    assert ci["result_statuses"]["ok"] == 1
