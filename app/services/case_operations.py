from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.config import settings
from app.db import connect
from app.models import now_iso
from app.operations_repository import OperationConflict, command, encode, fingerprint, new_record, record, rows, save
from app.repositories import _case_from_row
from app.services.case_workflow import case_workflow, trip_snapshot

BUSINESS_ZONE = ZoneInfo("Asia/Taipei")


def snapshot(case) -> dict:
    return {**trip_snapshot(case), "customer_name": case.customer_name}


def trip_matches(first: dict, second: dict) -> bool:
    # The stored name is customer-facing display data, not a travel constraint.
    return {k: v for k, v in first.items() if k != "customer_name"} == {k: v for k, v in second.items() if k != "customer_name"}


def confirmed_bookings(db, case, quote: dict) -> list[dict]:
    return [b for b in rows(db, "bookings", case.id) if b["status"] == "confirmed" and b["quote_id"] == quote["id"] and trip_matches(b["case_snapshot"], snapshot(case))]


def update_booking_status(db, case, quote: dict) -> None:
    covered = {b["kind"] for b in confirmed_bookings(db, case, quote)}
    complete = {i["kind"] for i in quote["items"]} <= covered
    if case.status.value not in {"travelling", "closed"}:
        db.execute("UPDATE trip_cases SET status=?,updated_at=? WHERE id=?", ("confirmed" if complete else "booking", now_iso(), case.id))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise OperationConflict(message)


def accepted_quote(db, case_id: str) -> dict:
    found = next((q for q in rows(db, "quotes", case_id) if q["status"] == "accepted"), None)
    require(found is not None, "請先記錄客人採用的報價版本")
    return found


def validate_links(db, case_id: str, payload: dict) -> None:
    for field, table in [("quote_id", "quotes"), ("booking_id", "bookings"), ("document_id", "documents")]:
        if payload.get(field):
            record(db, table, case_id, payload[field])


def selection_guard(db, case_id: str) -> str:
    case = _case_from_row(db.execute("SELECT * FROM trip_cases WHERE id=?", (case_id,)).fetchone())
    selections = list(db.execute("SELECT snapshot_json FROM case_option_selections WHERE case_id=? ORDER BY kind", (case_id,)))
    source_states = []
    for raw in selections:
        selected = json.loads(raw[0])
        if selected["source_type"] == "official":
            task = db.execute("SELECT result_json,result_attempt_id,status,review_state FROM browser_tasks WHERE id=?", (selected["task_id"],)).fetchone()
            table = "flight_search_runs" if selected["kind"] == "flight" else "hotel_search_runs"
            run = db.execute(f"SELECT selected_task_id,selected_option_id FROM {table} WHERE id=?", (selected["run_id"],)).fetchone()
            attempt = db.execute("SELECT source,outcome FROM browser_attempts WHERE id=?", (task[1],)).fetchone() if task else None
            source_states.append([tuple(task) if task else None, tuple(run) if run else None, tuple(attempt) if attempt else None])
        else:
            option = db.execute("SELECT payload_json FROM case_options WHERE case_id=? AND id=?", (case_id, selected["id"])).fetchone()
            source_states.append(tuple(option) if option else None)
    return fingerprint([snapshot(case), [tuple(r) for r in selections], source_states])


