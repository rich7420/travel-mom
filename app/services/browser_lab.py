from __future__ import annotations

from collections import defaultdict
import json
from statistics import median
from typing import Any
from urllib.parse import urlparse

from app.models import BrowserTaskKind
from app.repositories import browser_attempt_repo, browser_task_repo


def _task_result_status(task) -> str | None:
    result = task.result_json or {}
    value = result.get("status") if isinstance(result, dict) else None
    return str(value) if value is not None else None


def _task_recipe_metadata(task) -> tuple[str | None, str | None]:
    try:
        payload = json.loads(task.instructions)
    except (TypeError, json.JSONDecodeError):
        return None, None
    recipe = payload.get("semantic_recipe") if isinstance(payload, dict) else None
    if not isinstance(recipe, dict):
        return None, None
    version = recipe.get("recipe_version")
    reviewed = recipe.get("last_reviewed")
    return (str(version) if version else None, str(reviewed) if reviewed else None)




def _supplier_identity(task) -> tuple[str, str, str]:
    if task.provider_code:
        code = str(task.provider_code).upper()
        return ("airline", code, code)
    if str(task.expected_schema or "").startswith("hotel-"):
        host = (urlparse(task.source_url).hostname or "hotel").lower().removeprefix("www.")
        return ("hotel", host, host)
    return ("generic", "GENERIC", "GENERIC")

