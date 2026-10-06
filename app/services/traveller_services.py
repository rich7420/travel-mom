"""Audited encrypted ticket and special-request bindings, separate from identity proof."""

import json

from app.db import connect
from app.models import now_iso
from app.operations_repository import command, encode, new_record, record, rows, save
from app.services.case_operations import require, trip_matches, snapshot
from app.services.travel_files import cipher, decrypt, encrypt


def metadata(value):
    return {
        k: value[k]
        for k in (
            "id",
            "revision",
            "status",
            "traveller_id",
            "booking_id",
            "traveller_revision",
            "booking_revision",
            "created_at",
        )
    }


def binding_current(case, value, travellers, bookings, quote):
    traveller = next((t for t in travellers if t["id"] == value["traveller_id"]), None)
    booking = next((b for b in bookings if b["id"] == value["booking_id"]), None)
    if not traveller or not booking:
        return False
    return bool(
        value["status"] == "active"
        and traveller["status"] == "active"
        and traveller["revision"] == value["traveller_revision"]
        and booking["status"] == "confirmed"
        and booking["revision"] == value["booking_revision"]
        and quote
        and booking["quote_id"] == quote["id"]
        and trip_matches(booking["case_snapshot"], snapshot(case))
    )


def pack_state(db, case):
    return pack_state_from(
        case,
        rows(db, "traveller_services", case.id),
        rows(db, "travellers", case.id),
        rows(db, "bookings", case.id),
        next(
            (q for q in rows(db, "quotes", case.id) if q["status"] == "accepted"), None
        ),
    )


def pack_state_from(case, values, travellers, bookings, quote):
    return [
        {
            **metadata(v),
            "current": binding_current(case, v, travellers, bookings, quote),
        }
        for v in values
    ]


def write(case_id, data, actor, service_id=None):
    cipher()

    def execute(db, case):
        private_content = encode(
            data.model_dump(
                mode="json",
                include={"ticket_number", "segment_label", "requests", "notes"},
            )
        )
        traveller = record(db, "travellers", case_id, data.traveller_id)
        booking = record(db, "bookings", case_id, data.booking_id)
        require(
            traveller["status"] == "active"
            and traveller["revision"] == data.traveller_revision,
            "旅客資料已變更，請重新核對",
        )
        require(
            booking["status"] == "confirmed"
            and booking["revision"] == data.booking_revision,
            "訂購確認已變更，請重新核對",
        )
        quote = next(
            (q for q in rows(db, "quotes", case_id) if q["status"] == "accepted"), None
        )
        require(
            quote
            and booking["quote_id"] == quote["id"]
            and trip_matches(booking["case_snapshot"], snapshot(case)),
            "請選此次旅行目前有效的訂購",
        )
        require(
            not data.ticket_number or booking["kind"] == "flight",
            "票號只適用機票；飯店可記錄房型與特殊需求",
        )
        if service_id:
            value = record(db, "traveller_services", case_id, service_id)
            require(
                value["status"] == "active"
                and value["revision"] == data.expected_revision,
                "票號或特殊需求已更新，請重新開啟核對",
            )
            value.setdefault("history", []).append(
                {
                    **(
                        {"encrypted": value["encrypted"]}
                        if decrypt(value["encrypted"]).decode() != private_content
                        else {}
                    ),
                    "actor": value["actor"],
                    "reference": value["reference"],
                    "at": value["occurred_at"],
                    "traveller_id": value["traveller_id"],
                    "booking_id": value["booking_id"],
                    "traveller_revision": value["traveller_revision"],
                    "booking_revision": value["booking_revision"],
                }
            )
            value["revision"] += 1
        else:
            require(data.expected_revision is None, "新增服務不需修訂標示")
            require(
                len(rows(db, "traveller_services", case_id)) < 500,
                "單一案件最多登錄 500 筆旅客服務",
            )
            value = new_record(case_id, "traveller_service", {"history": []})
        value.update(
            status="active",
            traveller_id=data.traveller_id,
            booking_id=data.booking_id,
            traveller_revision=data.traveller_revision,
            booking_revision=data.booking_revision,
            encrypted=value.get("encrypted")
            if value.get("encrypted")
            and decrypt(value["encrypted"]).decode() == private_content
            else encrypt(private_content.encode()),
            actor=actor,
            reference=data.reference,
            occurred_at=data.occurred_at.isoformat(),
        )
        save(db, "traveller_services", value)
        return metadata(value)

    return command(
        case_id,
        data,
        actor,
        f"traveller-service.{service_id or 'new'}.write",
        execute,
        private=True,
    )


def archive(case_id, service_id, data, actor):
    cipher()

    def execute(db, case):
        value = record(db, "traveller_services", case_id, service_id)
        require(
            value["status"] == "active" and value["revision"] == data.expected_revision,
            "服務紀錄已更新或封存，請重新核對",
        )
        value["revision"] += 1
        value.update(
            status="archived",
            archive={
                "actor": actor,
                "reference": data.reference,
                "at": data.occurred_at.isoformat(),
            },
        )
        save(db, "traveller_services", value)
        return metadata(value)

    return command(
        case_id,
        data,
        actor,
        f"traveller-service.{service_id}.archive",
        execute,
        private=True,
    )


def reveal(case_id, service_id, actor):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        value = record(db, "traveller_services", case_id, service_id)
        payload = json.loads(decrypt(value["encrypted"]))
        history = []
        prior = payload
        for item in reversed(value.get("history", [])):
            if item.get("encrypted"):
                prior = json.loads(decrypt(item["encrypted"]))
            history.append(
                {
                    **{k: v for k, v in item.items() if k != "encrypted"},
                    "content": prior,
                }
            )
        history.reverse()
        db.execute(
            "INSERT INTO audit_log(case_id,actor,action,payload_json,created_at) VALUES(?,?,?,?,?)",
            (
                case_id,
                actor,
                "agency.traveller-service.reveal",
                encode({"record_id": service_id}),
                now_iso(),
            ),
        )
        return {
            **metadata(value),
            **payload,
            "history": history,
            "reference": value["reference"],
            "occurred_at": value["occurred_at"],
        }
