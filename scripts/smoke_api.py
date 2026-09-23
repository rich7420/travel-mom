#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    with TemporaryDirectory(prefix="mom-travel-api-smoke-") as tmp:
        os.environ["TRAVEL_DESK_DB"] = str(Path(tmp) / "smoke.db")
        os.environ["OPENCLAW_ENABLED"] = "false"
        os.environ["LINE_ENABLED"] = "false"
        os.environ["TELEGRAM_ENABLED"] = "false"

        from fastapi.testclient import TestClient

        from app.main import app

        with TestClient(app) as client:
            health = client.get("/health")
            readiness = client.get("/api/system/readiness")
            airlines = client.get("/api/airlines")
            created = client.post(
                "/api/browser/flight-search",
                json={
                    "airline_codes": ["CI", "JX", "CX"],
                    "origin": "TPE",
                    "destination": "NRT",
                    "depart_date": "2026-10-18",
                    "return_date": "2026-10-22",
                    "adults": 1,
                    "children": 0,
                    "infants": 0,
                    "cabin": "economy",
                },
            )

            hotels = client.get("/api/hotels/networks")
            hotel_created = client.post(
                "/api/browser/hotel-search",
                json={
                    "hotel_name": "Hilton Tokyo",
                    "official_url": "https://www.hilton.com/en/hotels/tyohitw-hilton-tokyo/",
                    "checkin_date": "2026-10-18",
                    "checkout_date": "2026-10-22",
                    "rooms": 1,
                    "adults": 2,
                },
            )

            for response in (health, readiness, airlines, created, hotels, hotel_created):
                response.raise_for_status()

            run_id = created.json()["run"]["id"]
            run = client.get(f"/api/browser/runs/{run_id}")
            lab = client.get("/api/browser/lab/summary")
            run.raise_for_status()
            lab.raise_for_status()

            output = {
                "health": health.json(),
                "readiness": {
                    "offline_poc_ready": readiness.json()["offline_poc_ready"],
                    "live_browser_lab_configured": readiness.json()["live_browser_lab_configured"],
                    "mom_line_pilot_configured": readiness.json()["mom_line_pilot_configured"],
                },
                "airlines": [row["code"] for row in airlines.json()["airlines"]],
                "search_run": {
                    "id": run_id,
                    "status": run.json()["run"]["status"],
                    "tasks": len(run.json()["tasks"]),
                },
                "hotel_networks": [row["code"] for row in hotels.json()["networks"]],
                "hotel_search_run": {
                    "id": hotel_created.json()["run"]["id"],
                    "schema": hotel_created.json()["task"]["expected_schema"],
                },
                "browser_lab_schema": lab.json()["schema_version"],
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
