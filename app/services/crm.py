"""Explicit customer attribution, encrypted drafts/history and complaint follow-up."""

import json

from app.customer_repository import (
    create_id,
    customer_command,
    get_customer,
    save_customer,
)
from app.db import connect
from app.models import now_iso
from app.operations_repository import command, encode, new_record, record, rows, save
from app.services.case_operations import require
from app.services.travel_files import cipher, decrypt, encrypt


def customer_meta(value):
    return {
        k: value[k]
        for k in ("id", "display_name", "revision", "created_at", "consents")
    }


def profile(data, actor, customer_id=None):
    cipher()
    customer_id = customer_id or create_id(data.request_id)

    def execute(db):
        private_content = encode(data.model_dump(include={"phone", "email", "notes"}))
        if data.expected_revision is None:
            require(
                not db.execute(
                    "SELECT 1 FROM agency_customers WHERE id=?", (customer_id,)
                ).fetchone(),
                "客戶已存在，請開啟目前資料修改",
            )
            value = {
                "id": customer_id,
                "revision": 1,
                "created_at": now_iso(),
                "history": [],
                "consents": {},
            }
        else:
            value = get_customer(db, customer_id)
            require(
                value["revision"] == data.expected_revision,
                "客戶資料已更新，請重新開啟核對",
            )
            previous_email = json.loads(decrypt(value["encrypted"]))["email"]
            if data.email != previous_email and value["consents"].get("email"):
                previous = value["consents"]["email"]
                value.setdefault("consent_history", []).append(previous)
                value["consents"]["email"] = {
                    **previous,
                    "granted": False,
                    "revision": previous["revision"] + 1,
                    "actor": actor,
                    "reference": data.reference,
                    "at": data.occurred_at.isoformat(),
                    "reason": "email_changed",
                }
            value["history"].append(
                {
                    **(
                        {"encrypted": value["encrypted"]}
                        if decrypt(value["encrypted"]).decode() != private_content
                        else {}
                    ),
                    "display_name": value["display_name"],
                    "actor": value["actor"],
                    "at": value["occurred_at"],
                }
            )
            value["revision"] += 1
        value.update(
            display_name=data.display_name,
            encrypted=value.get("encrypted")
            if value.get("encrypted")
            and decrypt(value["encrypted"]).decode() == private_content
            else encrypt(private_content.encode()),
            actor=actor,
            reference=data.reference,
            occurred_at=data.occurred_at.isoformat(),
        )
        save_customer(db, value)
        return customer_meta(value)

    return customer_command(customer_id, data, actor, "customer.profile.write", execute)


def consent(customer_id, data, actor):
    cipher()

    def execute(db):
        value = get_customer(db, customer_id)
        require(
            value["revision"] == data.expected_revision,
            "客戶資料或接收同意已更新，請重新核對",
        )
        if data.granted:
            require(
                bool(json.loads(decrypt(value["encrypted"]))["email"]),
                "請先填寫此客戶目前的 Email，再記錄接收同意",
            )
        previous = value["consents"].get(data.channel)
        if previous:
            value.setdefault("consent_history", []).append(previous)
        value["consents"][data.channel] = {
            "channel": data.channel,
            "granted": data.granted,
            "revision": (previous or {}).get("revision", 0) + 1,
            "actor": actor,
            "reference": data.reference,
            "at": data.occurred_at.isoformat(),
        }
        value["revision"] += 1
        save_customer(db, value)
        return customer_meta(value)

    return customer_command(customer_id, data, actor, "customer.consent", execute)


def link(case_id, data, actor):
    cipher()

    def execute(db, case):
        get_customer(db, data.customer_id)
        previous = next(iter(rows(db, "customer_links", case_id)), None)
        require(
            (previous or {}).get("revision", 0) == data.expected_revision,
            "客戶關聯已更新，請重新核對",
        )
        value = previous or new_record(case_id, "customer_link", {"history": []})
        if previous:
            value["history"].append(
                {
                    k: previous.get(k)
                    for k in (
                        "customer_id",
                        "actor",
                        "reference",
                        "occurred_at",
                        "reason",
                    )
                }
            )
            value["revision"] += 1
        value.update(
            customer_id=data.customer_id,
            actor=actor,
            reference=data.reference,
            occurred_at=data.occurred_at.isoformat(),
            reason=data.reason,
        )
        return save(db, "customer_links", value)

    return command(
        case_id, data, actor, "crm.link", execute, private=True, allow_closed=True
    )


