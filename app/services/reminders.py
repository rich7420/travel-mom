"""Explicit reminder policies and cancellation; dispatch lives in the durable worker."""

from datetime import datetime, timezone
import json
from uuid import uuid4

from app.config import settings
from app.customer_repository import get_customer
from app.db import connect
from app.models import now_iso, new_id
from app.operations_repository import (
    command,
    encode,
    fingerprint,
    new_record,
    record,
    rows,
    save,
)
from app.services.case_operations import require
from app.services.service_order_state import TERMINAL
from app.services.travel_files import cipher, decrypt, encrypt


def source(db, case_id, kind, source_id):
    table = "work_items" if kind == "work_item" else "service_orders"
    value = record(db, table, case_id, source_id)
    active = (
        value["status"] == "open"
        if kind == "work_item"
        else value["status"] not in TERMINAL
    )
    return value, active


def configured(channel):
    if channel == "line":
        return bool(
            settings.reminder_line_enabled
            and settings.line_channel_access_token
            and settings.line_allowed_user_ids
        )
    return bool(
        settings.reminder_smtp_enabled
        and settings.reminder_smtp_host
        and settings.reminder_smtp_from
        and settings.reminder_smtp_tls in {"ssl", "starttls"}
    )


def staff_recipients(channel):
    return (
        settings.line_allowed_user_ids
        if channel == "line"
        else (settings.reminder_staff_emails or settings.cloudflare_access_emails)
    )


def context(db, rule):
    case = db.execute(
        "SELECT status FROM trip_cases WHERE id=?", (rule["case_id"],)
    ).fetchone()
    require(case and case[0] != "closed", "案件已結案，提醒已暫停")
    value, active = source(db, rule["case_id"], rule["source_kind"], rule["source_id"])
    require(active, "待辦或工作單已結束，提醒已取消")
    require(value["owner"] == rule["source_owner"], "負責人已變更，請重新核對接收人")
    profile = None
    consent = None
    if rule["recipient_kind"] == "customer":
        link = next(iter(rows(db, "customer_links", rule["case_id"])), None)
        require(
            link and link["customer_id"] == rule["customer_id"],
            "案件的客戶關聯已變更，請重新設定提醒",
        )
        profile = get_customer(db, rule["customer_id"])
        consent = profile["consents"].get("email")
        require(
            profile["revision"] == rule["customer_revision"]
            and consent
            and (consent["granted"] or not rule["enabled"])
            and consent["revision"] == rule["consent_revision"],
            "客戶資料或 Email 接收同意已變更，提醒已暫停",
        )
    guard = {
        "kind": rule["source_kind"],
        "id": value["id"],
        "due_at": value["due_at"],
        "owner": value["owner"],
        "customer_revision": profile["revision"] if profile else None,
        "consent_revision": consent["revision"] if consent else None,
    }
    return value, fingerprint(guard), profile


def recipient(db, rule):
    value, guard, profile = context(db, rule)
    content = json.loads(decrypt(rule["encrypted"]))
    if profile:
        address = json.loads(decrypt(profile["encrypted"]))["email"]
        require(bool(address), "客戶尚無 Email 地址")
    else:
        address = content["recipient"]
        allowed = staff_recipients(rule["channel"])
        require(address in allowed, "接收人不在已設定的員工名單，請重新核對")
    return address, content["body"], value, guard


def cancel_jobs(db, rule_id, reason):
    timestamp = now_iso()
    jobs = list(
        db.execute(
            "SELECT id,attempt_no FROM agency_notification_jobs WHERE rule_id=? AND status IN ('queued','retry','paused','paused_after_restore')",
            (rule_id,),
        )
    )
    for job in jobs:
        db.execute(
            "UPDATE agency_notification_jobs SET status='cancelled',revision=revision+1,lease_token=NULL,lease_until=NULL WHERE id=?",
            (job[0],),
        )
        db.execute(
            "INSERT INTO agency_notification_attempts VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                new_id("attempt"),
                job[0],
                job[1],
                "cancel",
                "cancelled",
                "system",
                reason,
                None,
                None,
                timestamp,
            ),
        )


def cancel_invalid(db, case_id=None, customer_id=None):
    """Fast transaction hook. Claim-time rechecks also cover writers outside command()."""
    query = "SELECT payload_json FROM agency_reminders"
    params = ()
    if case_id:
        query += " WHERE case_id=?"
        params = (case_id,)
    elif customer_id:
        query += " WHERE customer_id=?"
        params = (customer_id,)
    for raw in list(db.execute(query, params)):
        rule = json.loads(raw[0])
        if not rule["enabled"]:
            cancel_jobs(db, rule["id"], "提醒已停用")
            continue
        try:
            value, guard, _ = context(db, rule)
        except (ValueError, KeyError) as exc:
            rule.update(
                enabled=False, pause_reason=str(exc), revision=rule["revision"] + 1
            )
            save(db, "reminders", rule)
            cancel_jobs(db, rule["id"], "案件、接收同意或負責人已變更")
            continue
        if rule.get("source_fingerprint") != guard:
            cancel_jobs(db, rule["id"], "期限已變更，舊排程取消")
            rule.update(
                source_fingerprint=guard,
                source_due_at=value["due_at"],
                source_revision=value["revision"],
                armed_at=now_iso(),
            )
            save(db, "reminders", rule)