def create_quote(case_id: str, data, actor: str) -> dict:
    # Expensive official-result comparisons happen without holding the write lock.
    with connect() as db:
        db.execute("BEGIN")
        if not db.execute("SELECT id FROM trip_cases WHERE id=?", (case_id,)).fetchone():
            raise KeyError(case_id)
        guard = selection_guard(db, case_id)
    workflow = case_workflow(case_id)
    options = workflow["selections"]
    with connect() as db:
        db.execute("BEGIN")
        after_guard = selection_guard(db, case_id)

    def execute(db, case):
        require(workflow["can_draft_offer"], "請先選取仍有效、符合案件的實際方案")
        require(guard == after_guard == selection_guard(db, case_id), "案件或選案已變更，請重新開啟報價")
        require(case.status.value != "closed", "已結案案件請先確認是否需要重新開案")
        now = datetime.now(timezone.utc)
        expiries = [datetime.fromisoformat(o["valid_until"]) if o.get("valid_until") else datetime.fromisoformat(o["observed_at"]) + timedelta(hours=settings.quote_max_age_hours) for o in options]
        require(now < data.valid_until <= min(expiries), "報價期限須在未來，且不可晚於所選供應商價格的有效時間")
        items = []
        for option in options:
            item = {key: option[key] for key in ["id", "kind", "title", "currency", "total_amount", "details", "conditions"]}
            if option["source_type"] == "official":
                item["title"] = f"{option['supplier_name']}｜{option['title']}"
            items.append(item)
        totals = {}
        for item in items:
            totals[item["currency"]] = totals.get(item["currency"], Decimal(0)) + Decimal(item["total_amount"])
        adjustments = {a.currency: a for a in data.adjustments}
        require(len(adjustments) == len(data.adjustments) and set(adjustments) <= set(totals), "費用調整的幣別需與方案一致，且不可重複")
        require(set(data.costs) <= {i["id"] for i in items}, "成本欄位不屬於目前選案")
        margins = {}
        for currency, base in totals.copy().items():
            a = adjustments.get(currency)
            total = base + (a.service_fee - a.discount if a else Decimal(0))
            require(total > 0, "折扣不可使報價總額為零或負數")
            totals[currency] = f"{total:.2f}"
            matching = [i for i in items if i["currency"] == currency]
            margins[currency] = f"{total - sum(data.costs[i['id']] for i in matching):.2f}" if all(data.costs.get(i["id"]) is not None for i in matching) else None
        version = max((q["version"] for q in rows(db, "quotes", case_id)), default=0) + 1
        quote = new_record(case_id, "quote", {"version": version, "status": "draft", "title": data.title,
            "case_snapshot": snapshot(case), "valid_until": data.valid_until.isoformat(), "includes": data.includes, "excludes": data.excludes,
            "items": items, "adjustments": [a.model_dump(mode="json") for a in data.adjustments],
            "totals": totals, "costs": {k: f"{v:.2f}" if v is not None else None for k, v in data.costs.items()}, "expected_margin": margins, "events": []})
        return save(db, "quotes", quote)
    return command(case_id, data, actor, "quote.create", execute)


def decide_quote(case_id: str, quote_id: str, action: str, data, actor: str) -> dict:
    def execute(db, case):
        q = record(db, "quotes", case_id, quote_id)
        require(case.status.value != "closed", "已結案案件請先重新開案")
        require(data.occurred_at >= datetime.fromisoformat(q["created_at"]) - timedelta(minutes=5), "送出／決定時間不可早於報價建立")
        if action == "sent":
            require(q["status"] == "draft", "只有草稿可以記錄已送出")
            require(trip_matches(q["case_snapshot"], snapshot(case)) and datetime.fromisoformat(q["valid_until"]) > datetime.now(timezone.utc), "報價已過期或需求已變更，請建立新版")
            q["status"] = "sent"
        elif action in {"accept", "reject"}:
            require(q["status"] == "sent", "請先核對並記錄此版本已送給客人")
            sent = next(e for e in reversed(q["events"]) if e["action"] == "sent")
            require(data.occurred_at >= datetime.fromisoformat(sent["occurred_at"]) - timedelta(minutes=5), "客人決定時間不可早於實際送出報價")
            if action == "accept":
                require(trip_matches(q["case_snapshot"], snapshot(case)) and datetime.fromisoformat(q["valid_until"]) > datetime.now(timezone.utc), "報價已過期或需求已變更，請重新查核並建立新版")
                previous = next((old for old in rows(db, "quotes", case_id) if old["status"] == "accepted"), None)
                if previous:
                    require(data.amend and len(data.reason.strip()) >= 3, "更換客人採用版本須勾選異動核對並說明原因；原收付款與訂購紀錄仍保留")
                for old in rows(db, "quotes", case_id):
                    if old["id"] != q["id"] and old["status"] in {"draft", "sent", "accepted"}:
                        old["status"] = "replaced"
                        old["events"].append({"action": "replaced", "by_quote_id": q["id"], "reason": data.reason, "actor": actor, "at": now_iso()})
                        save(db, "quotes", old)
                q["status"] = "accepted"
                if case.status.value not in {"travelling", "closed"}:
                    db.execute("UPDATE trip_cases SET status='booking',updated_at=? WHERE id=?", (now_iso(), case_id))
            else:
                q["status"] = "rejected"
        else:
            raise KeyError(action)
        q["events"].append({"action": action, "reference": data.reference, "occurred_at": data.occurred_at.isoformat(), "reason": data.reason, "actor": actor, "at": now_iso()})
        return save(db, "quotes", q)
    return command(case_id, data, actor, f"quote.{quote_id}.{action}", execute)


