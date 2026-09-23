from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from app.models import HotelRoomOption, HotelSearchResultV1
from app.repositories import browser_task_repo


def _search_context(instructions: str) -> dict[str, Any]:
    try:
        payload = json.loads(instructions)
    except (TypeError, json.JSONDecodeError):
        return {}
    search = payload.get("search")
    return search if isinstance(search, dict) else {}


def _score(option: HotelRoomOption, cheapest: float, search: dict[str, Any]) -> tuple[float, list[str]]:
    score = 100.0
    reasons: list[str] = []
    if cheapest > 0:
        ratio = max(0.0, (option.total_amount - cheapest) / cheapest)
        score -= min(28.0, ratio * 45.0)
        if option.total_amount <= cheapest * 1.03:
            reasons.append("總住宿價格接近最低")

    if option.refundable is True:
        score += 6.0
        reasons.append("可取消")
    elif option.refundable is False:
        score -= 8.0

    if option.breakfast_included is True:
        score += 4.0
        reasons.append("含早餐")
    elif search.get("breakfast_required"):
        score -= 12.0

    if search.get("free_cancellation_preferred") and option.refundable is not True:
        score -= 8.0

    if option.base_amount is None or option.taxes_and_fees is None:
        score -= 5.0
    else:
        reasons.append("已取得稅費拆分")
    if option.mandatory_property_fees is None:
        score -= 2.0
    if option.payment_timing in {"pay_later", "pay_at_property"}:
        score += 2.0
        reasons.append("可延後付款")
    if option.loyalty_required:
        score -= 1.0
        reasons.append("需會員資格")

    max_total = search.get("max_total_twd")
    if isinstance(max_total, (int, float)) and option.currency.upper() == "TWD":
        if option.total_amount <= max_total:
            score += 2.0
            reasons.append("在設定住宿預算內")
        else:
            score -= min(20.0, 8.0 + (option.total_amount - max_total) / max(1, max_total) * 30.0)
            reasons.append("超過設定住宿預算")

    score -= min(8.0, len(option.warnings) * 2.0)
    return round(score, 2), reasons


def compare_official_hotel_tasks(task_ids: list[str]) -> dict[str, Any]:
    if not task_ids:
        raise ValueError("task_ids 不可為空")
    if len(task_ids) > 12:
        raise ValueError("一次最多比較 12 個 hotel Browser tasks")

    states: list[dict[str, Any]] = []
    ready: list[tuple[Any, HotelSearchResultV1]] = []
    search: dict[str, Any] = {}
    for task_id in task_ids:
        task = browser_task_repo.get(task_id)
        if not task:
            states.append({"task_id": task_id, "state": "missing"})
            continue
        if not search:
            search = _search_context(task.instructions)
        if task.expected_schema != "hotel-search-v1":
            states.append({"task_id": task.id, "state": "wrong_schema"})
            continue
        if task.review_state != "auto_validated" or not task.result_json:
            states.append({"task_id": task.id, "state": "needs_result" if task.status in {"queued", "running"} else "needs_review"})
            continue
        try:
            result = HotelSearchResultV1.model_validate(task.result_json)
        except Exception as exc:
            states.append({"task_id": task.id, "state": "invalid", "error": str(exc)})
            continue
        if result.status != "ok" or not result.options:
            states.append({"task_id": task.id, "state": result.status, "manual_handoff_reason": result.manual_handoff_reason})
            continue
        ready.append((task, result))
        states.append({"task_id": task.id, "state": "ready", "hotel_name": result.hotel_name, "option_count": len(result.options)})

    by_currency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task, result in ready:
        for option in result.options:
            currency = option.currency.upper()
            by_currency[currency].append({"task": task, "result": result, "option": option})

    groups: list[dict[str, Any]] = []
    for currency, rows in sorted(by_currency.items()):
        cheapest = min(float(row["option"].total_amount) for row in rows)
        ranked = []
        for row in rows:
            score, reasons = _score(row["option"], cheapest, search)
            ranked.append({
                "task_id": row["task"].id,
                "hotel_name": row["result"].hotel_name,
                "source_url": row["result"].source_url,
                "observed_at": row["result"].observed_at,
                "score": score,
                "reasons": reasons,
                "option": row["option"].model_dump(mode="json"),
            })
        ranked.sort(key=lambda x: (-x["score"], x["option"]["total_amount"]))
        groups.append({"currency": currency, "cheapest_amount": cheapest, "ranked": ranked})

    return {
        "schema_version": "hotel-comparison-v1",
        "search": search,
        "task_states": states,
        "currency_groups": groups,
        "mixed_currency": len(groups) > 1,
        "customer_safe": False,
        "warning": "只比較已通過 official-domain 與 typed-schema 驗證的結果；訂房前仍需重新驗價與由人類完成付款。",
    }
