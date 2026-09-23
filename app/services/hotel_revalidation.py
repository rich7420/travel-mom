from __future__ import annotations

from app.config import settings
from app.models import (
    BrowserTaskKind,
    HotelRevalidationResultV1,
    HotelRevalidationSummary,
    HotelRoomOption,
    HotelSearchResultV1,
)
from app.repositories import browser_task_repo


def _original_option(parent_task_id: str, option_id: str) -> tuple[HotelSearchResultV1, HotelRoomOption]:
    parent = browser_task_repo.get(parent_task_id)
    if not parent or parent.kind != BrowserTaskKind.HOTEL_SEARCH or not parent.result_json:
        raise ValueError("找不到原始 hotel search 結果")
    result = HotelSearchResultV1.model_validate(parent.result_json)
    for option in result.options:
        if option.option_id == option_id:
            return result, option
    raise ValueError("原始 hotel option 不存在")


def _norm(value: str | None) -> str:
    return (value or "").strip().casefold()


def summarize_hotel_revalidation(task_id: str) -> HotelRevalidationSummary:
    task = browser_task_repo.get(task_id)
    if not task:
        raise KeyError(task_id)
    if task.expected_schema != "hotel-revalidation-v1" or task.kind != BrowserTaskKind.HOTEL_REVALIDATE:
        raise ValueError("task 不是 hotel revalidation")
    if not task.parent_task_id or not task.parent_option_id:
        raise ValueError("hotel revalidation 缺少 parent")

    original_result, original = _original_option(task.parent_task_id, task.parent_option_id)
    base = dict(
        task_id=task.id,
        search_task_id=task.parent_task_id,
        option_id=task.parent_option_id,
        hotel_name=original_result.hotel_name,
        source_url=task.source_url,
        original_amount=original.total_amount,
        currency=original.currency,
    )
    blockers: list[str] = []
    warnings: list[str] = []
    if task.review_state != "auto_validated" or not task.result_json:
        blockers.append("重新驗價尚未通過結構與 official-domain 驗證")
        return HotelRevalidationSummary(**base, status="needs_review", blockers=blockers)

    result = HotelRevalidationResultV1.model_validate(task.result_json)
    base.update(source_url=result.source_url, observed_at=result.observed_at, match_confidence=result.match_confidence)
    warnings.extend(result.differences)
    warnings.extend(result.notes)
    if result.status != "found" or result.current_option is None:
        if result.status == "unavailable":
            blockers.append("原房型/方案已無法購買")
        elif result.status == "manual_required":
            blockers.append(result.manual_handoff_reason or "官網要求人工處理")
        else:
            blockers.append(f"重新驗價狀態：{result.status}")
        return HotelRevalidationSummary(**base, status=result.status, blockers=blockers, warnings=warnings)

    current = result.current_option
    delta = float(current.total_amount) - float(original.total_amount)
    delta_percent = (delta / float(original.total_amount) * 100.0) if original.total_amount else None
    room_changed = (_norm(current.room_name), _norm(current.bed_type)) != (_norm(original.room_name), _norm(original.bed_type))
    rate_changed = _norm(current.rate_name) != _norm(original.rate_name)
    cancellation_changed = (
        current.refundable != original.refundable
        or _norm(current.cancellation_deadline_local) != _norm(original.cancellation_deadline_local)
    )
    meal_changed = current.breakfast_included != original.breakfast_included
    fees_changed = (
        current.taxes_and_fees != original.taxes_and_fees
        or current.mandatory_property_fees != original.mandatory_property_fees
        or current.resort_fee_included != original.resort_fee_included
    )

    requires_acceptance = False
    if current.currency.upper() != original.currency.upper():
        blockers.append("重新驗價幣別與原始選項不同")
    if result.match_confidence != "exact":
        blockers.append("重新驗價沒有 exact match")
    if room_changed:
        blockers.append("房型/床型與原選項不同")
    if delta != 0:
        requires_acceptance = True
        warnings.append(f"價格變動：{original.currency} {original.total_amount:g} → {current.currency} {current.total_amount:g}")
    if rate_changed:
        requires_acceptance = True
        warnings.append("rate plan 名稱已變更")
    if cancellation_changed:
        requires_acceptance = True
        warnings.append("取消條件已變更")
    if meal_changed:
        requires_acceptance = True
        warnings.append("早餐包含狀態已變更")
    if fees_changed:
        requires_acceptance = True
        warnings.append("稅費/mandatory fee 狀態已變更")

    return HotelRevalidationSummary(
        **base,
        status="changed" if requires_acceptance else "unchanged",
        current_amount=current.total_amount,
        delta_amount=round(delta, 2),
        delta_percent=round(delta_percent, 3) if delta_percent is not None else None,
        room_changed=room_changed,
        rate_changed=rate_changed,
        cancellation_changed=cancellation_changed,
        meal_changed=meal_changed,
        fees_changed=fees_changed,
        requires_human_acceptance=requires_acceptance,
        blockers=list(dict.fromkeys(blockers)),
        warnings=list(dict.fromkeys(warnings)),
    )