def create_work_item(case_id: str, data, actor: str) -> dict:
    def execute(db, case):
        payload = data.model_dump(mode="json", exclude={"request_id"})
        validate_links(db, case_id, payload)
        return save(db, "work_items", new_record(case_id, "work", {**payload, "status": "open", "history": []}))
    return command(case_id, data, actor, "work.create", execute)


def patch_work_item(case_id: str, item_id: str, data, actor: str) -> dict:
    def execute(db, case):
        item = record(db, "work_items", case_id, item_id)
        require(item["revision"] == data.expected_revision, "待辦已由另一個操作更新，請重新開啟並核對")
        changes = data.model_dump(mode="json", exclude_unset=True, exclude={"request_id", "expected_revision", "reason"})
        require(all(value is not None for value in changes.values()) and bool(changes), "請填要修改的待辦內容，欄位不可留空")
        item["history"].append({"at": now_iso(), "actor": actor, "reason": data.reason, "before": {k: item[k] for k in changes}, "changes": changes})
        item.update(changes)
        item["revision"] += 1
        return save(db, "work_items", item)
    return command(case_id, data, actor, f"work.{item_id}.patch", execute)


def deadline_state(item: dict) -> dict:
    due = datetime.fromisoformat(item["due_at"])
    now = datetime.now(timezone.utc)
    return {**item, "timing": None if item["status"] != "open" else "overdue" if due < now else "today" if due.astimezone(BUSINESS_ZONE).date() == now.astimezone(BUSINESS_ZONE).date() else "upcoming"}


def list_work_items() -> list[dict]:
    with connect() as db:
        found = db.execute("SELECT w.payload_json,c.customer_name FROM agency_work_items w JOIN trip_cases c ON c.id=w.case_id ORDER BY w.due_at,w.id").fetchall()
    return [deadline_state({**json.loads(r[0]), "customer_name": r[1]}) for r in found]


def create_booking(case_id: str, data, actor: str) -> dict:
    def execute(db, case):
        q = accepted_quote(db, case_id)
        require(case.status.value != "closed", "已結案案件請先重新開案")
        require(trip_matches(q["case_snapshot"], snapshot(case)), "需求已變更，請先完成新版報價與客人核對")
        require(data.kind in {i["kind"] for i in q["items"]}, "此訂購種類不在客人採用的報價中")
        payload = data.model_dump(mode="json", exclude={"request_id", "checked"})
        booking = save(db, "bookings", new_record(case_id, "booking", {**payload, "quote_id": q["id"], "case_snapshot": snapshot(case), "status": "confirmed"}))
        update_booking_status(db, case, q)
        return booking
    return command(case_id, data, actor, "booking.create", execute)


def rebind_booking(case_id: str, booking_id: str, data, actor: str) -> dict:
    def execute(db, case):
        booking = record(db, "bookings", case_id, booking_id)
        quote = accepted_quote(db, case_id)
        require(case.status.value != "closed" and booking["status"] == "confirmed", "只能重新核對未結案案件的有效訂購紀錄")
        require(trip_matches(quote["case_snapshot"], snapshot(case)) and booking["kind"] in {i["kind"] for i in quote["items"]}, "請先核對目前案件與採用報價的種類及需求")
        booking.setdefault("history", []).append({"action": "rebind", "before": {k: booking[k] for k in ["quote_id", "case_snapshot", "customer_details", "reference", "occurred_at"]}, "reason": data.reason, "actor": actor, "at": now_iso()})
        booking.update(quote_id=quote["id"], case_snapshot=snapshot(case), customer_details=data.customer_details, reference=data.reference, occurred_at=data.occurred_at.isoformat())
        booking["revision"] += 1
        save(db, "bookings", booking)
        update_booking_status(db, case, quote)
        return booking
    return command(case_id, data, actor, f"booking.{booking_id}.rebind", execute)


