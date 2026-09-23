from __future__ import annotations

import json
from datetime import datetime, timezone
from json import JSONDecoder
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError

from app.airlines import get_airline, host_matches_domain
from app.models import FlightOption, FlightRevalidationResultV1, FlightSearchResultV1


def extract_first_json_object(text: str) -> dict | None:
    """Extract the first valid JSON object even if the model wrapped it in prose/fences."""
    decoder = JSONDecoder()
    for idx, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _validate_timestamp(value: str, field: str, errors: list[str]) -> None:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{field} 不是有效 ISO-8601 timestamp")
        return
    if dt.tzinfo is None:
        errors.append(f"{field} 必須包含 timezone")
        return
    # A page clock can drift slightly, but a result far in the future is not trustworthy.
    if dt.astimezone(timezone.utc) > datetime.now(timezone.utc).replace(microsecond=0):
        delta = (dt.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds()
        if delta > 300:
            errors.append(f"{field} 超過目前時間 5 分鐘")


def _validate_official_source(source_url: str, expected_airline_code: str, errors: list[str]) -> None:
    expected = get_airline(expected_airline_code)
    if expected is None:
        errors.append(f"未知 expected airline: {expected_airline_code}")
        return
    parsed = urlparse(source_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        errors.append("result source_url 必須使用 https")
    if not any(host_matches_domain(host, d) for d in expected.allowed_domains):
        errors.append(f"result source_url 不屬於 {expected.code} 官方 domain: {host}")


def _find_contiguous_path(
    segments: list,
    start_airport: str,
    end_airport: str,
    start_index: int = 0,
) -> tuple[list, int] | None:
    """Find an ordered itinerary path, including connections.

    Browser results commonly return TPE-HKG + HKG-NRT rather than a synthetic
    TPE-NRT segment. The previous validator incorrectly rejected every connecting
    itinerary, so validation follows the actual contiguous segment chain instead.
    """

    for first in range(start_index, len(segments)):
        if segments[first].origin.upper() != start_airport:
            continue
        current = start_airport
        path: list = []
        for index in range(first, len(segments)):
            segment = segments[index]
            if segment.origin.upper() != current:
                break
            path.append(segment)
            current = segment.destination.upper()
            if current == end_airport:
                return path, index + 1
    return None


def _validate_route_and_dates(result: FlightSearchResultV1, expected_search: dict[str, Any], errors: list[str]) -> None:
    origin = str(expected_search.get("origin") or "").upper()
    destination = str(expected_search.get("destination") or "").upper()
    depart_date = str(expected_search.get("depart_date") or "")
    return_date = str(expected_search.get("return_date") or "")
    trip_type = str(expected_search.get("trip_type") or "round_trip")

    seen_ids: set[str] = set()
    for idx, option in enumerate(result.options):
        if option.option_id in seen_ids:
            errors.append(f"option[{idx}] option_id 重複")
        seen_ids.add(option.option_id)
        if option.total_amount <= 0:
            errors.append(f"option[{idx}] total_amount 必須 > 0")
        if not option.segments:
            errors.append(f"option[{idx}] 缺少 segments")
            continue

        for seg_idx, segment in enumerate(option.segments):
            segment.origin = segment.origin.strip().upper()
            segment.destination = segment.destination.strip().upper()
            if (
                len(segment.origin) != 3
                or not segment.origin.isalpha()
                or len(segment.destination) != 3
                or not segment.destination.isalpha()
            ):
                errors.append(f"option[{idx}].segments[{seg_idx}] IATA code 格式不正確")
            if not segment.flight_number.strip():
                errors.append(f"option[{idx}].segments[{seg_idx}] 缺少 flight_number")

        if origin and destination:
            outbound_match = _find_contiguous_path(option.segments, origin, destination)
        else:
            outbound_match = None
        if origin and destination and not outbound_match:
            errors.append(f"option[{idx}] 找不到連續的要求去程 {origin}->{destination}")
            continue

        next_index = 0
        if outbound_match:
            outbound, next_index = outbound_match
            if depart_date and not (outbound[0].departure_local or "").startswith(depart_date):
                errors.append(f"option[{idx}] 去程日期與 requested depart_date 不一致")

        if trip_type == "round_trip" and origin and destination:
            return_match = _find_contiguous_path(option.segments, destination, origin, next_index)
            if not return_match:
                errors.append(f"option[{idx}] 找不到連續的要求回程 {destination}->{origin}")
            else:
                inbound, _ = return_match
                if return_date and not (inbound[0].departure_local or "").startswith(return_date):
                    errors.append(f"option[{idx}] 回程日期與 requested return_date 不一致")

        if result.currency and option.currency.upper() != result.currency.upper():
            errors.append(
                f"option[{idx}] currency {option.currency} 與 result currency {result.currency} 不一致"
            )


def validate_flight_search_result(
    text: str,
    expected_airline_code: str,
    expected_search: dict[str, Any] | None = None,
) -> tuple[FlightSearchResultV1 | None, list[str]]:
    errors: list[str] = []
    raw = extract_first_json_object(text)
    if raw is None:
        return None, ["沒有找到可解析的 JSON object"]
    try:
        result = FlightSearchResultV1.model_validate(raw)
    except ValidationError as exc:
        return None, [f"schema validation failed: {err['loc']}: {err['msg']}" for err in exc.errors()[:12]]

    if result.airline_code != expected_airline_code.upper():
        errors.append(f"airline_code mismatch: expected {expected_airline_code.upper()}, got {result.airline_code}")
    _validate_official_source(result.source_url, expected_airline_code, errors)
    _validate_timestamp(result.observed_at, "observed_at", errors)
    if result.status == "ok" and not result.options:
        errors.append("status=ok 但 options 為空")
    if result.status == "manual_required" and not result.manual_handoff_reason:
        errors.append("manual_required 缺少 manual_handoff_reason")

    if result.status == "ok":
        _validate_route_and_dates(result, expected_search or {}, errors)
    return result, errors


def _segment_identity(option: FlightOption) -> list[tuple[str, str, str, str]]:
    """Identity deliberately excludes times/duration so a schedule shift can be reported, not silently mismatched."""
    return [
        (
            seg.flight_number.strip().upper(),
            seg.origin.strip().upper(),
            seg.destination.strip().upper(),
            (seg.departure_local or "")[:10],
        )
        for seg in option.segments
    ]


def validate_flight_revalidation_result(
    text: str,
    expected_airline_code: str,
    expected_option_id: str,
    original_option: FlightOption,
) -> tuple[FlightRevalidationResultV1 | None, list[str]]:
    errors: list[str] = []
    raw = extract_first_json_object(text)
    if raw is None:
        return None, ["沒有找到可解析的 JSON object"]
    try:
        result = FlightRevalidationResultV1.model_validate(raw)
    except ValidationError as exc:
        return None, [f"schema validation failed: {err['loc']}: {err['msg']}" for err in exc.errors()[:12]]

    if result.airline_code != expected_airline_code.upper():
        errors.append(f"airline_code mismatch: expected {expected_airline_code.upper()}, got {result.airline_code}")
    if result.original_option_id != expected_option_id:
        errors.append("original_option_id 與要求重新驗價的 option 不一致")
    _validate_official_source(result.source_url, expected_airline_code, errors)
    _validate_timestamp(result.observed_at, "observed_at", errors)

    if result.status == "found":
        if result.current_option is None:
            errors.append("status=found 但 current_option 缺失")
        else:
            current = result.current_option
            if current.total_amount <= 0:
                errors.append("current_option.total_amount 必須 > 0")
            if current.currency.upper() != original_option.currency.upper():
                errors.append(
                    f"重新驗價幣別改變：{original_option.currency} -> {current.currency}；不可自動比較"
                )
            if _segment_identity(current) != _segment_identity(original_option):
                errors.append("重新驗價找到的航段/航班/日期與原選項不同")
            if result.match_confidence != "exact":
                errors.append("重新驗價 match_confidence 不是 exact，需人工檢查")
    elif result.current_option is not None:
        errors.append(f"status={result.status} 時 current_option 應為空")

    if result.status == "manual_required" and not result.manual_handoff_reason:
        errors.append("manual_required 缺少 manual_handoff_reason")
    return result, errors


def _validate_hotel_source(source_url: str, allowed_domains: list[str] | tuple[str, ...], errors: list[str]) -> None:
    parsed = urlparse(source_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        errors.append("hotel result source_url 必須使用 https")
    if not host:
        errors.append("hotel result source_url 缺少 host")
        return
    if not any(host_matches_domain(host, d) for d in allowed_domains):
        errors.append(f"hotel result source_url 不在核准 official domains: {host}")


def validate_hotel_search_result(
    text: str,
    expected_search: dict[str, Any],
    allowed_domains: list[str] | tuple[str, ...],
) -> tuple["HotelSearchResultV1 | None", list[str]]:
    from app.models import HotelSearchResultV1

    errors: list[str] = []
    raw = extract_first_json_object(text)
    if raw is None:
        return None, ["沒有找到可解析的 JSON object"]
    try:
        result = HotelSearchResultV1.model_validate(raw)
    except ValidationError as exc:
        return None, [f"schema validation failed: {err['loc']}: {err['msg']}" for err in exc.errors()[:16]]

    _validate_hotel_source(result.source_url, allowed_domains, errors)
    _validate_timestamp(result.observed_at, "observed_at", errors)

    expected_name = str(expected_search.get("hotel_name") or "").strip().casefold()
    if expected_name and result.hotel_name.strip().casefold() != expected_name:
        errors.append(f"hotel_name mismatch: expected {expected_search.get('hotel_name')}, got {result.hotel_name}")

    for key in ("checkin_date", "checkout_date"):
        expected = str(expected_search.get(key) or "")
        actual = str(getattr(result, key))
        if expected and expected != actual:
            errors.append(f"{key} mismatch: expected {expected}, got {actual}")
    for key in ("rooms", "adults"):
        expected = expected_search.get(key)
        if expected is not None and int(expected) != int(getattr(result, key)):
            errors.append(f"{key} mismatch: expected {expected}, got {getattr(result, key)}")
    expected_children = list(expected_search.get("children_ages") or [])
    if expected_children != result.children_ages:
        errors.append(f"children_ages mismatch: expected {expected_children}, got {result.children_ages}")

    if result.status == "ok" and not result.options:
        errors.append("status=ok 但 options 為空")
    if result.status == "manual_required" and not result.manual_handoff_reason:
        errors.append("manual_required 缺少 manual_handoff_reason")

    seen_ids: set[str] = set()
    for idx, option in enumerate(result.options):
        if option.option_id in seen_ids:
            errors.append(f"option[{idx}] option_id 重複")
        seen_ids.add(option.option_id)
        if option.total_amount <= 0:
            errors.append(f"option[{idx}] total_amount 必須 > 0")
        if result.currency and option.currency.upper() != result.currency.upper():
            errors.append(f"option[{idx}] currency 與 result currency 不一致")
        if option.base_amount is not None and option.taxes_and_fees is not None:
            known_total = option.base_amount + option.taxes_and_fees + (option.mandatory_property_fees or 0)
            # Hotel sites can round or embed fees differently; reject only material mismatch.
            tolerance = max(2.0, option.total_amount * 0.015)
            if abs(known_total - option.total_amount) > tolerance:
                errors.append(
                    f"option[{idx}] price breakdown 與 total_amount 差距過大: breakdown={known_total:g}, total={option.total_amount:g}"
                )
        if option.refundable is True and not option.cancellation_deadline_local:
            errors.append(f"option[{idx}] refundable=true 但缺少 cancellation_deadline_local")
    return result, errors


def _hotel_rate_identity(option: "HotelRoomOption") -> tuple[str, str, str]:
    return (
        option.room_name.strip().casefold(),
        option.bed_type.strip().casefold(),
        option.rate_name.strip().casefold(),
    )


def validate_hotel_revalidation_result(
    text: str,
    expected_option_id: str,
    original_option: "HotelRoomOption",
    allowed_domains: list[str] | tuple[str, ...],
) -> tuple["HotelRevalidationResultV1 | None", list[str]]:
    from app.models import HotelRevalidationResultV1

    errors: list[str] = []
    raw = extract_first_json_object(text)
    if raw is None:
        return None, ["沒有找到可解析的 JSON object"]
    try:
        result = HotelRevalidationResultV1.model_validate(raw)
    except ValidationError as exc:
        return None, [f"schema validation failed: {err['loc']}: {err['msg']}" for err in exc.errors()[:16]]

    if result.original_option_id != expected_option_id:
        errors.append("original_option_id 與要求重新驗價的 hotel option 不一致")
    _validate_hotel_source(result.source_url, allowed_domains, errors)
    _validate_timestamp(result.observed_at, "observed_at", errors)

    if result.status == "found":
        if result.current_option is None:
            errors.append("status=found 但 current_option 缺失")
        else:
            current = result.current_option
            if current.total_amount <= 0:
                errors.append("current_option.total_amount 必須 > 0")
            if current.currency.upper() != original_option.currency.upper():
                errors.append(
                    f"重新驗價幣別改變：{original_option.currency} -> {current.currency}；不可自動比較"
                )
            if _hotel_rate_identity(current) != _hotel_rate_identity(original_option):
                errors.append("重新驗價找到的房型/床型/方案與原選項不同")
            if result.match_confidence != "exact":
                errors.append("重新驗價 match_confidence 不是 exact，需人工檢查")
    elif result.current_option is not None:
        errors.append(f"status={result.status} 時 current_option 應為空")

    if result.status == "manual_required" and not result.manual_handoff_reason:
        errors.append("manual_required 缺少 manual_handoff_reason")
    return result, errors
