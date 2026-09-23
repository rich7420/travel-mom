#!/usr/bin/env python3
"""Run the v0.7 hotel official-site workflow with deterministic demo data.

No live website is contacted. The script proves the typed pipeline:
TripCase -> trusted official hotel site -> HotelSearchRun -> validated room result ->
comparison -> exact revalidation -> change acceptance gate -> human-checkout preflight.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if args.db:
        db_path = Path(args.db).expanduser().resolve()
    elif args.keep:
        db_path = Path(tempfile.mkdtemp(prefix="mom-travel-v07-")) / "demo.db"
    else:
        temp_dir = tempfile.TemporaryDirectory(prefix="mom-travel-v07-")
        db_path = Path(temp_dir.name) / "demo.db"
    if db_path.exists():
        db_path.unlink()

    os.environ.update({
        "TRAVEL_DESK_DB": str(db_path),
        "OPENCLAW_ENABLED": "false",
        "APP_ENV": "dev",
        "BROWSER_LAB_INGEST_ENABLED": "true",
    })

    from app.db import init_db
    from app.models import (
        BrowserTaskIngestRequest,
        HotelBookingPreflightRequest,
        HotelRevalidationCreateRequest,
        HotelSearchRequest,
        TripCaseCreate,
    )
    from app.repositories import case_repo
    from app.services.browser_tasks import browser_task_service
    from app.services.hotel_booking_preflight import build_hotel_booking_preflight
    from app.services.hotel_compare import compare_official_hotel_tasks
    from app.services.hotel_revalidation import summarize_hotel_revalidation

    init_db()
    trip = case_repo.create(TripCaseCreate(
        customer_name="示範客人",
        destination="東京",
        origin="TPE",
        depart_date="2026-10-18",
        return_date="2026-10-22",
        adults=2,
        notes="DEMO ONLY",
    ))
    plan = browser_task_service.create_hotel_search(HotelSearchRequest(
        case_id=trip.id,
        hotel_name="Hilton Tokyo",
        official_url="https://www.hilton.com/en/hotels/tyohitw-hilton-tokyo/",
        checkin_date="2026-10-18",
        checkout_date="2026-10-22",
        rooms=1,
        adults=2,
        currency_preference="TWD",
        breakfast_required=True,
        free_cancellation_preferred=True,
        max_total_twd=60000,
    ))

    search_payload = {
        "schema_version": "hotel-search-v1",
        "hotel_name": "Hilton Tokyo",
        "source_url": "https://www.hilton.com/en/hotels/tyohitw-hilton-tokyo/",
        "status": "ok",
        "observed_at": now(),
        "checkin_date": "2026-10-18",
        "checkout_date": "2026-10-22",
        "rooms": 1,
        "adults": 2,
        "children_ages": [],
        "currency": "TWD",
        "options": [
            {
                "option_id": "hilton-flex-king",
                "room_name": "Deluxe King",
                "bed_type": "1 king",
                "rate_name": "Flexible Rate",
                "occupancy_summary": "2 adults",
                "total_amount": 52000,
                "currency": "TWD",
                "base_amount": 46000,
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
            },
            {
                "option_id": "hilton-advance-king",
                "room_name": "Deluxe King",
                "bed_type": "1 king",
                "rate_name": "Advance Purchase",
                "occupancy_summary": "2 adults",
                "total_amount": 48000,
                "currency": "TWD",
                "base_amount": 42500,
                "taxes_and_fees": 4500,
                "mandatory_property_fees": 1000,
                "breakfast_included": False,
                "refundable": False,
                "cancellation_deadline_local": None,
                "payment_timing": "pay_now",
                "member_rate": False,
                "loyalty_required": False,
                "resort_fee_included": True,
                "warnings": ["non-refundable"],
            },
        ],
        "manual_handoff_reason": None,
        "notes": ["DEMO DATA — not live availability"],
    }
    browser_task_service.ingest(
        plan.task.id,
        BrowserTaskIngestRequest(raw_text=json.dumps(search_payload, ensure_ascii=False)),
    )
    comparison = compare_official_hotel_tasks([plan.task.id])
    ranked = comparison["currency_groups"][0]["ranked"]
    selected = ranked[0]

    reval = browser_task_service.create_hotel_revalidation(HotelRevalidationCreateRequest(
        search_task_id=selected["task_id"],
        option_id=selected["option"]["option_id"],
    ))
    current = json.loads(json.dumps(selected["option"]))
    current["total_amount"] = float(current["total_amount"]) + 1200
    if current.get("base_amount") is not None:
        current["base_amount"] = float(current["base_amount"]) + 1200
    reval_payload = {
        "schema_version": "hotel-revalidation-v1",
        "hotel_name": "Hilton Tokyo",
        "source_url": "https://www.hilton.com/en/hotels/tyohitw-hilton-tokyo/",
        "status": "found",
        "observed_at": now(),
        "original_option_id": selected["option"]["option_id"],
        "match_confidence": "exact",
        "current_option": current,
        "differences": ["DEMO: total increased by TWD 1,200"],
        "manual_handoff_reason": None,
        "notes": ["DEMO DATA — not live availability"],
    }
    browser_task_service.ingest(
        reval.id,
        BrowserTaskIngestRequest(raw_text=json.dumps(reval_payload, ensure_ascii=False)),
    )
    summary = summarize_hotel_revalidation(reval.id)
    blocked = build_hotel_booking_preflight(HotelBookingPreflightRequest(revalidation_task_id=reval.id))
    accepted = build_hotel_booking_preflight(HotelBookingPreflightRequest(
        revalidation_task_id=reval.id,
        accept_price_or_terms_change=True,
    ))

    output = {
        "database": str(db_path),
        "trip_case_id": trip.id,
        "hotel_search_run_id": plan.run.id,
        "ranked_options": [
            {
                "rate": row["option"]["rate_name"],
                "amount": row["option"]["total_amount"],
                "refundable": row["option"]["refundable"],
                "breakfast": row["option"]["breakfast_included"],
                "score": row["score"],
            }
            for row in ranked
        ],
        "selected": selected["option"]["option_id"],
        "revalidation": summary.model_dump(mode="json"),
        "preflight_before_acceptance": {"ready": blocked.ready, "blockers": blocked.blockers},
        "preflight_after_acceptance": {
            "ready": accepted.ready,
            "status": accepted.status,
            "payment_handled_by_agent": accepted.payment_handled_by_agent,
        },
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))

    ok = (
        len(ranked) == 2
        and summary.requires_human_acceptance
        and not blocked.ready
        and accepted.ready
        and accepted.status == "ready_for_human_checkout"
        and not accepted.payment_handled_by_agent
    )
    if args.keep and not args.db:
        print(f"Kept demo database: {db_path}")
    if temp_dir:
        temp_dir.cleanup()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