def rule_meta(rule):
    fields = (
        "id",
        "revision",
        "source_kind",
        "source_id",
        "source_revision",
        "source_due_at",
        "channel",
        "recipient_kind",
        "customer_id",
        "customer_revision",
        "consent_revision",
        "offset_minutes",
        "repeat_hours",
        "enabled",
        "pause_reason",
        "armed_at",
        "created_at",
    )
    return {k: rule.get(k) for k in fields}


def write_rule(case_id, data, actor, rule_id=None):
    cipher()

    def execute(db, case):
        origin, active = source(db, case_id, data.source_kind, data.source_id)
        require(
            active and origin["revision"] == data.source_revision,
            "待辦或工作單已更新，請重新核對期限",
        )
        private_content = encode({"recipient": data.recipient, "body": data.body})
        if rule_id:
            value = record(db, "reminders", case_id, rule_id)
            require(
                value["revision"] == data.expected_revision,
                "提醒已更新，請重新開啟核對",
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
                    "enabled": value["enabled"],
                }
            )
            value["revision"] += 1
            cancel_jobs(db, rule_id, "提醒內容或接收人已變更")
        else:
            require(data.expected_revision is None, "新增提醒不需修訂標示")
            require(
                len(rows(db, "reminders", case_id)) < 200, "單一案件最多設定 200 項提醒"
            )
            value = new_record(case_id, "reminder", {"history": []})
        value.update(
            data.model_dump(
                mode="json",
                exclude={
                    "request_id",
                    "expected_revision",
                    "recipient",
                    "body",
                    "checked",
                },
            )
        )
        value.update(
            source_owner=origin["owner"],
            source_due_at=origin["due_at"],
            pause_reason=None,
            armed_at=now_iso(),
            encrypted=value.get("encrypted")
            if value.get("encrypted")
            and decrypt(value["encrypted"]).decode() == private_content
            else encrypt(private_content.encode()),
            actor=actor,
        )
        if data.enabled:
            require(
                configured(data.channel), "此通知通道尚未設定或啟用，請先保存停用的提醒"
            )
            recipient(db, value)
        _, guard, _ = context(db, value)
        value["source_fingerprint"] = guard
        save(db, "reminders", value)
        return rule_meta(value)

    return command(
        case_id,
        data,
        actor,
        f"reminder.{rule_id or 'new'}.write",
        execute,
        private=True,
    )


def reveal_rule(case_id, rule_id, actor):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        value = record(db, "reminders", case_id, rule_id)
        body = json.loads(decrypt(value["encrypted"]))
        db.execute(
            "INSERT INTO audit_log(case_id,actor,action,payload_json,created_at) VALUES(?,?,?,?,?)",
            (
                case_id,
                actor,
                "agency.reminder.reveal",
                encode({"record_id": rule_id}),
                now_iso(),
            ),
        )
        return {
            **value,
            **body,
            "encrypted": None,
            "history": [
                {k: v for k, v in h.items() if k != "encrypted"}
                for h in value["history"]
            ],
        }


def status():
    with connect() as db:
        state = dict(
            db.execute("SELECT * FROM agency_notification_state WHERE id=1").fetchone()
        )
    last = (
        datetime.fromisoformat(state["last_tick_at"]) if state["last_tick_at"] else None
    )
    return {
        "enabled": settings.reminders_enabled,
        "channels": {k: configured(k) for k in ("email", "line")},
        "staff_recipients": {k: list(staff_recipients(k)) for k in ("email", "line")},
        "last_tick_at": state["last_tick_at"],
        "worker_running": bool(
            last and 0 <= (datetime.now(timezone.utc) - last).total_seconds() < 180
        ),
        "restore_pending": state["restore_epoch"] != state["acknowledged_epoch"],
    }


def summary(case_id):
    with connect() as db:
        case = db.execute(
            "SELECT status FROM trip_cases WHERE id=?", (case_id,)
        ).fetchone()
        if not case:
            raise KeyError(case_id)
        jobs = [
            {
                k: r[k]
                for k in (
                    "id",
                    "rule_id",
                    "revision",
                    "channel",
                    "status",
                    "send_at",
                    "attempt_no",
                    "provider_request_id",
                )
            }
            for r in db.execute(
                "SELECT * FROM agency_notification_jobs WHERE case_id=? ORDER BY created_at DESC,id DESC LIMIT 200",
                (case_id,),
            )
        ]
        ids = {j["id"] for j in jobs}
        attempts = [
            dict(r)
            for r in db.execute(
                "SELECT a.* FROM agency_notification_attempts a JOIN agency_notification_jobs j ON j.id=a.job_id WHERE j.case_id=? ORDER BY a.created_at DESC LIMIT 400",
                (case_id,),
            )
            if r["job_id"] in ids
        ]
        return {
            "case_closed": case[0] == "closed",
            "rules": [rule_meta(v) for v in rows(db, "reminders", case_id)],
            "jobs": jobs,
            "attempts": attempts,
            "readiness": status(),
        }


