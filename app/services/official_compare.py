from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from app.models import FlightOption, FlightSearchResultV1
from app.repositories import browser_task_repo


def _task_search_context(instructions: str) -> dict[str, Any]:
    try:
        payload = json.loads(instructions)
    except (TypeError, json.JSONDecodeError):
        return {}
    search = payload.get("search")
    return search if isinstance(search, dict) else {}


def _option_score(
    option: FlightOption,
    cheapest: float,
    fastest: int | None,
    nonstop_preferred: bool,
    max_total_twd: int | None = None,
) -> tuple[float, list[str]]:
    score = 100.0
    reasons: list[str] = []

    if cheapest > 0:
        price_delta_ratio = max(0.0, (option.total_amount - cheapest) / cheapest)
        score -= min(30.0, price_delta_ratio * 45.0)
        if option.total_amount <= cheapest * 1.03:
            reasons.append("價格接近此幣別最低")

    score -= option.stops * (16.0 if nonstop_preferred else 10.0)
    if option.stops == 0:
        reasons.append("直飛")
        score += 4.0

    if fastest and option.total_duration_minutes:
        extra_minutes = max(0, option.total_duration_minutes - fastest)
        score -= min(15.0, extra_minutes / 30.0 * 1.5)
        if extra_minutes <= 30:
            reasons.append("總旅行時間短")

    baggage = (option.checked_baggage or "unknown").lower()
    if baggage != "unknown" and baggage.strip():
        reasons.append("已取得託運行李資訊")
        score += 2.0
    else:
        score -= 2.0

    change = (option.change_rule_summary or "unknown").lower()
    refund = (option.refund_rule_summary or "unknown").lower()
    if change == "unknown":
        score -= 1.0
    if refund == "unknown":
        score -= 1.0
    if any(x in refund for x in ("non-refundable", "不可退", "no refund")):
        score -= 4.0
    if any(x in change for x in ("not allowed", "不可改", "no change")):
        score -= 3.0

    if max_total_twd is not None and option.currency.upper() == "TWD":
        if option.total_amount <= max_total_twd:
            reasons.append("在設定總預算內")
            score += 2.0
        else:
            over_ratio = (option.total_amount - max_total_twd) / max(1, max_total_twd)
            score -= min(22.0, 8.0 + over_ratio * 35.0)
            reasons.append(f"超過設定總預算 TWD {max_total_twd:,}")

    score -= min(8.0, len(option.warnings) * 2.0)
    return round(score, 2), reasons


def compare_official_flight_tasks(task_ids: list[str]) -> dict[str, Any]:
    if not task_ids:
        raise ValueError("task_ids 不可為空")
    if len(task_ids) > 12:
        raise ValueError("一次最多比較 12 個 Browser tasks")

    task_rows = []
    ready_results: list[tuple[Any, FlightSearchResultV1]] = []
    search_context: dict[str, Any] = {}

    for task_id in task_ids:
        task = browser_task_repo.get(task_id)
        if not task:
            task_rows.append({"task_id": task_id, "state": "missing"})
            continue
        if not search_context:
            search_context = _task_search_context(task.instructions)
        if task.review_state != "auto_validated" or not task.result_json:
            task_rows.append({
                "task_id": task.id,
                "airline_code": task.provider_code,
                "state": "needs_result" if task.status in {"queued", "running"} else "needs_review",
                "status": task.status,
                "review_state": task.review_state,
            })
            continue
        try:
            result = FlightSearchResultV1.model_validate(task.result_json)
        except Exception as exc:  # defensive: persisted JSON may predate schema
            task_rows.append({"task_id": task.id, "airline_code": task.provider_code, "state": "invalid", "error": str(exc)})
            continue
        if result.status != "ok" or not result.options:
            task_rows.append({
                "task_id": task.id,
                "airline_code": task.provider_code,
                "state": result.status,
                "manual_handoff_reason": result.manual_handoff_reason,
                "notes": result.notes,
            })
            continue
        ready_results.append((task, result))
        task_rows.append({"task_id": task.id, "airline_code": task.provider_code, "state": "ready", "option_count": len(result.options)})

    by_currency: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task, result in ready_results:
        for option in result.options:
            currency = (option.currency or result.currency or "UNKNOWN").upper()
            by_currency[currency].append({
                "task_id": task.id,
                "airline_code": result.airline_code,
                "airline_name": result.airline_name,
                "source_url": result.source_url,
                "observed_at": result.observed_at,
                "option": option,
            })

    groups = []
    nonstop_preferred = bool(search_context.get("nonstop_preferred", False))
    raw_budget = search_context.get("max_total_twd")
    max_total_twd = int(raw_budget) if isinstance(raw_budget, (int, float)) and raw_budget >= 0 else None
    for currency, rows in sorted(by_currency.items()):
        cheapest = min(float(r["option"].total_amount) for r in rows)
        durations = [r["option"].total_duration_minutes for r in rows if r["option"].total_duration_minutes]
        fastest = min(durations) if durations else None
        ranked = []
        for row in rows:
            score, reasons = _option_score(
                row["option"],
                cheapest,
                fastest,
                nonstop_preferred,
                max_total_twd=max_total_twd,
            )
            ranked.append({
                "task_id": row["task_id"],
                "airline_code": row["airline_code"],
                "airline_name": row["airline_name"],
                "source_url": row["source_url"],
                "observed_at": row["observed_at"],
                "score": score,
                "reasons": reasons,
                "option": row["option"].model_dump(mode="json"),
            })
        ranked.sort(key=lambda x: (-x["score"], x["option"]["total_amount"]))
        groups.append({
            "currency": currency,
            "ranked": ranked,
            "cheapest_amount": cheapest,
            "fastest_duration_minutes": fastest,
        })

    return {
        "schema_version": "flight-comparison-v1",
        "search": search_context,
        "task_states": task_rows,
        "currency_groups": groups,
        "mixed_currency": len(groups) > 1,
        "customer_safe": False,
        "warning": "僅比較已通過結構驗證的官網搜尋結果；成交/付款前仍必須回官方網站重新驗價與條件。",
    }
