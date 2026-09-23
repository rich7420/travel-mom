#!/usr/bin/env python3
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import re
from urllib.parse import urlparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.airlines import AIRLINES, RECIPE_ROOT, host_matches_domain

REQUIRED = {
    "recipe_version",
    "last_reviewed",
    "airline_code",
    "airline",
    "risk_level",
    "official_domains",
    "supported_schemas",
    "browser_profile_policy",
    "strategy",
    "start_url",
    "expected_inputs",
    "workflow",
    "special_rules",
    "known_blockers",
    "revalidate",
    "safety",
    "failure_policy",
    "regression_cases",
}
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
REQUIRED_SCHEMAS = {"flight-search-v1", "flight-revalidation-v1"}


def main() -> int:
    errors: list[str] = []
    regression_ids: set[str] = set()

    for code, airline in AIRLINES.items():
        path = RECIPE_ROOT / f"{code}.json"
        if not path.exists():
            errors.append(f"{code}: missing recipe {path}")
            continue
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{code}: invalid JSON: {exc}")
            continue

        missing = REQUIRED - set(obj)
        if missing:
            errors.append(f"{code}: missing fields {sorted(missing)}")
        if obj.get("airline_code") != code:
            errors.append(f"{code}: recipe airline_code mismatch")
        if not SEMVER_RE.fullmatch(str(obj.get("recipe_version", ""))):
            errors.append(f"{code}: recipe_version must be semver")
        try:
            date.fromisoformat(str(obj.get("last_reviewed", "")))
        except ValueError:
            errors.append(f"{code}: last_reviewed must be ISO date")

        host = (urlparse(obj.get("start_url", "")).hostname or "").lower()
        if not any(host_matches_domain(host, domain) for domain in airline.allowed_domains):
            errors.append(f"{code}: start_url not on official domain: {host}")

        domains = obj.get("official_domains") or []
        if not domains:
            errors.append(f"{code}: official_domains empty")
        for domain in domains:
            if not any(host_matches_domain(domain, allowed) or host_matches_domain(allowed, domain) for allowed in airline.allowed_domains):
                errors.append(f"{code}: recipe domain not represented in registry allowlist: {domain}")

        if not REQUIRED_SCHEMAS.issubset(set(obj.get("supported_schemas") or [])):
            errors.append(f"{code}: supported_schemas missing {sorted(REQUIRED_SCHEMAS)}")
        if obj.get("browser_profile_policy") not in {"isolated_default", "human_selected_login"}:
            errors.append(f"{code}: invalid browser_profile_policy")
        if not obj.get("workflow"):
            errors.append(f"{code}: empty workflow")

        safety = " ".join(str(item) for item in obj.get("safety") or []).lower()
        for token in ("payment", "cvv", "otp", "3ds", "captcha", "official domains"):
            if token not in safety:
                errors.append(f"{code}: safety missing token {token!r}")

        cases = obj.get("regression_cases") or []
        if len(cases) < 2:
            errors.append(f"{code}: at least two regression_cases required")
        for case in cases:
            case_id = str(case.get("id", ""))
            if not case_id:
                errors.append(f"{code}: regression case missing id")
            elif case_id in regression_ids:
                errors.append(f"duplicate regression case id: {case_id}")
            regression_ids.add(case_id)
            for field in ("task", "origin", "destination", "expected"):
                if not case.get(field):
                    errors.append(f"{code}/{case_id or '?'}: missing {field}")

    extras = {path.stem for path in RECIPE_ROOT.glob("*.json")} - set(AIRLINES)
    if extras:
        errors.append(f"recipes without registry entries: {sorted(extras)}")
    if errors:
        for error in errors:
            print("ERROR:", error)
        return 1
    print(f"OK: {len(AIRLINES)} airline recipes audited; {len(regression_ids)} regression cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