def void_record(case_id: str, table: str, record_id: str, data, actor: str) -> dict:
    def execute(db, case):
        value = record(db, table, case_id, record_id)
        require(value.get("status") != "voided", "此紀錄已作廢")
        value.update(status="voided", void_reason=data.reason, void_reference=data.reference, void_at=data.occurred_at.isoformat(), void_actor=actor)
        save(db, table, value)
        if table == "ledger":
            validate_ledger(rows(db, "ledger", case_id))
        elif case.status.value == "confirmed":
            q = accepted_quote(db, case_id)
            update_booking_status(db, case, q)
        return value
    return command(case_id, data, actor, f"{table}.{record_id}.void", execute)


def ledger_totals(entries: list[dict]) -> dict:
    totals = {}
    for entry in entries:
        if entry.get("status") == "voided":
            continue
        group = totals.setdefault(entry["currency"], {kind: Decimal(0) for kind in ["customer_receipt", "customer_refund", "supplier_payment", "supplier_refund"]})
        group[entry["kind"]] += Decimal(entry["amount"])
    return totals


def validate_ledger(entries: list[dict]) -> None:
    for values in ledger_totals(entries).values():
        require(values["customer_receipt"] >= values["customer_refund"] and values["supplier_payment"] >= values["supplier_refund"], "退款不可超過同案件、同幣別的實際收款／付款；請先核對原紀錄")


def create_ledger_entry(case_id: str, data, actor: str) -> dict:
    def execute(db, case):
        q = accepted_quote(db, case_id)
        if data.booking_id:
            record(db, "bookings", case_id, data.booking_id)
        payload = data.model_dump(mode="json", exclude={"request_id", "checked"})
        entry = save(db, "ledger", new_record(case_id, "money", {**payload, "quote_id": q["id"], "status": "recorded"}))
        validate_ledger(rows(db, "ledger", case_id))
        return entry
    return command(case_id, data, actor, "ledger.create", execute)


def balances(quote: dict | None, entries: list[dict]) -> dict:
    ledger = ledger_totals(entries)
    currencies = set(ledger) | set(quote["totals"] if quote else {})
    result = {}
    for currency in sorted(currencies):
        group = ledger.get(currency, {kind: Decimal(0) for kind in ["customer_receipt", "customer_refund", "supplier_payment", "supplier_refund"]})
        net_received = group["customer_receipt"] - group["customer_refund"]
        net_paid = group["supplier_payment"] - group["supplier_refund"]
        due = quote["totals"].get(currency) if quote else None
        result[currency] = {**{k: f"{v:.2f}" for k, v in group.items()}, "net_received": f"{net_received:.2f}", "net_paid": f"{net_paid:.2f}", "net_cash": f"{net_received - net_paid:.2f}",
            "quote_total": due, "customer_balance": f"{Decimal(due) - net_received:.2f}" if due is not None else None,
            "expected_margin": quote["expected_margin"].get(currency) if quote else None}
    return result


def validate_document_booking(db, case, booking_id: str) -> None:
    booking = record(db, "bookings", case.id, booking_id)
    quote = accepted_quote(db, case.id)
    require(booking["status"] == "confirmed" and booking["quote_id"] == quote["id"] and trip_matches(booking["case_snapshot"], snapshot(case)), "請將文件關聯至目前採用報價的有效訂購紀錄，或以原因修正為不綁定")


