from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.config import settings
from app.db import audit
from app.models import TripCase, now_iso
from app.repositories import browser_attempt_repo, browser_task_repo, case_repo, flight_search_run_repo, hotel_search_run_repo
from app.services.hotel_compare import compare_official_hotel_tasks
from app.services.official_compare import compare_official_flight_tasks
from app.workflow_models import ManualOptionCreate
from app.workflow_repository import case_workflow_repo

# Recognized city airports constrain bound searches; the operator chooses among multiple airports.
AIRPORT_CHOICES = {
    "東京": ["NRT", "HND"], "tokyo": ["NRT", "HND"], "大阪": ["KIX", "ITM"], "osaka": ["KIX", "ITM"],
    "北海道": ["CTS"], "札幌": ["CTS"], "sapporo": ["CTS"], "沖繩": ["OKA"], "首爾": ["ICN", "GMP"],
    "香港": ["HKG"], "hong kong": ["HKG"], "曼谷": ["BKK", "DMK"], "新加坡": ["SIN"],
    "台北": ["TPE", "TSA"], "高雄": ["KHH"], "台中": ["RMQ"],
}


def trip_snapshot(case: TripCase) -> dict:
    data = case.model_dump(mode="json")
    return {key: data[key] for key in (
        "origin", "destination", "depart_date", "return_date", "adults", "children", "infants", "children_ages",
    )}


def require_case(case_id: str) -> TripCase:
    case = case_repo.get(case_id)
    if case is None:
        raise KeyError(case_id)
    return case


def airport_choices(destination: str | None) -> list[str]:
    value = (destination or "").strip()
    if len(value) == 3 and value.isascii() and value.isalpha():
        return [value.upper()]
    return AIRPORT_CHOICES.get(value.lower(), [])


def validate_search_case(case: TripCase, req, kind: str) -> None:
    if kind == "flight":
        if (req.adults, req.children, req.infants) != (case.adults, case.children, case.infants):
            raise ValueError("查價人數與案件不同，請先更新案件需求")
        if case.children_ages is not None and req.children_ages != case.children_ages:
            raise ValueError("小孩年齡與案件不同，請先更新案件需求")
        if req.depart_date != case.depart_date or req.return_date != case.return_date:
            raise ValueError("查價日期與案件不同，請先更新案件需求")
        if req.origin != case.origin:
            raise ValueError("出發機場與案件不同，請先更新案件需求")
        choices = airport_choices(case.destination)
        if choices and req.destination not in choices:
            raise ValueError("目的地機場與案件不同，請先更新案件需求")
    else:
        if req.adults != case.adults or len(req.children_ages) != case.children + case.infants:
            raise ValueError("請填入案件中每位小孩與嬰兒的年齡，不可遺漏旅客")
        if case.children_ages is not None and req.children_ages[:case.children] != case.children_ages:
            raise ValueError("小孩年齡與案件不同，請先更新案件需求")
        if any(age > 1 for age in req.children_ages[case.children:]):
            raise ValueError("嬰兒年齡應為 0 或 1 歲，其他旅客請更新為小孩")
        if req.checkin_date != case.depart_date or req.checkout_date != case.return_date:
            raise ValueError("住宿日期與案件不同，請先更新案件需求")


def option_state(option: dict, case: TripCase) -> dict:
    reasons = []
    if option.get("case_snapshot") != trip_snapshot(case):
        reasons.append("案件需求已變更，請重新查價並錄入方案")
    if option.get("is_demo"):
        reasons.append("示範資料不能當成客人報價")
    now = datetime.now(timezone.utc)
    valid_until = option.get("valid_until")
    if valid_until and datetime.fromisoformat(valid_until) <= now:
        reasons.append("供應商報價已超過有效期限")
    if not valid_until:
        try:
            observed = datetime.fromisoformat(option["observed_at"])
            age = (now - observed).total_seconds()
        except (KeyError, ValueError, TypeError):
            age = float("inf")
        if age > settings.quote_max_age_hours * 3600 or age < -300:
            reasons.append(f"報價需要重新查詢確認（未指定期限時有效 {settings.quote_max_age_hours} 小時）")
    if option.get("result_unavailable"):
        reasons.append("查價尚未完成或結果需要人工檢查")
    return {**option, "usable": not reasons, "blockers": reasons}


