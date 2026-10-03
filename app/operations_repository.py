from __future__ import annotations

import hashlib
import json
import sqlite3

from app.db import connect
from app.models import new_id, now_iso
from app.repositories import _case_from_row


class OperationConflict(ValueError):
    pass


class OperationBusy(RuntimeError):
    pass


TABLES = {"quotes", "work_items", "bookings", "documents", "ledger", "pretrip"}


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


def rows(db, table: str, case_id: str) -> list[dict]:
    if table not in TABLES:
        raise ValueError("unknown operations table")
    return [json.loads(row[0]) for row in db.execute(
        f"SELECT payload_json FROM agency_{table} WHERE case_id=? ORDER BY created_at, id", (case_id,))]


def record(db, table: str, case_id: str, record_id: str) -> dict:
    if table not in TABLES:
        raise ValueError("unknown operations table")
    found = db.execute(f"SELECT payload_json FROM agency_{table} WHERE case_id=? AND id=?", (case_id, record_id)).fetchone()
    if not found:
        raise KeyError(record_id)
    return json.loads(found[0])


def save(db, table: str, value: dict) -> dict:
    if table not in TABLES:
        raise ValueError("unknown operations table")
    columns = {"id": value["id"], "case_id": value["case_id"], "payload_json": encode(value), "created_at": value["created_at"]}
    if table == "quotes":
        columns.update(version=value["version"], status=value["status"])
    elif table == "work_items":
        columns.update(status=value["status"], due_at=value["due_at"])
    elif table == "bookings":
        columns.update(quote_id=value["quote_id"], kind=value["kind"], status=value["status"],
                       supplier_key=value["supplier"].casefold(), confirmation_key="".join(value["confirmation_number"].split()).casefold())
    elif table == "pretrip":
        columns.update(version=value["version"])
    fields = list(columns)
    updates = ",".join(f"{name}=excluded.{name}" for name in fields if name not in {"id", "case_id", "created_at"})
    db.execute(f"INSERT INTO agency_{table}({','.join(fields)}) VALUES({','.join('?' for _ in fields)}) ON CONFLICT(id) DO UPDATE SET {updates}", tuple(columns.values()))
    return value


def new_record(case_id: str, prefix: str, payload: dict) -> dict:
    return {**payload, "id": new_id(prefix), "case_id": case_id, "created_at": now_iso(), "revision": 1}


def command(case_id: str, data, actor: str, action: str, execute) -> dict:
    payload = data.model_dump(mode="json", exclude={"request_id"}, exclude_unset=action.endswith(".patch"))
    digest = fingerprint({"action": action, "payload": payload, "actor": actor})
    try:
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            case_row = db.execute("SELECT * FROM trip_cases WHERE id=?", (case_id,)).fetchone()
            if case_row is None:
                raise KeyError(case_id)
            previous = db.execute("SELECT fingerprint,response_json FROM agency_commands WHERE case_id=? AND request_id=?", (case_id, str(data.request_id))).fetchone()
            if previous:
                if previous[0] != digest:
                    raise OperationConflict("重試編號已用於不同內容，請重新提交")
                return json.loads(previous[1])
            result = execute(db, _case_from_row(case_row))
            next_status = db.execute("SELECT status FROM trip_cases WHERE id=?", (case_id,)).fetchone()[0]
            timestamp = now_iso()
            db.execute("INSERT INTO agency_commands VALUES(?,?,?,?,?,?,?)", (case_id, str(data.request_id), action, digest, encode(result), actor, timestamp))
            # Never call audit() or another repository writer while holding this lock.
            db.execute("INSERT INTO audit_log(case_id,actor,action,payload_json,created_at) VALUES(?,?,?,?,?)", (case_id, actor, f"agency.{action}", encode({"request_id": str(data.request_id), "record_id": result.get("id"), "reason": payload.get("reason", ""), "status_before": case_row["status"], "status_after": next_status}), timestamp))
            return result
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            raise OperationBusy("資料正在更新，請稍後以原內容重試") from exc
        raise
    except sqlite3.IntegrityError as exc:
        raise OperationConflict("已有相同確認紀錄或資料關聯不完整，請核對案件") from exc
