from __future__ import annotations

from typing import Any

from app.config import settings
from app.models import (
    BrowserTaskKind,
    FlightOption,
    FlightRevalidationResultV1,
    FlightRevalidationSummary,
    FlightSearchResultV1,
)
from app.repositories import browser_task_repo


def _original_option(parent_task_id: str, option_id: str) -> tuple[FlightSearchResultV1, FlightOption]:
    parent = browser_task_repo.get(parent_task_id)
    if not parent or parent.kind != BrowserTaskKind.FLIGHT_SEARCH or not parent.result_json:
        raise ValueError("找不到原始 flight search 結果")
    result = FlightSearchResultV1.model_validate(parent.result_json)
    for option in result.options:
        if option.option_id == option_id:
            return result, option
    raise ValueError("原始 flight option 不存在")


def _segments_key(option: FlightOption) -> list[tuple[str, str, str, str]]:
    return [
        (
            seg.flight_number.strip().upper(),
            seg.origin.strip().upper(),
            seg.destination.strip().upper(),
            (seg.departure_local or "")[:10],
        )
        for seg in option.segments
    ]


def _known(value: str | None) -> bool:
    return bool(value and value.strip() and value.strip().lower() != "unknown")


def summarize_revalidation(task_id: str) -> FlightRevalidationSummary:
    task = browser_task_repo.get(task_id)
    if not task:
        raise KeyError(task_id)
    if task.kind != BrowserTaskKind.REVALIDATE_PRICE:
        raise ValueError("task 不是 revalidate_price")
    if not task.parent_task_id or not task.parent_option_id:
        raise ValueError("revalidation task 缺少 parent reference")

    original_result, original = _original_option(task.parent_task_id, task.parent_option_id)
    base: dict[str, Any] = {
        "task_id": task.id,
        "search_task_id": task.parent_task_id,
        "option_id": task.parent_option_id,
        "airline_code": task.provider_code or original_result.airline_code,
        "source_url": task.source_url,
        "original_amount": original.total_amount,
        "currency": original.currency,
    }
    blockers: list[str] = []
    warnings: list[str] = []

    if task.review_state != "auto_validated" or not task.result_json:
        blockers.append("重新驗價尚未通過結構與官方網域驗證")
        return FlightRevalidationSummary(**base, status="needs_review", blockers=blockers, warnings=warnings)

    result = FlightRevalidationResultV1.model_validate(task.result_json)
    base.update(
        status=result.status,
        source_url=result.source_url,
        observed_at=result.observed_at,
        match_confidence=result.match_confidence,
    )
    warnings.extend(result.differences)
    warnings.extend(result.notes)

    if result.status != "found" or result.current_option is None:
        if result.status == "unavailable":
            blockers.append("原選項已找不到或已無法購買")
        elif result.status == "manual_required":
            blockers.append(result.manual_handoff_reason or "官網要求人工處理")
        else:
            blockers.append(f"重新驗價狀態：{result.status}")
        return FlightRevalidationSummary(**base, blockers=blockers, warnings=warnings)

    current = result.current_option
    delta = float(current.total_amount) - float(original.total_amount)
    delta_percent = (delta / float(original.total_amount) * 100.0) if original.total_amount else None
    fare_changed = current.fare_family.strip() != original.fare_family.strip()
    itinerary_changed = _segments_key(current) != _segments_key(original)
    rules_changed = any(
        getattr(current, field).strip() != getattr(original, field).strip()
        for field in ("checked_baggage", "carry_on", "change_rule_summary", "refund_rule_summary", "seat_selection")
    )

    requires_acceptance = False
    if current.currency.upper() != original.currency.upper():
        blockers.append("重新驗價幣別與原始選項不同")
    if result.match_confidence != "exact":
        blockers.append("重新驗價沒有 exact match")
    if itinerary_changed:
        blockers.append("航段/航班/日期與原選項不同")
    if delta != 0:
        if current.currency.upper() == "TWD":
            requires_acceptance = abs(delta) > settings.price_change_acceptance_threshold_twd
        else:
            requires_acceptance = True
        warnings.append(f"價格變動：{original.currency} {original.total_amount:g} → {current.currency} {current.total_amount:g}")
    if fare_changed:
        requires_acceptance = True
        warnings.append("票價產品名稱已變更")
    if rules_changed:
        requires_acceptance = True
        warnings.append("行李或退改/選位條件已變更")
    if not _known(current.checked_baggage):
        warnings.append("託運行李資訊仍未確認")
    if not _known(current.change_rule_summary):
        warnings.append("改票規則仍未確認")
    if not _known(current.refund_rule_summary):
        warnings.append("退票規則仍未確認")

    status = "changed" if requires_acceptance else "unchanged"
    base["status"] = status
    return FlightRevalidationSummary(
        **base,
        current_amount=current.total_amount,
        delta_amount=round(delta, 2),
        delta_percent=round(delta_percent, 3) if delta_percent is not None else None,
        fare_family_changed=fare_changed,
        itinerary_changed=itinerary_changed,
        rules_changed=rules_changed,
        requires_human_acceptance=requires_acceptance,
        blockers=blockers,
        warnings=warnings,
    )