def build_browser_lab_summary(limit: int = 1000, task_ids: set[str] | None = None) -> dict[str, Any]:
    """Aggregate Browser Lab telemetry without overstating business readiness.

    Three different notions are intentionally separated:
    - contract validation: output matched the typed schema/domain/route/date checks;
    - usable success: a validated option was actually returned (`ok`/`found`);
    - manual terminal: the browser correctly stopped and handed work to a human.

    A manual handoff is safe behavior, but it is not counted as an automated success.
    """

    tasks = browser_task_repo.list(limit=limit)
    if task_ids is not None:
        tasks = [task for task in tasks if task.id in task_ids]
    attempts = browser_attempt_repo.list(limit=limit * 5)
    if task_ids is not None:
        attempts = [attempt for attempt in attempts if attempt.task_id in task_ids]
    task_by_id = {task.id: task for task in tasks}

    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "tasks_total": 0,
            "search_tasks": 0,
            "revalidation_tasks": 0,
            "hotel_search_tasks": 0,
            "hotel_revalidation_tasks": 0,
            "attempts_total": 0,
            "openclaw_attempts": 0,
            "lab_ingest_attempts": 0,
            "auto_validated_tasks": 0,
            "usable_result_tasks": 0,
            "manual_terminal_tasks": 0,
            "no_result_tasks": 0,
            "needs_review_tasks": 0,
            "manual_or_blocked_attempts": 0,
            "validation_error_attempts": 0,
            "usable_success_attempts": 0,
            "contract_valid_attempts": 0,
            "durations_ms": [],
            "recipe_versions": set(),
            "recipe_reviewed_dates": set(),
            "outcomes": defaultdict(int),
            "result_statuses": defaultdict(int),
        }
    )

    supplier_meta: dict[str, tuple[str, str]] = {}
    for task in tasks:
        supplier_type, code, label = _supplier_identity(task)
        group_key = f"{supplier_type}:{code}"
        supplier_meta[group_key] = (supplier_type, label)
        row = grouped[group_key]
        row["tasks_total"] += 1
        if task.kind == BrowserTaskKind.FLIGHT_SEARCH:
            row["search_tasks"] += 1
        if task.kind == BrowserTaskKind.REVALIDATE_PRICE:
            row["revalidation_tasks"] += 1
        if task.kind == BrowserTaskKind.HOTEL_SEARCH:
            row["hotel_search_tasks"] += 1
        if task.kind == BrowserTaskKind.HOTEL_REVALIDATE:
            row["hotel_revalidation_tasks"] += 1
        if task.review_state == "auto_validated":
            row["auto_validated_tasks"] += 1
        if task.review_state == "needs_review":
            row["needs_review_tasks"] += 1

        recipe_version, recipe_reviewed = _task_recipe_metadata(task)
        if recipe_version:
            row["recipe_versions"].add(recipe_version)
        if recipe_reviewed:
            row["recipe_reviewed_dates"].add(recipe_reviewed)

        result_status = _task_result_status(task)
        if result_status in {"ok", "found"}:
            row["usable_result_tasks"] += 1
        elif result_status == "manual_required":
            row["manual_terminal_tasks"] += 1
        elif result_status in {"no_results", "unavailable"}:
            row["no_result_tasks"] += 1

    for attempt in attempts:
        task = task_by_id.get(attempt.task_id)
        if task:
            supplier_type, code, label = _supplier_identity(task)
            group_key = f"{supplier_type}:{code}"
            supplier_meta[group_key] = (supplier_type, label)
        else:
            group_key = "generic:GENERIC"
            supplier_meta[group_key] = ("generic", "GENERIC")
        row = grouped[group_key]
        row["attempts_total"] += 1
        row[f"{attempt.source}_attempts"] += 1
        row["outcomes"][attempt.outcome] += 1
        result_status = attempt.result_status or (_task_result_status(task) if task else None)
        if result_status:
            row["result_statuses"][result_status] += 1
        if attempt.validation_errors:
            row["validation_error_attempts"] += 1
        if (
            attempt.blocker
            or attempt.outcome in {"needs_review", "degraded", "error"}
            or result_status in {"manual_required", "blocked", "error"}
        ):
            row["manual_or_blocked_attempts"] += 1
        if attempt.duration_ms is not None:
            row["durations_ms"].append(attempt.duration_ms)

        contract_valid_statuses = {"ok", "found", "no_results", "unavailable", "manual_required"}
        if result_status in contract_valid_statuses and not attempt.validation_errors:
            row["contract_valid_attempts"] += 1
            if result_status in {"ok", "found"} and not attempt.blocker:
                row["usable_success_attempts"] += 1

    providers = []
    for group_key in sorted(grouped):
        row = grouped[group_key]
        supplier_type, label = supplier_meta.get(group_key, ("generic", "GENERIC"))
        provider_key = group_key.split(":", 1)[1]
        attempts_total = row["attempts_total"]
        providers.append(
            {
                "provider_type": supplier_type,
                "provider_key": provider_key,
                "provider_label": label,
                # Backward-compatible field retained for v0.6 airline UI/tests.
                "airline_code": provider_key,
                "tasks_total": row["tasks_total"],
                "search_tasks": row["search_tasks"],
                "revalidation_tasks": row["revalidation_tasks"],
                "hotel_search_tasks": row["hotel_search_tasks"],
                "hotel_revalidation_tasks": row["hotel_revalidation_tasks"],
                "attempts_total": attempts_total,
                "recipe_versions": sorted(row["recipe_versions"]),
                "recipe_reviewed_dates": sorted(row["recipe_reviewed_dates"]),
                "openclaw_attempts": row["openclaw_attempts"],
                "lab_ingest_attempts": row["lab_ingest_attempts"],
                "auto_validated_tasks": row["auto_validated_tasks"],
                "usable_result_tasks": row["usable_result_tasks"],
                "manual_terminal_tasks": row["manual_terminal_tasks"],
                "no_result_tasks": row["no_result_tasks"],
                "needs_review_tasks": row["needs_review_tasks"],
                "validation_error_attempts": row["validation_error_attempts"],
                "manual_or_blocked_attempts": row["manual_or_blocked_attempts"],
                "contract_validation_rate": (
                    round(row["contract_valid_attempts"] / attempts_total, 4) if attempts_total else None
                ),
                "usable_success_rate": (
                    round(row["usable_success_attempts"] / attempts_total, 4) if attempts_total else None
                ),
                # Backward-compatible alias used by the current UI.
                "success_rate": (
                    round(row["usable_success_attempts"] / attempts_total, 4) if attempts_total else None
                ),
                "median_duration_ms": int(median(row["durations_ms"])) if row["durations_ms"] else None,
                "outcomes": dict(row["outcomes"]),
                "result_statuses": dict(row["result_statuses"]),
            }
        )

    total_attempts = len(attempts)
    total_contract_valid = 0
    total_usable = 0
    for attempt in attempts:
        task = task_by_id.get(attempt.task_id)
        result_status = attempt.result_status or (_task_result_status(task) if task else None)
        if result_status in {"ok", "found", "no_results", "unavailable", "manual_required"} and not attempt.validation_errors:
            total_contract_valid += 1
            if result_status in {"ok", "found"} and not attempt.blocker:
                total_usable += 1

    return {
        "schema_version": "browser-lab-summary-v2",
        "tasks_total": len(tasks),
        "attempts_total": total_attempts,
        "overall_contract_validation_rate": (
            round(total_contract_valid / total_attempts, 4) if total_attempts else None
        ),
        "overall_usable_success_rate": round(total_usable / total_attempts, 4) if total_attempts else None,
        # Backward-compatible alias.
        "overall_success_rate": round(total_usable / total_attempts, 4) if total_attempts else None,
        "providers": providers,
        "notes": [
            "contract_validation_rate 表示輸出通過 typed schema、指定供應商 official domain 與行程/住宿條件驗證。",
            "usable_success_rate 只計算真的取得可比較 option 的 ok/found；安全的 manual handoff 不算自動成功。",
            "lab_ingest 只驗證離線資料；正式 POC 判斷應優先看 openclaw_attempts。",
        ],
    }
