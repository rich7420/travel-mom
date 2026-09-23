from __future__ import annotations

from datetime import datetime, timezone

from app.config import settings
from app.db import audit
from app.models import (
    BookingChecklistItem,
    BookingPreflightRequest,
    BookingPreflightResult,
    FlightRevalidationResultV1,
    now_iso,
)
from app.repositories import browser_task_repo
from app.services.flight_revalidation import summarize_revalidation


def _minutes_old(value: str) -> float:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must contain timezone")
    return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 60.0)


def _item(key: str, label: str, status: str, detail: str) -> BookingChecklistItem:
    return BookingChecklistItem(key=key, label=label, status=status, detail=detail)


def build_booking_preflight(req: BookingPreflightRequest) -> BookingPreflightResult:
    task = browser_task_repo.get(req.revalidation_task_id)
    if not task:
        raise KeyError(req.revalidation_task_id)

    summary = summarize_revalidation(task.id)
    checklist: list[BookingChecklistItem] = []
    blockers = list(summary.blockers)
    warnings = list(summary.warnings)
    age_minutes: float | None = None

    if task.review_state == "auto_validated":
        checklist.append(_item("structured_validation", "重新驗價資料驗證", "ok", "Schema、航空公司與官方網域已驗證"))
    else:
        checklist.append(_item("structured_validation", "重新驗價資料驗證", "blocked", "結果尚未通過自動驗證"))
        blockers.append("重新驗價結果需要人工 review")

    result: FlightRevalidationResultV1 | None = None
    if task.result_json:
        result = FlightRevalidationResultV1.model_validate(task.result_json)

    if result and result.observed_at:
        try:
            age_minutes = _minutes_old(result.observed_at)
            if age_minutes <= settings.price_revalidation_max_age_minutes:
                checklist.append(
                    _item(
                        "freshness",
                        "價格新鮮度",
                        "ok",
                        f"{age_minutes:.1f} 分鐘前重新確認，門檻 {settings.price_revalidation_max_age_minutes} 分鐘",
                    )
                )
            else:
                checklist.append(
                    _item(
                        "freshness",
                        "價格新鮮度",
                        "blocked",
                        f"已過 {age_minutes:.1f} 分鐘，需再次重新驗價",
                    )
                )
                blockers.append("重新驗價結果已過期")
        except ValueError:
            checklist.append(_item("freshness", "價格新鮮度", "blocked", "observed_at 無法解析"))
            blockers.append("重新驗價時間無法驗證")
    else:
        checklist.append(_item("freshness", "價格新鮮度", "blocked", "缺少重新驗價時間"))
        blockers.append("缺少重新驗價時間")

    if summary.match_confidence == "exact" and not summary.itinerary_changed:
        checklist.append(_item("itinerary", "航班與日期", "ok", "與原選項完全相符"))
    else:
        checklist.append(_item("itinerary", "航班與日期", "blocked", "無法證明與原選項完全相同"))
        blockers.append("航班與日期未取得 exact match")

    if summary.current_amount is not None and summary.currency:
        detail = f"{summary.currency} {summary.current_amount:g}"
        if summary.delta_amount:
            detail += f"（變動 {summary.delta_amount:+g}）"
        checklist.append(_item("price", "最新總價與幣別", "ok", detail))
    else:
        checklist.append(_item("price", "最新總價與幣別", "blocked", "缺少可驗證總價"))
        blockers.append("缺少最新總價或幣別")

    if summary.requires_human_acceptance:
        if req.accept_price_change:
            checklist.append(_item("price_acceptance", "價格/條件變動確認", "ok", "使用者已明確接受目前差異"))
            audit(
                task.case_id,
                "human",
                "flight_price_change.accepted",
                {
                    "revalidation_task_id": task.id,
                    "search_task_id": task.parent_task_id,
                    "option_id": task.parent_option_id,
                    "original_amount": summary.original_amount,
                    "current_amount": summary.current_amount,
                    "currency": summary.currency,
                },
                now_iso(),
            )
        else:
            checklist.append(_item("price_acceptance", "價格/條件變動確認", "blocked", "需要人工勾選接受新價格/條件"))
            blockers.append("價格或條件有變動，尚未明確接受")
    else:
        checklist.append(_item("price_acceptance", "價格/條件變動確認", "ok", "沒有需要另外接受的變動"))

    if result and result.current_option:
        option = result.current_option
        baggage_ok = option.checked_baggage.strip().lower() != "unknown"
        checklist.append(
            _item(
                "baggage",
                "託運行李",
                "ok" if baggage_ok else "warning",
                option.checked_baggage if baggage_ok else "尚未確認，付款前由人類在官網再次查看",
            )
        )
        rules_known = all(
            value.strip().lower() != "unknown"
            for value in (option.change_rule_summary, option.refund_rule_summary)
        )
        checklist.append(
            _item(
                "fare_rules",
                "退改規則",
                "ok" if rules_known else "warning",
                f"改票：{option.change_rule_summary}；退票：{option.refund_rule_summary}",
            )
        )
        if not baggage_ok:
            warnings.append("付款前必須由人類確認託運行李")
        if not rules_known:
            warnings.append("付款前必須由人類閱讀完整退改規則")
    else:
        checklist.append(_item("baggage", "託運行李", "blocked", "沒有 current_option"))
        checklist.append(_item("fare_rules", "退改規則", "blocked", "沒有 current_option"))
        blockers.append("沒有可進入 checkout 的目前選項")

    checklist.append(
        _item(
            "human_checkout",
            "付款與開票",
            "warning",
            "Travel Desk 只打開/預填至付款前；信用卡、OTP、3DS 與最終送出由媽媽本人完成",
        )
    )

    # Stable de-duplication keeps the UI concise.
    blockers = list(dict.fromkeys(blockers))
    warnings = list(dict.fromkeys(warnings))
    ready = not blockers
    status = "ready_for_human_checkout" if ready else (
        "needs_review" if task.review_state != "auto_validated" else "blocked"
    )
    next_action = (
        "由人類打開官方網站付款頁，逐項核對旅客姓名、航班、行李、退改規則與總額後自行完成付款。"
        if ready
        else "先處理阻擋項目，再建立新的 booking preflight；系統不會自行付款或開票。"
    )
    return BookingPreflightResult(
        ready=ready,
        status=status,
        case_id=task.case_id,
        airline_code=task.provider_code,
        search_task_id=task.parent_task_id,
        revalidation_task_id=task.id,
        option_id=task.parent_option_id,
        revalidation_age_minutes=round(age_minutes, 2) if age_minutes is not None else None,
        checklist=checklist,
        blockers=blockers,
        warnings=warnings,
        next_action=next_action,
    )