def add_manual_option(case_id: str, data: ManualOptionCreate) -> dict:
    case = require_case(case_id)
    if not case.destination or not case.depart_date:
        raise ValueError("請先補上案件目的地與出發日期")
    if data.kind == "hotel" and not case.return_date:
        raise ValueError("飯店方案需要完整入住與退房日期")
    if case.children and case.children_ages is None:
        raise ValueError("請先在案件補上每位小孩的年齡，再確認方案總價")
    payload = {**data.model_dump(mode="json"), "source_type": "manual", "is_demo": False, "case_snapshot": trip_snapshot(case)}
    payload.pop("confirmed_for_case")
    option = case_workflow_repo.add_option(case_id, payload)
    audit(case_id, "operator", "case.option_recorded", {"option_id": option["id"], "kind": data.kind}, now_iso())
    return option_state(option, case)


def _official_options(case: TripCase, kind: str) -> list[dict]:
    repo = flight_search_run_repo if kind == "flight" else hotel_search_run_repo
    compare = compare_official_flight_tasks if kind == "flight" else compare_official_hotel_tasks
    options = []
    for run in repo.list(case_id=case.id, limit=100):
        if not run.task_ids:
            continue
        comparison = compare(run.task_ids)
        context_matches = run.request.case_context == trip_snapshot(case)
        try:
            validate_search_case(case, run.request, kind)
        except ValueError:
            context_matches = False
        for group in comparison["currency_groups"]:
            for row in group["ranked"]:
                item = row["option"]
                task = browser_task_repo.get(row["task_id"])
                attempts = browser_attempt_repo.list_for_task(task.id)
                result_attempt = next((attempt for attempt in attempts if attempt.id == task.result_attempt_id), None)
                is_demo = result_attempt is None or result_attempt.source != "openclaw"
                if kind == "flight":
                    supplier = row["airline_name"]
                    title = " / ".join(segment.get("flight_number", "") for segment in item["segments"]) or item["fare_family"] or supplier
                    details = "；".join(filter(None, [
                        f"{run.request.origin} → {run.request.destination}",
                        item.get("fare_family"), f"託運行李：{item.get('checked_baggage', '待確認')}",
                        *[f"{s['origin']} → {s['destination']} {s.get('departure_local', '')} → {s.get('arrival_local', '')}" for s in item["segments"]],
                    ]))
                    conditions = f"改票：{item['change_rule_summary']}；退票：{item['refund_rule_summary']}"
                else:
                    supplier = row["hotel_name"]
                    title = f"{item['room_name']} / {item['rate_name']}"
                    details = f"{run.request.rooms} 間房；床型：{item['bed_type']}；早餐：{ {True: '包含', False: '不包含', None: '待確認'}[item['breakfast_included']] }"
                    conditions = f"取消期限：{item['cancellation_deadline_local'] or '待確認'}；付款：{item['payment_timing']}；額外飯店費用：{item['mandatory_property_fees'] if item['mandatory_property_fees'] is not None else '待確認'}"
                option = {
                    "id": f"official:{kind}:{task.id}:{item['option_id']}", "case_id": case.id, "kind": kind,
                    "supplier_name": supplier, "title": title, "total_amount": str(Decimal(str(item["total_amount"]))),
                    "currency": group["currency"], "details": details, "conditions": conditions,
                    "source_type": "official", "source_reference": "官網查詢" if not is_demo else "Browser Lab 示範",
                    "source_url": row["source_url"], "observed_at": row["observed_at"], "valid_until": None,
                    "is_demo": is_demo, "result_unavailable": task.status != "completed" or task.review_state != "auto_validated", "case_snapshot": trip_snapshot(case) if context_matches else {},
                    "run_id": run.id, "task_id": task.id, "supplier_option_id": item["option_id"],
                    "score": row["score"], "warnings": item.get("warnings", []),
                }
                options.append(option_state(option, case))
    return options


def case_workflow(case_id: str) -> dict:
    case = require_case(case_id)
    options = [option_state(option, case) for option in case_workflow_repo.list_options(case_id)]
    options.extend(_official_options(case, "flight"))
    options.extend(_official_options(case, "hotel"))
    by_id = {option["id"]: option for option in options}
    selections = []
    for snapshot in case_workflow_repo.selections(case_id):
        current = by_id.get(snapshot["id"])
        # Resolve the current result, not just the stored snapshot, before offering a draft.
        if current:
            current = {**current, "selected_at": snapshot["selected_at"]}
            if any(current[key] != snapshot[key] for key in ("total_amount", "currency", "details", "conditions", "observed_at")):
                current = {**current, "usable": False, "blockers": ["方案內容已更新，請重新選取"]}
            if current["source_type"] == "official":
                repo = flight_search_run_repo if current["kind"] == "flight" else hotel_search_run_repo
                run = repo.get(current["run_id"])
                if run is None or (run.selected_task_id, run.selected_option_id) != (current["task_id"], current["supplier_option_id"]):
                    current = {**current, "usable": False, "blockers": ["查價選案已由另一個介面變更，請重新選取"]}
            selections.append(current)
        else:
            selections.append({**snapshot, "usable": False, "blockers": ["原查價結果已不可用，請重新查詢"]})
    return {
        "case": case.model_dump(mode="json"), "options": options, "selections": selections,
        "airport_choices": airport_choices(case.destination),
        "can_draft_offer": bool(selections) and all(option["usable"] for option in selections),
    }