def message_meta(value):
    keys = (
        "id",
        "customer_id",
        "revision",
        "kind",
        "channel",
        "status",
        "owner",
        "followup_at",
        "service_order_id",
        "corrects_id",
        "created_at",
        "actor",
    )
    return {k: value.get(k) for k in keys}


def create_message(case_id, data, actor):
    cipher()

    def execute(db, case):
        linked = next(iter(rows(db, "customer_links", case_id)), None)
        require(
            linked is not None, "請先建立或明確關聯這位客戶，聯絡紀錄才會歸到正確的人"
        )
        if data.service_order_id:
            record(db, "service_orders", case_id, data.service_order_id)
        if data.corrects_id:
            record(db, "communications", case_id, data.corrects_id)
        require(
            len(rows(db, "communications", case_id)) < 1000,
            "單一案件最多保存 1000 筆聯絡紀錄",
        )
        status = {
            "draft": "draft",
            "incoming": "received",
            "outgoing": "recorded",
            "contact": "noted",
            "complaint": "open",
        }[data.kind]
        value = new_record(
            case_id,
            "communication",
            {
                "customer_id": linked["customer_id"],
                "kind": data.kind,
                "channel": data.channel,
                "status": status,
                "owner": data.owner,
                "followup_at": data.followup_at.isoformat()
                if data.followup_at
                else None,
                "service_order_id": data.service_order_id,
                "corrects_id": data.corrects_id,
                "encrypted": encrypt(data.body.encode()),
                "history": [],
                "actor": actor,
                "reference": data.reference,
                "occurred_at": data.occurred_at.isoformat(),
            },
        )
        save(db, "communications", value)
        return message_meta(value)

    return command(
        case_id,
        data,
        actor,
        "crm.message.create",
        execute,
        private=True,
        allow_closed=True,
    )


def patch_message(case_id, message_id, data, actor):
    cipher()

    def execute(db, case):
        value = record(db, "communications", case_id, message_id)
        require(
            value["revision"] == data.expected_revision,
            "聯絡紀錄已更新，請重新開啟核對",
        )
        require(
            value["status"] == "draft" or value["kind"] == "complaint",
            "已記錄的往來內容保留原文；請另外追加更正紀錄",
        )
        if data.body is not None:
            require(value["status"] == "draft", "客訴原文保留；請追加更正或後續聯絡")
        if data.status is not None:
            require(value["kind"] == "complaint", "只有客訴可更新處理狀態")
        value["history"].append(
            {
                **(
                    {"encrypted": value["encrypted"]}
                    if data.body is not None
                    and data.body != decrypt(value["encrypted"]).decode()
                    else {}
                ),
                "status": value["status"],
                "owner": value["owner"],
                "followup_at": value["followup_at"],
                "actor": actor,
                "reference": data.reference,
                "at": data.occurred_at.isoformat(),
            }
        )
        if data.body is not None:
            value["encrypted"] = encrypt(data.body.encode())
        for name in ("owner", "status", "followup_at"):
            if name in data.model_fields_set:
                field = getattr(data, name)
                value[name] = (
                    field.isoformat() if name == "followup_at" and field else field
                )
        value.update(
            revision=value["revision"] + 1,
            actor=actor,
            reference=data.reference,
            occurred_at=data.occurred_at.isoformat(),
        )
        save(db, "communications", value)
        return message_meta(value)

    return command(
        case_id,
        data,
        actor,
        f"crm.message.{message_id}.patch",
        execute,
        private=True,
        allow_closed=True,
    )


