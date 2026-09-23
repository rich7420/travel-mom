from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.db import init_db
from app.models import (
    BrowserTaskIngestRequest,
    HotelBookingPreflightRequest,
    HotelRevalidationCreateRequest,
    HotelSearchRequest,
    HotelSiteGrantCreate,
)
from app.repositories import hotel_search_run_repo, hotel_site_grant_repo
from app.services.browser_tasks import browser_task_service
from app.services.hotel_booking_preflight import build_hotel_booking_preflight
from app.services.hotel_compare import compare_official_hotel_tasks
from app.services.hotel_revalidation import summarize_hotel_revalidation
from app.services.hotel_trust import approve_independent_hotel_site, is_trusted_hotel_url


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _hotel_search_payload(source_url: str, hotel_name: str = "Hilton Tokyo", amount: float = 52000) -> dict:
    return {
        "schema_version": "hotel-search-v1",
        "hotel_name": hotel_name,
        "source_url": source_url,
        "status": "ok",
        "observed_at": _now(),
        "checkin_date": "2026-10-18",
        "checkout_date": "2026-10-22",
        "rooms": 1,
        "adults": 2,
        "children_ages": [],
        "currency": "TWD",
        "options": [
            {
                "option_id": "room-1",
                "room_name": "Deluxe King",
                "bed_type": "1 king",
                "rate_name": "Flexible Rate",
                "occupancy_summary": "2 adults",
                "total_amount": amount,
                "currency": "TWD",
                "base_amount": amount - 6000,
                "taxes_and_fees": 5000,
                "mandatory_property_fees": 1000,
                "breakfast_included": True,
                "refundable": True,
                "cancellation_deadline_local": "2026-10-16T18:00+09:00",
                "payment_timing": "pay_at_property",
                "member_rate": False,
                "loyalty_required": False,
                "resort_fee_included": True,
                "warnings": [],
            }
        ],
        "notes": [],
    }


def _hotel_revalidation_payload(search_payload: dict, amount: float) -> dict:
    current = json.loads(json.dumps(search_payload["options"][0]))
    current["total_amount"] = amount
    # keep the breakdown internally consistent
    current["base_amount"] = amount - 6000
    return {
        "schema_version": "hotel-revalidation-v1",
        "hotel_name": search_payload["hotel_name"],
        "source_url": search_payload["source_url"],
        "status": "found",
        "observed_at": _now(),
        "original_option_id": "room-1",
        "match_confidence": "exact",
        "current_option": current,
        "differences": [],
        "notes": [],
    }


def _create_hilton_plan():
    init_db()
    req = HotelSearchRequest(
        hotel_name="Hilton Tokyo",
        official_url="https://www.hilton.com/en/hotels/tyohitw-hilton-tokyo/",
        checkin_date="2026-10-18",
        checkout_date="2026-10-22",
        rooms=1,
        adults=2,
        breakfast_required=True,
        free_cancellation_preferred=True,
    )
    return browser_task_service.create_hotel_search(req)


def test_builtin_hotel_network_is_trusted_and_search_run_persists():
    assert is_trusted_hotel_url("https://www.hilton.com/en/") is True
    plan = _create_hilton_plan()
    persisted = hotel_search_run_repo.get(plan.run.id)
    assert persisted is not None
    assert persisted.request.hotel_name == "Hilton Tokyo"
    assert persisted.task_ids == [plan.task.id]


def test_hotel_search_validation_compare_revalidation_and_preflight():
    plan = _create_hilton_plan()
    source = "https://www.hilton.com/en/hotels/tyohitw-hilton-tokyo/"
    payload = _hotel_search_payload(source)
    updated = browser_task_service.ingest(plan.task.id, BrowserTaskIngestRequest(raw_text=json.dumps(payload)))
    assert updated.review_state == "auto_validated"

    comparison = compare_official_hotel_tasks([plan.task.id])
    ranked = comparison["currency_groups"][0]["ranked"][0]
    assert ranked["option"]["total_amount"] == 52000
    assert any("早餐" in reason for reason in ranked["reasons"])

    reval = browser_task_service.create_hotel_revalidation(
        HotelRevalidationCreateRequest(search_task_id=plan.task.id, option_id="room-1")
    )
    reval_payload = _hotel_revalidation_payload(payload, 53000)
    browser_task_service.ingest(reval.id, BrowserTaskIngestRequest(raw_text=json.dumps(reval_payload)))
    summary = summarize_hotel_revalidation(reval.id)
    assert summary.status == "changed"
    assert summary.delta_amount == 1000

    blocked = build_hotel_booking_preflight(HotelBookingPreflightRequest(revalidation_task_id=reval.id))
    assert blocked.ready is False
    accepted = build_hotel_booking_preflight(
        HotelBookingPreflightRequest(revalidation_task_id=reval.id, accept_price_or_terms_change=True)
    )
    assert accepted.ready is True
    assert accepted.payment_handled_by_agent is False


def test_unknown_independent_hotel_requires_human_site_grant():
    init_db()
    url = "https://www.independent-example-hotel.com/booking"
    req = HotelSearchRequest(
        hotel_name="Independent Example Hotel",
        official_url=url,
        checkin_date="2026-10-18",
        checkout_date="2026-10-20",
        adults=2,
    )
    with pytest.raises(ValueError, match="尚未信任"):
        browser_task_service.create_hotel_search(req)

    grant = approve_independent_hotel_site(HotelSiteGrantCreate(
        hotel_name="Independent Example Hotel",
        official_url=url,
        trust_source="human",
        notes="Human checked the hotel's own About/booking links.",
    ))
    assert grant.status.value == "approved"
    assert hotel_site_grant_repo.get_by_domain("www.independent-example-hotel.com") is not None
    plan = browser_task_service.create_hotel_search(req)
    assert plan.task.source_url == url


def test_ota_cannot_be_attested_as_official_hotel_site():
    with pytest.raises(ValueError, match="OTA"):
        approve_independent_hotel_site(HotelSiteGrantCreate(
            hotel_name="Not Official",
            official_url="https://www.booking.com/hotel/example.html",
            trust_source="human",
        ))


def test_browser_lab_groups_hotel_supplier_by_official_host():
    from app.services.browser_lab import build_browser_lab_summary

    plan = _create_hilton_plan()
    payload = _hotel_search_payload("https://www.hilton.com/en/hotels/tyohitw-hilton-tokyo/")
    browser_task_service.ingest(plan.task.id, BrowserTaskIngestRequest(raw_text=json.dumps(payload)))
    report = build_browser_lab_summary(task_ids={plan.task.id})
    row = report['providers'][0]
    assert row['provider_type'] == 'hotel'
    assert row['provider_key'] == 'hilton.com'
    assert row['hotel_search_tasks'] == 1
