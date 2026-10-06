"""Customer-owned private commands remain usable after a travel case closes."""

import json
import sqlite3
from uuid import UUID, uuid5

from app.db import connect
from app.models import now_iso
from app.operations_repository import (
    OperationBusy,
    OperationConflict,
    command_fingerprint,
    encode,
)

CUSTOMER_NAMESPACE = UUID("baf42791-3893-4590-9f89-b7a5243f507d")


def create_id(request_id):
    return "customer_" + uuid5(CUSTOMER_NAMESPACE, str(request_id)).hex


def get_customer(db, customer_id):
    found = db.execute(
        "SELECT payload_json FROM agency_customers WHERE id=?", (customer_id,)
    ).fetchone()
    if not found:
        raise KeyError(customer_id)
    return json.loads(found[0])


def save_customer(db, value):
    db.execute(
        "INSERT INTO agency_customers(id,display_name,revision,payload_json,created_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name,revision=excluded.revision,payload_json=excluded.payload_json",
        (
            value["id"],
            value["display_name"],
            value["revision"],
            encode(value),
            value["created_at"],
        ),
    )


def customer_command(customer_id, data, actor, action, execute):
    if not action.startswith("customer."):
        raise ValueError("Invalid customer command")
    _, digest = command_fingerprint(data, actor, action, private=True)
    try:
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT fingerprint,response_json FROM customer_commands WHERE customer_id=? AND request_id=?",
                (customer_id, str(data.request_id)),
            ).fetchone()
            if previous:
                if previous[0] != digest:
                    raise OperationConflict(
                        "重試編號已用於不同內容，請先核對上次儲存結果"
                    )
                return json.loads(previous[1])
            result = execute(db)
            from app.services.reminders import cancel_invalid

            cancel_invalid(db, customer_id=customer_id)
            db.execute(
                "INSERT INTO customer_commands VALUES(?,?,?,?,?,?,?)",
                (
                    customer_id,
                    str(data.request_id),
                    action,
                    digest,
                    encode(result),
                    actor,
                    now_iso(),
                ),
            )
            db.execute(
                "INSERT INTO audit_log(case_id,actor,action,payload_json,created_at) VALUES(?,?,?,?,?)",
                (
                    None,
                    actor,
                    "agency." + action,
                    encode(
                        {"customer_id": customer_id, "request_id": str(data.request_id)}
                    ),
                    now_iso(),
                ),
            )
            return result
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            raise OperationBusy("資料正在更新，請稍後以原內容重試") from exc
        raise
    except sqlite3.IntegrityError as exc:
        raise OperationConflict("客戶資料已存在或關聯不完整，請重新核對") from exc
