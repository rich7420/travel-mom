#!/usr/bin/env python3
"""Run the complete v0.6 workflow without OpenClaw or live travel data.

This is a deterministic integration demo, not a fare source. It creates an isolated
SQLite database, ingests typed sample airline results, compares them, revalidates one
option, and proves that a changed price blocks booking preflight until explicitly
accepted.
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


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _option(code: str, amount: int, outbound_hour: int, return_hour: int) -> dict:
    return {
        "option_id": f"{code}-demo-1",
        "total_amount": amount,
        "currency": "TWD",
        "fare_family": "Economy Standard",
        "cabin": "economy",
        "segments": [
            {
                "flight_number": f"{code}100",
                "marketing_airline": code,
                "operating_airline": code,
                "origin": "TPE",
                "destination": "NRT",
                "departure_local": f"2026-10-18T{outbound_hour:02d}:00+08:00",
                "arrival_local": f"2026-10-18T{outbound_hour + 4:02d}:00+09:00",
                "duration_minutes": 180,
            },
            {
                "flight_number": f"{code}101",
                "marketing_airline": code,
                "operating_airline": code,
                "origin": "NRT",
                "destination": "TPE",
                "departure_local": f"2026-10-22T{return_hour:02d}:00+09:00",
                "arrival_local": f"2026-10-22T{return_hour + 3:02d}:00+08:00",
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


def _search_result(code: str, name: str, url: str, option: dict) -> dict:
    return {
        "schema_version": "flight-search-v1",
        "airline_code": code,
        "airline_name": name,
        "source_url": url,
        "status": "ok",
        "observed_at": _now(),
        "currency": "TWD",
        "options": [option],
        "manual_handoff_reason": None,
        "notes": ["DEMO DATA — not a live quotation"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", help="SQLite path; defaults to a temporary file")
    parser.add_argument("--keep", action="store_true", help="keep the demo database")
    args = parser.parse_args()

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if args.db:
        db_path = Path(args.db).expanduser().resolve()
    elif args.keep:
        kept_dir = Path(tempfile.mkdtemp(prefix="mom-travel-v06-"))
        db_path = kept_dir / "demo.db"
    else:
        temp_dir = tempfile.TemporaryDirectory(prefix="mom-travel-v06-")
        db_path = Path(temp_dir.name) / "demo.db"
    if db_path.exists():
        db_path.unlink()

    os.environ["TRAVEL_DESK_DB"] = str(db_path)
    os.environ["OPENCLAW_ENABLED"] = "false"
    os.environ["APP_ENV"] = "dev"
    os.environ["BROWSER_LAB_INGEST_ENABLED"] = "true"

    from app.db import init_db
    from app.models import (
        BookingPreflightRequest,
        BrowserTaskIngestRequest,
        FlightRevalidationCreateRequest,
        FlightSearchRequest,
        TripCaseCreate,
    )
    from app.repositories import case_repo
    from app.services.booking_preflight import build_booking_preflight
    from app.services.browser_lab import build_browser_lab_summary
    from app.services.browser_tasks import browser_task_service
    from app.services.flight_revalidation import summarize_revalidation
    from app.services.official_compare import compare_official_flight_tasks

    init_db()
    trip = case_repo.create(
        TripCaseCreate(
            customer_name="示範客人",
            destination="東京",
            origin="TPE",
            depart_date="2026-10-18",
            return_date="2026-10-22",
            adults=2,
            notes="DEMO ONLY",
        )
    )
    plan = browser_task_service.create_flight_search(
        FlightSearchRequest(
            case_id=trip.id,
            airline_codes=["CI", "JX", "CX"],
            origin="TPE",
            destination="NRT",
            depart_date="2026-10-18",
            return_date="2026-10-22",
            adults=2,
            nonstop_preferred=True,
        )
    )

    providers = {
        "CI": ("中華航空", "https://booking.china-airlines.com/booking/Index", _option("CI", 15320, 8, 14)),
        "JX": ("星宇航空", "https://www.starlux-airlines.com/flights/en-tw/", _option("JX", 15780, 9, 15)),
        "CX": ("國泰航空", "https://www.cathaypacific.com/cx/en_TW/book-a-trip.html", _option("CX", 14900, 7, 13)),
    }
    for task in plan.tasks:
        name, url, option = providers[task.provider_code or ""]
        payload = _search_result(task.provider_code or "", name, url, option)
        browser_task_service.ingest(
            task.id,
            BrowserTaskIngestRequest(raw_text=json.dumps(payload, ensure_ascii=False)),
        )

    comparison = compare_official_flight_tasks([task.id for task in plan.tasks])
    ranked = comparison["currency_groups"][0]["ranked"]
    selected = ranked[0]
    revalidation = browser_task_service.create_revalidation(
        FlightRevalidationCreateRequest(
            search_task_id=selected["task_id"],
            option_id=selected["option"]["option_id"],
        )
    )
    current_option = json.loads(json.dumps(selected["option"]))
    current_option["total_amount"] = float(current_option["total_amount"]) + 300
    revalidation_payload = {
        "schema_version": "flight-revalidation-v1",
        "airline_code": selected["airline_code"],
        "airline_name": selected["airline_name"],
        "source_url": selected["source_url"],
        "status": "found",
        "observed_at": _now(),
        "original_option_id": selected["option"]["option_id"],
        "match_confidence": "exact",
        "current_option": current_option,
        "differences": ["DEMO: price increased by TWD 300"],
        "manual_handoff_reason": None,
        "notes": ["DEMO DATA — not a live quotation"],
    }
    browser_task_service.ingest(
        revalidation.id,
        BrowserTaskIngestRequest(raw_text=json.dumps(revalidation_payload, ensure_ascii=False)),
    )

    summary = summarize_revalidation(revalidation.id)
    blocked = build_booking_preflight(BookingPreflightRequest(revalidation_task_id=revalidation.id))
    accepted = build_booking_preflight(
        BookingPreflightRequest(revalidation_task_id=revalidation.id, accept_price_change=True)
    )
    lab = build_browser_lab_summary()

    output = {
        "database": str(db_path),
        "trip_case_id": trip.id,
        "search_run_id": plan.run.id if plan.run else None,
        "ranked": [
            {
                "airline": row["airline_code"],
                "amount": row["option"]["total_amount"],
                "score": row["score"],
            }
            for row in ranked
        ],
        "selected": {
            "airline": selected["airline_code"],
            "option_id": selected["option"]["option_id"],
        },
        "revalidation": summary.model_dump(mode="json"),
        "preflight_before_acceptance": {
            "ready": blocked.ready,
            "blockers": blocked.blockers,
        },
        "preflight_after_acceptance": {
            "ready": accepted.ready,
            "status": accepted.status,
            "payment_handled_by_agent": accepted.payment_handled_by_agent,
        },
        "browser_lab": lab,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))

    ok = (
        len(ranked) == 3
        and summary.requires_human_acceptance
        and not blocked.ready
        and accepted.ready
        and not accepted.payment_handled_by_agent
    )
    if args.keep and not args.db:
        print(f"Kept demo database: {db_path}")
    if temp_dir:
        temp_dir.cleanup()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