def confirm_job(case_id, job_id, data, actor):
    from app.services.notification_worker import (
        LINE_RETRY_WINDOW,
        accepted_history,
        epoch_ready,
        event,
        get_job,
        job_meta,
    )

    cipher()

    def execute(db, case):
        job = get_job(db, case_id, job_id)
        require(
            job["revision"] == data.expected_revision
            and job["status"] in {"unknown", "failed"},
            "寄送狀態已更新，請重新核對",
        )
        now = datetime.now(timezone.utc)
        if data.decision == "retry":
            require(epoch_ready(db), "備份還原後的提醒尚未由管理員核對")
            rule = record(db, "reminders", case_id, job["rule_id"])
            require(
                rule["enabled"] and rule["revision"] == job["rule_revision"],
                "提醒已停用或變更，請重新設定",
            )
            require(
                settings.reminders_enabled and configured(job["channel"]),
                "此通知通道或自動提醒尚未啟用",
            )
            address, body, _, guard = recipient(db, rule)
            frozen = json.loads(decrypt(json.loads(job["payload_json"])["encrypted"]))
            require(
                guard == job["source_fingerprint"]
                and address == frozen["recipient"]
                and body == frozen["body"],
                "接收人、內容或期限已變更，請重新設定提醒",
            )
            key = job["retry_key"]
            if (
                job["channel"] == "line"
                and job["first_attempt_at"]
                and now - datetime.fromisoformat(job["first_attempt_at"])
                >= LINE_RETRY_WINDOW
            ):
                key = str(uuid4())
            db.execute(
                "UPDATE agency_notification_jobs SET status='retry',revision=revision+1,next_attempt_at=?,retry_key=?,first_attempt_at=?,attempt_no=0 WHERE id=?",
                (
                    now.isoformat(),
                    key,
                    now.isoformat()
                    if key != job["retry_key"]
                    else job["first_attempt_at"],
                    job_id,
                ),
            )
            event(
                db,
                job,
                "retry",
                actor,
                data.reference,
                kind="manual_retry",
                at=data.occurred_at,
            )
        else:
            state = "accepted" if data.decision == "accepted" else "cancelled"
            db.execute(
                "UPDATE agency_notification_jobs SET status=?,revision=revision+1,lease_token=NULL,lease_until=NULL WHERE id=?",
                (state, job_id),
            )
            event(
                db,
                job,
                state,
                actor,
                data.reference,
                kind="manual_confirmation",
                at=data.occurred_at,
            )
            if state == "accepted":
                accepted_history(db, job, actor, data.reference, data.occurred_at)
        return job_meta(get_job(db, case_id, job_id))

    # Confirmation of past contact can be recorded after closure; retry still checks the live source.
    return command(
        case_id,
        data,
        actor,
        f"crm.reminder.{job_id}.confirm",
        execute,
        private=True,
        allow_closed=True,
    )


def acknowledge_restore(data, actor):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        state = db.execute(
            "SELECT * FROM agency_notification_state WHERE id=1"
        ).fetchone()
        require(
            state["restore_epoch"] != state["acknowledged_epoch"],
            "目前沒有待核對的還原提醒",
        )
        db.execute(
            "UPDATE agency_notification_state SET acknowledged_epoch=restore_epoch WHERE id=1"
        )
        db.execute(
            "INSERT INTO audit_log(case_id,actor,action,payload_json,created_at) VALUES(?,?,?,?,?)",
            (
                None,
                actor,
                "agency.reminders.restore-acknowledged",
                encode(
                    {
                        "epoch": state["restore_epoch"],
                        "reference": data.reference,
                        "at": data.occurred_at.isoformat(),
                    }
                ),
                now_iso(),
            ),
        )
    return {"acknowledged": True, "rules_remain_paused": True}


def reveal_job(case_id, job_id, actor):
    """Audited reconciliation reads the actual frozen content, not the edited policy."""
    from app.services.notification_worker import get_job, job_meta

    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        job = get_job(db, case_id, job_id)
        frozen = json.loads(job["payload_json"])
        content = (
            json.loads(decrypt(frozen["encrypted"])) if frozen.get("encrypted") else {}
        )
        db.execute(
            "INSERT INTO audit_log(case_id,actor,action,payload_json,created_at) VALUES(?,?,?,?,?)",
            (
                case_id,
                actor,
                "agency.reminder-job.reveal",
                encode({"record_id": job_id}),
                now_iso(),
            ),
        )
        return {
            **job_meta(job),
            **content,
            "message_id": f"<{job_id}@travel-mom.local>",
        }
