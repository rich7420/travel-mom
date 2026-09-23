from __future__ import annotations

from datetime import datetime, timezone

from app.config import settings
from app.db import audit
from app.models import (
    BookingChecklistItem,
    HotelBookingPreflightRequest,
    HotelBookingPreflightResult,
    HotelRevalidationResultV1,
    now_iso,
)
from app.repositories import browser_task_repo
from app.services.hotel_revalidation import summarize_hotel_revalidation


def _minutes_old(value: str) -> float:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must contain timezone")
    return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 60.0)


def _item(key: str, label: str, status: str, detail: str) -> BookingChecklistItem:
    return BookingChecklistItem(key=key, label=label, status=status, detail=detail)


def build_hotel_booking_preflight(req: HotelBookingPreflightRequest) -> HotelBookingPreflightResult:
    task = browser_task_repo.get(req.revalidation_task_id)
    if not task:
        raise KeyError(req.revalidation_task_id)
    summary = summarize_hotel_revalidation(task.id)
    checklist: list[BookingChecklistItem] = []
    blockers = list(summary.blockers)
    warnings = list(summary.warnings)
    age_minutes: float | None = None

    if task.review_state == "auto_validated":
        checklist.append(_item("structured_validation", "重新驗價資料驗證", "ok", "Schema 與 official domain 已驗證"))
    else:
        checklist.append(_item("structured_validation", "重新驗價資料驗證", "blocked", "結果尚未通過自動驗證"))
        blockers.append("hotel revalidation 需要人工 review")

    result: HotelRevalidationResultV1 | None = None
    if task.result_json:
        result = HotelRevalidationResultV1.model_validate(task.result_json)

    if result and result.observed_at:
        try:
            age_minutes = _minutes_old(result.observed_at)
            if age_minutes <= settings.price_revalidation_max_age_minutes:
                checklist.append(_item("freshness", "價格新鮮度", "ok", f"{age_minutes:.1f} 分鐘前確認"))
            else:
                checklist.append(_item("freshness", "價格新鮮度", "blocked", "重新驗價已過期"))
                blockers.append("重新驗價結果已過期")
        except ValueError:
            checklist.append(_item("freshness", "價格新鮮度", "blocked", "observed_at 無法解析"))
            blockers.append("重新驗價時間無法驗證")
    else:
        blockers.append("缺少重新驗價時間")
        checklist.append(_item("freshness", "價格新鮮度", "blocked", "缺少重新驗價時間"))

    if summary.match_confidence == "exact" and not summary.room_changed:
        checklist.append(_item("room_rate", "房型/床型", "ok", "與原選項相同"))
    else:
        checklist.append(_item("room_rate", "房型/床型", "blocked", "無法證明 exact match"))
        blockers.append("房型/床型未取得 exact match")

    if summary.current_amount is not None and summary.currency:
        detail = f"{summary.currency} {summary.current_amount:g}"
        if summary.delta_amount:
            detail += f"（變動 {summary.delta_amount:+g}）"
        checklist.append(_item("price", "最新住宿總價", "ok", detail))
    else:
        checklist.append(_item("price", "最新住宿總價", "blocked", "缺少可驗證總價"))
        blockers.append("缺少最新住宿總價")

    if summary.requires_human_acceptance:
        if req.accept_price_or_terms_change:
            checklist.append(_item("change_acceptance", "價格/條件變動確認", "ok", "使用者已明確接受"))
            audit(task.case_id, "human", "hotel_price_terms_change.accepted", {
                "revalidation_task_id": task.id,
                "search_task_id": task.parent_task_id,
                "option_id": task.parent_option_id,
                "current_amount": summary.current_amount,
                "currency": summary.currency,
            }, now_iso())
        else:
            checklist.append(_item("change_acceptance", "價格/條件變動確認", "blocked", "需要人工接受最新條件"))
            blockers.append("價格或住宿條件有變動，尚未明確接受")
    else:
        checklist.append(_item("change_acceptance", "價格/條件變動確認", "ok", "沒有需要另外接受的變動"))

    if result and result.current_option:
        option = result.current_option
        fees_known = option.taxes_and_fees is not None and option.mandatory_property_fees is not None
        checklist.append(_item(
            "fees",
            "稅費與 mandatory fee",
            "ok" if fees_known else "warning",
            f"taxes/fees={option.taxes_and_fees}; property_fees={option.mandatory_property_fees}",
        ))
        if not fees_known:
            warnings.append("付款前需人工確認所有稅費與 mandatory property fee")
        cancellation_known = option.refundable is not None and (option.refundable is False or bool(option.cancellation_deadline_local))
        checklist.append(_item(
            "cancellation",
            "取消規則",
            "ok" if cancellation_known else "warning",
            f"refundable={option.refundable}; deadline={option.cancellation_deadline_local or 'unknown'}",
        ))
        if not cancellation_known:
            warnings.append("付款前需人工閱讀完整取消規則")
        checklist.append(_item(
            "meal_payment",
            "早餐與付款時點",
            "warning" if option.breakfast_included is None or option.payment_timing == "unknown" else "ok",
            f"breakfast={option.breakfast_included}; payment={option.payment_timing}",
        ))
    else:
        blockers.append("沒有可進入 checkout 的目前房型")

    checklist.append(_item(
        "human_checkout",
        "訂房付款",
        "warning",
        "Travel Desk 僅預填到付款前；信用卡、OTP、3DS、最終提交由媽媽本人完成。",
    ))
    blockers = list(dict.fromkeys(blockers))
    warnings = list(dict.fromkeys(warnings))
    ready = not blockers
    status = "ready_for_human_checkout" if ready else ("needs_review" if task.review_state != "auto_validated" else "blocked")
    return HotelBookingPreflightResult(
        ready=ready,
        status=status,
        case_id=task.case_id,
        hotel_name=summary.hotel_name,
        search_task_id=task.parent_task_id,
        revalidation_task_id=task.id,
        option_id=task.parent_option_id,
        revalidation_age_minutes=round(age_minutes, 2) if age_minutes is not None else None,
        checklist=checklist,
        blockers=blockers,
        warnings=warnings,
        next_action=(
            "由人類在官方飯店網站核對入住人姓名、房型、總價、取消規則與付款條件後自行提交。"
            if ready else "先處理阻擋項目，再重新建立 hotel booking preflight。"
        ),
    )