def attest_sent(case_id, message_id, data, actor):
    cipher()

    def execute(db, case):
        value = record(db, "communications", case_id, message_id)
        require(
            value["revision"] == data.expected_revision
            and value["status"] in {"draft", "recorded"},
            "內容已更新或已記錄送出，請重新核對",
        )
        require(
            value["kind"] in {"draft", "outgoing"},
            "只有對客草稿或傳出訊息可以記錄已人工送出",
        )
        value["history"].append(
            {
                "status": value["status"],
                "actor": actor,
                "reference": data.reference,
                "at": data.occurred_at.isoformat(),
            }
        )
        value.update(
            kind="outgoing",
            status="sent",
            revision=value["revision"] + 1,
            actor=actor,
            reference=data.reference,
            occurred_at=data.occurred_at.isoformat(),
        )
        save(db, "communications", value)
        return message_meta(value)

    return command(
        case_id,
        data,
        actor,
        f"crm.message.{message_id}.sent",
        execute,
        private=True,
        allow_closed=True,
    )


def audit_read(db, actor, action, record_id, case_id=None):
    db.execute(
        "INSERT INTO audit_log(case_id,actor,action,payload_json,created_at) VALUES(?,?,?,?,?)",
        (
            case_id,
            actor,
            "agency." + action,
            encode({"record_id": record_id}),
            now_iso(),
        ),
    )


def reveal_customer(customer_id, actor):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        value = get_customer(db, customer_id)
        result = {**customer_meta(value), **json.loads(decrypt(value["encrypted"]))}
        audit_read(db, actor, "customer.reveal", customer_id)
        return result


def message_body(db, value):
    if value.get("notification_job_id"):
        job = db.execute(
            "SELECT payload_json FROM agency_notification_jobs WHERE id=? AND case_id=?",
            (value["notification_job_id"], value["case_id"]),
        ).fetchone()
        if not job:
            raise ValueError("通知內容關聯不完整")
        return json.loads(decrypt(json.loads(job[0])["encrypted"]))["body"]
    return decrypt(value["encrypted"]).decode()


def reveal_message(case_id, message_id, actor):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        value = record(db, "communications", case_id, message_id)
        current_body = message_body(db, value)
        versions = []
        prior_body = current_body
        for h in reversed(value["history"]):
            if h.get("encrypted"):
                prior_body = decrypt(h["encrypted"]).decode()
            versions.append(
                {**{k: v for k, v in h.items() if k != "encrypted"}, "body": prior_body}
            )
        result = {
            **message_meta(value),
            "body": current_body,
            "reference": value["reference"],
            "occurred_at": value["occurred_at"],
            "history": list(reversed(versions)),
        }
        audit_read(db, actor, "communication.reveal", message_id, case_id)
        return result


def list_customers(query=""):
    with connect() as db:
        return [
            {"id": r[0], "display_name": r[1], "revision": r[2]}
            for r in db.execute(
                "SELECT id,display_name,revision FROM agency_customers WHERE instr(lower(display_name),lower(?))>0 ORDER BY display_name,id LIMIT 100",
                (query,),
            )
        ]


def summary(case_id):
    with connect() as db:
        found = db.execute("SELECT * FROM trip_cases WHERE id=?", (case_id,)).fetchone()
        if not found:
            raise KeyError(case_id)
        linked = next(iter(rows(db, "customer_links", case_id)), None)
        return {
            "case_closed": found["status"] == "closed",
            "customer_link": {k: linked[k] for k in ("id", "customer_id", "revision")}
            if linked
            else None,
            "customer": customer_meta(get_customer(db, linked["customer_id"]))
            if linked
            else None,
            "communications": [
                message_meta(v) for v in rows(db, "communications", case_id)
            ][::-1],
        }


def customer_history(customer_id):
    with connect() as db:
        get_customer(db, customer_id)
        cases = [
            {"id": r[0], "customer_name": r[1], "destination": r[2], "status": r[3]}
            for r in db.execute(
                "SELECT c.id,c.customer_name,c.destination,c.status FROM trip_cases c LEFT JOIN agency_customer_links l ON l.case_id=c.id WHERE l.customer_id=? OR c.id IN (SELECT case_id FROM agency_communications WHERE customer_id=?) ORDER BY c.updated_at DESC LIMIT 100",
                (customer_id, customer_id),
            )
        ]
        messages = [
            {**message_meta(json.loads(r[1])), "case_id": r[0]}
            for r in db.execute(
                "SELECT case_id,payload_json FROM agency_communications WHERE customer_id=? ORDER BY created_at DESC,id DESC LIMIT 200",
                (customer_id,),
            )
        ]
        return {"cases": cases, "communications": messages}