def select_case_option(case_id: str, option_id: str) -> dict:
    workflow = case_workflow(case_id)
    option = next((item for item in workflow["options"] if item["id"] == option_id), None)
    if option is None:
        raise KeyError(option_id)
    if not option["usable"]:
        raise ValueError("；".join(option["blockers"]))
    if option["source_type"] == "official":
        from app.services.browser_tasks import browser_task_service
        selector = browser_task_service.select_option if option["kind"] == "flight" else browser_task_service.select_hotel_option
        selector(option["run_id"], option["task_id"], option["supplier_option_id"])
    saved = case_workflow_repo.select(case_id, option)
    audit(case_id, "operator", "case.option_selected", {"option_id": option_id, "kind": option["kind"]}, now_iso())
    return saved


def local_customer_draft(case_id: str | None, incoming_text: str, workflow: dict | None = None) -> str:
    if not case_id:
        return "您好，收到您的需求了！我會先確認旅行日期、目的地、人數與預算，再整理適合的方案給您。若有特別在意的時間、行李或住宿條件，也請一起告訴我，謝謝。"
    workflow = workflow if workflow is not None else case_workflow(case_id)
    case = workflow["case"]
    lines = [f"{case['customer_name']}您好，", "", "收到您的訊息了，我先為您整理目前的需求：",
             f"目的地：{case['destination'] or '待確認'}",
             f"日期：{case['depart_date'] or '待確認'} → {case['return_date'] or '單程／回程待確認'}",
             f"旅客：{case['adults']} 位成人、{case['children']} 位小孩、{case['infants']} 位嬰兒。"]
    if workflow["can_draft_offer"]:
        lines += ["", "目前選定的參考方案如下（尚未訂購）："]
        totals: dict[str, Decimal] = {}
        for option in workflow["selections"]:
            amount = Decimal(option["total_amount"])
            label = "機票" if option["kind"] == "flight" else "住宿"
            public_title = option["title"] if option["source_type"] == "manual" else f"{option['supplier_name']}｜{option['title']}"
            lines += [f"{label}：{public_title}", option["details"],
                      f"全案旅客的{label}總價：{option['currency']} {_money(amount, option['currency'])}",
                      f"條件：{option['conditions']}", f"來源：{'人工查核的供應商報價' if option['source_type'] == 'manual' else '航空／飯店官網'}；查詢時間：{_taipei_time(option['observed_at'])}"]
            if option["source_type"] == "official" and option.get("source_url"):
                lines.append(f"來源網址：{option['source_url']}")
            if option.get("valid_until"):
                lines.append(f"供應商報價有效至：{_taipei_time(option['valid_until'])}")
            totals[option["currency"]] = totals.get(option["currency"], Decimal(0)) + amount
        if len(workflow["selections"]) > 1:
            if len(totals) == 1:
                currency, total = next(iter(totals.items()))
                lines.append(f"以上已選項目合計：{currency} {_money(total, currency)}（不含未列明項目）")
            else:
                lines.append("以上方案幣別不同，尚未換算合計。")
        lines += ["", "以上是參考方案，價格、機位／房況及未確認的條件仍需在訂購前再次核對，尚未保留或完成訂購。請您確認是否符合需求，我再為您確認後續安排。"]
    else:
        lines += ["", "票價、機位、房況與相關條件還需要確認，我會確認後再提供方案給您。"]
    if any(word in incoming_text for word in ("簽證", "入境", "護照")):
        lines += ["", "您提到的證件／入境事項，我會另外依權威來源與您的旅客資料確認後回覆。"]
    return "\n".join(lines)


def _taipei_time(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M 台北時間")


def _money(amount: Decimal, currency: str) -> str:
    return f"{amount:,.0f}" if currency in {"JPY", "KRW"} else f"{amount:,.2f}"