def create_document(case_id: str, data, actor: str) -> dict:
    def execute(db, case):
        payload = data.model_dump(mode="json", exclude={"request_id"})
        validate_links(db, case_id, payload)
        if data.booking_id:
            validate_document_booking(db, case, data.booking_id)
        return save(db, "documents", new_record(case_id, "document", {**payload, "status": "missing", "customer_text": "", "customer_url": None}))
    return command(case_id, data, actor, "document.create", execute)


def patch_document(case_id: str, document_id: str, data, actor: str) -> dict:
    def execute(db, case):
        doc = record(db, "documents", case_id, document_id)
        require(doc["revision"] == data.expected_revision, "文件已更新，請重新開啟核對")
        require(data.status != "ready" or bool(data.customer_text.strip() or data.customer_url), "文件備妥時需填對客說明或文件連結")
        changes = data.model_dump(mode="json", exclude_unset=True, exclude={"request_id", "expected_revision", "checked"})
        if "required" in changes:
            require(data.required is not None, "必備標示不可留空")
        binding_changed = any(key in changes and changes[key] != doc.get(key) for key in ["required", "booking_id"])
        if binding_changed:
            require(len(data.reason.strip()) >= 3, "更改必備標示或關聯訂購須填修正原因")
        if data.booking_id:
            validate_document_booking(db, case, data.booking_id)
        doc.setdefault("history", []).append({"before": {k: doc.get(k) for k in changes}, "actor": actor, "at": now_iso(), "reason": data.reason})
        doc.update(changes)
        doc["revision"] += 1
        return save(db, "documents", doc)
    return command(case_id, data, actor, f"document.{document_id}.patch", execute)


def pack_source(db, case, quote: dict) -> dict:
    bookings = rows(db, "bookings", case.id)
    docs = rows(db, "documents", case.id)
    # Include voided/old bindings and every revision in the guard; no URL is fetched.
    return {"case_snapshot": snapshot(case), "quote_id": quote["id"], "quote_version": quote["version"], "bookings": bookings, "documents": docs}


def pack_blockers(source: dict, quote: dict) -> list[str]:
    blockers = []
    if not trip_matches(source["case_snapshot"], quote["case_snapshot"]):
        blockers.append("案件需求與客人採用報價不同")
    bookings = [b for b in source["bookings"] if b["status"] == "confirmed" and b["quote_id"] == quote["id"] and trip_matches(b["case_snapshot"], source["case_snapshot"])]
    kinds = {b["kind"] for b in bookings}
    for kind in {i["kind"] for i in quote["items"]} - kinds:
        blockers.append(f"{'機票' if kind == 'flight' else '飯店'}尚無符合此報價的訂購確認")
    # A checklist is mandatory, with product-specific required evidence entries.
    for kind, doc_kind in [("flight", "e_ticket"), ("hotel", "hotel_voucher")]:
        if kind in kinds and not any(d["kind"] == doc_kind and d["required"] for d in source["documents"]):
            blockers.append(f"請加入必備的{'電子機票' if kind == 'flight' else '住宿憑證'}文件項目")
    confirmed_ids = {b["id"] for b in bookings}
    for doc in source["documents"]:
        if doc["required"] and (doc["status"] != "ready" or (doc.get("booking_id") and doc["booking_id"] not in confirmed_ids)):
            blockers.append(f"文件待核對：{doc['title']}")
    return blockers


def public_quote(quote: dict) -> dict:
    safe = {key: quote[key] for key in ["version", "title", "case_snapshot", "created_at", "valid_until", "includes", "excludes", "adjustments", "totals"]}
    safe["items"] = [{k: item[k] for k in ["kind", "title", "currency", "total_amount", "details", "conditions"]} for item in quote["items"]]
    return safe


