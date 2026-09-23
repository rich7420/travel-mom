#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / "recipes" / "official_hotel_search.json"


def main() -> int:
    data = json.loads(RECIPE.read_text())
    required = {
        "id", "kind", "recipe_version", "last_reviewed", "trust_policy", "safe_actions",
        "required_search_inputs", "required_output", "semantic_steps", "forbidden_actions",
        "stop_conditions", "regression_cases",
    }
    missing = sorted(required - set(data))
    errors: list[str] = []
    if missing:
        errors.append(f"missing keys: {missing}")
    if data.get("kind") != "hotel_search":
        errors.append("kind must be hotel_search")
    trust = data.get("trust_policy") or {}
    if trust.get("independent_property") != "requires_human_approved_HotelSiteGrant":
        errors.append("independent hotel trust must require human-approved grant")
    if trust.get("ota_as_official_site") != "deny":
        errors.append("OTA-as-official must be deny")
    forbidden = set(data.get("forbidden_actions") or [])
    for value in {"final_purchase", "payment", "enter_card", "bypass_captcha", "bypass_otp", "bypass_3ds"}:
        if value not in forbidden:
            errors.append(f"missing forbidden action: {value}")
    outputs = set(data.get("required_output") or [])
    for value in {"total_amount", "currency", "mandatory_property_fees", "refundable", "payment_timing", "observed_at"}:
        if value not in outputs:
            errors.append(f"missing required output: {value}")
    regressions = data.get("regression_cases") or []
    if len(regressions) < 4:
        errors.append("need at least four hotel regression cases")
    ids = [row.get("id") for row in regressions if isinstance(row, dict)]
    if len(ids) != len(set(ids)):
        errors.append("duplicate hotel regression case ids")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"OK: hotel semantic recipe audited; {len(regressions)} regression cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