def public_pack(pack: dict) -> dict:
    source = pack["source"]
    current_ids = {b["id"] for b in source["bookings"] if b["status"] == "confirmed" and b["quote_id"] == source["quote_id"] and trip_matches(b["case_snapshot"], source["case_snapshot"])}
    return {"id": pack["id"], "version": pack["version"], "title": pack["title"], "created_at": pack["created_at"], "case_snapshot": source["case_snapshot"],
        "quote_version": source["quote_version"], "blockers": pack["blockers"],
        "bookings": [{k: b[k] for k in ["kind", "title", "confirmation_number", "customer_details"]} for b in source["bookings"] if b["status"] == "confirmed" and b["quote_id"] == source["quote_id"] and trip_matches(b["case_snapshot"], source["case_snapshot"])],
        "documents": [{k: d[k] for k in ["title", "customer_text", "customer_url"]} for d in source["documents"] if d["status"] == "ready" and (not d.get("booking_id") or d["booking_id"] in current_ids)]}


def create_pack(case_id: str, data, actor: str) -> dict:
    def execute(db, case):
        q = accepted_quote(db, case_id)
        source = pack_source(db, case, q)
        blockers = pack_blockers(source, q)
        version = max((p["version"] for p in rows(db, "pretrip", case_id)), default=0) + 1
        pack = new_record(case_id, "pack", {"version": version, "title": data.title, "status": "draft" if blockers else "prepared", "source": source, "source_hash": fingerprint(source), "blockers": blockers})
        return save(db, "pretrip", pack)
    return command(case_id, data, actor, "pretrip.create", execute)


def deliver_pack(case_id: str, pack_id: str, data, actor: str) -> dict:
    def execute(db, case):
        pack = record(db, "pretrip", case_id, pack_id)
        q = accepted_quote(db, case_id)
        source = pack_source(db, case, q)
        require(pack["status"] == "prepared", "只有完整備妥的行前摘要才能記錄交付；缺件版本請補齊後重新產生")
        require(pack["source_hash"] == fingerprint(source) and not pack_blockers(source, q), "報價版本、訂購確認、案件或文件已變更，請重新產生並核對行前摘要")
        pack.update(status="delivered", delivery={"channel": data.channel, "reference": data.reference, "occurred_at": data.occurred_at.isoformat(), "actor": actor})
        return save(db, "pretrip", pack)
    return command(case_id, data, actor, f"pretrip.{pack_id}.deliver", execute)


def case_operations(case_id: str) -> dict:
    with connect() as db:
        db.execute("BEGIN")
        case_row = db.execute("SELECT * FROM trip_cases WHERE id=?", (case_id,)).fetchone()
        if not case_row:
            raise KeyError(case_id)
        case = _case_from_row(case_row)
        bundle = {table: rows(db, table, case_id) for table in ["quotes", "work_items", "bookings", "documents", "ledger", "pretrip"]}
        quote = next((q for q in bundle["quotes"] if q["status"] == "accepted"), None)
        bundle["accepted_quote_id"] = quote["id"] if quote else None
        bundle["balances"] = balances(quote, bundle["ledger"])
        bundle["warnings"] = pack_blockers(pack_source(db, case, quote), quote) if quote else ["尚未記錄客人採用的報價"]
        if quote:
            bundle["warnings"].extend(f"訂購需重新核對採用版本：{b['title']}" for b in bundle["bookings"] if b["status"] == "confirmed" and (b["quote_id"] != quote["id"] or not trip_matches(b["case_snapshot"], snapshot(case))))
        for booking in bundle["bookings"]:
            booking["binding_current"] = bool(quote and booking["quote_id"] == quote["id"] and trip_matches(booking["case_snapshot"], snapshot(case)))
            if booking["status"] == "confirmed":
                duplicate = db.execute("SELECT 1 FROM agency_bookings WHERE case_id<>? AND status='confirmed' AND kind=? AND supplier_key=? AND confirmation_key=? LIMIT 1", (case_id, booking["kind"], booking["supplier"].casefold(), "".join(booking["confirmation_number"].split()).casefold())).fetchone()
                if duplicate:
                    bundle["warnings"].append(f"確認號也登錄在其他案件，請核對是否為同一團體或誤填：{booking['confirmation_number']}")
        bundle["work_items"] = [deadline_state(i) for i in bundle["work_items"]]
        for pack in bundle["pretrip"]:
            pack["stale"] = not quote or pack["source_hash"] != fingerprint(pack_source(db, case, quote))
        return {"case": case.model_dump(mode="json"), **bundle}
