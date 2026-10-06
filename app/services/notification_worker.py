"""Durable, fenced reminder dispatch. Only this worker creates scheduled jobs."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
import time
from uuid import uuid4

from app.db import connect
from app.models import new_id
from app.operations_repository import encode, new_record, record, save
from app.services import outbound, reminders
from app.services.case_operations import BUSINESS_ZONE, require
from app.services.travel_files import decrypt, encrypt

LEASE_SECONDS = 300
LINE_RETRY_WINDOW = timedelta(hours=24, minutes=-5)
MAX_ATTEMPTS = 5


def moment(value=None):
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc)


def event(
    db,
    job,
    status,
    actor="reminder-worker",
    reference="",
    error=None,
    provider=None,
    kind="result",
    at=None,
):
    db.execute(
        "INSERT INTO agency_notification_attempts VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            new_id("attempt"),
            job["id"],
            job["attempt_no"],
            kind,
            status,
            actor,
            reference,
            provider,
            error,
            moment(at).isoformat(),
        ),
    )


def job_meta(job):
    return {
        k: job[k]
        for k in (
            "id",
            "rule_id",
            "revision",
            "channel",
            "status",
            "send_at",
            "attempt_no",
        )
    }


def get_job(db, case_id, job_id):
    row = db.execute(
        "SELECT * FROM agency_notification_jobs WHERE case_id=? AND id=?",
        (case_id, job_id),
    ).fetchone()
    if not row:
        raise KeyError(job_id)
    return dict(row)


def accepted_history(db, job, actor, reference, at):
    content = json.loads(job["payload_json"])
    if not content.get("customer_id") or content["recipient_kind"] != "customer":
        return
    previous = db.execute(
        "SELECT 1 FROM agency_communications WHERE case_id=? AND notification_job_id=?",
        (job["case_id"], job["id"]),
    ).fetchone()
    if previous:
        return
    value = new_record(
        job["case_id"],
        "communication",
        {
            "customer_id": content["customer_id"],
            "kind": "outgoing",
            "channel": job["channel"],
            "status": "provider_accepted",
            "owner": content["source_owner"],
            "followup_at": None,
            "service_order_id": content["source_id"]
            if content["source_kind"] == "service_order"
            else None,
            "corrects_id": None,
            "history": [],
            "actor": actor,
            "reference": reference,
            "occurred_at": at.isoformat(),
            "notification_job_id": job["id"],
        },
    )
    save(db, "communications", value)


def epoch_ready(db):
    state = db.execute(
        "SELECT restore_epoch,acknowledged_epoch FROM agency_notification_state WHERE id=1"
    ).fetchone()
    return state[0] == state[1]


def create_jobs(db, now):
    reminders.cancel_invalid(db)
    for raw in list(
        db.execute("SELECT payload_json FROM agency_reminders WHERE enabled=1")
    ):
        rule = json.loads(raw[0])
        # Flags off preserve the policy; re-enabling checks grace instead of replaying a backlog.
        if not reminders.settings.reminders_enabled or not reminders.configured(
            rule["channel"]
        ):
            continue
        try:
            address, body, source, guard = reminders.recipient(db, rule)
        except (ValueError, KeyError):
            continue
        first = datetime.fromisoformat(source["due_at"]) - timedelta(
            minutes=rule["offset_minutes"]
        )
        if first > now:
            continue
        local_first = first.astimezone(BUSINESS_ZONE)
        today = now.astimezone(BUSINESS_ZONE).date()
        if rule["repeat_hours"]:
            first_day = max(
                local_first.date(),
                datetime.fromisoformat(rule["armed_at"])
                .astimezone(BUSINESS_ZONE)
                .date(),
            )
            start = max(first_day, today - timedelta(days=30))
            days = [start + timedelta(days=i) for i in range((today - start).days + 1)]
            scheduled = [
                datetime.combine(day, local_first.timetz()).astimezone(timezone.utc)
                for day in days
            ]
        else:
            scheduled = [first]
        for send_at in scheduled:
            if send_at > now or send_at < datetime.fromisoformat(rule["armed_at"]):
                continue
            occurrence = send_at.astimezone(BUSINESS_ZONE).date().isoformat()
            if db.execute(
                "SELECT 1 FROM agency_notification_jobs WHERE rule_id=? AND occurrence_date=? AND ((rule_revision=? AND source_fingerprint=?) OR status IN ('accepted','dispatching','unknown'))",
                (rule["id"], occurrence, rule["revision"], guard),
            ).fetchone():
                continue
            status = (
                "queued"
                if now - send_at
                <= timedelta(minutes=reminders.settings.reminder_grace_minutes)
                else "missed"
            )
            payload = {
                **{
                    k: rule[k]
                    for k in (
                        "recipient_kind",
                        "source_kind",
                        "source_id",
                        "source_owner",
                    )
                },
                "customer_id": rule.get("customer_id")
                if rule["recipient_kind"] == "customer"
                else None,
            }
            if status == "queued":
                payload.update(
                    encrypted=encrypt(
                        encode({"recipient": address, "body": body}).encode()
                    ),
                    body_hash=hashlib.sha256(body.encode()).hexdigest(),
                )
            job_id = str(uuid4())
            cursor = db.execute(
                """INSERT OR IGNORE INTO agency_notification_jobs
                (id,rule_id,case_id,rule_revision,source_fingerprint,occurrence_date,channel,status,send_at,next_attempt_at,retry_key,payload_json,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    job_id,
                    rule["id"],
                    rule["case_id"],
                    rule["revision"],
                    guard,
                    occurrence,
                    rule["channel"],
                    status,
                    send_at.isoformat(),
                    send_at.isoformat(),
                    str(uuid4()),
                    encode(payload),
                    now.isoformat(),
                ),
            )
            if cursor.rowcount and status == "missed":
                event(
                    db,
                    {"id": job_id, "attempt_no": 0},
                    "missed",
                    error="schedule_missed",
                    kind="schedule",
                    at=now,
                )


def lease_expiry(db, now):
    for raw in list(
        db.execute(
            "SELECT * FROM agency_notification_jobs WHERE status='dispatching' AND lease_until<=?",
            (now.isoformat(),),
        )
    ):
        job = dict(raw)
        first = datetime.fromisoformat(job["first_attempt_at"])
        retry = (
            job["channel"] == "line"
            and now - first < LINE_RETRY_WINDOW
            and job["attempt_no"] < MAX_ATTEMPTS
        )
        state = "retry" if retry else "unknown"
        db.execute(
            "UPDATE agency_notification_jobs SET status=?,revision=revision+1,lease_until=NULL,lease_token=NULL,next_attempt_at=? WHERE id=?",
            (state, now.isoformat(), job["id"]),
        )
        event(db, job, state, error="lease_expired", at=now)


def claim(instance, now):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        state = db.execute(
            "SELECT * FROM agency_notification_state WHERE id=1"
        ).fetchone()
        if (
            state["worker_instance"]
            and state["worker_instance"] != instance
            and state["last_tick_at"]
            and datetime.fromisoformat(state["last_tick_at"]) > now
        ):
            return None, "clock_conflict"
        db.execute(
            "UPDATE agency_notification_state SET last_tick_at=?,worker_instance=? WHERE id=1",
            (now.isoformat(), instance),
        )
        if not epoch_ready(db):
            return None, "restore_paused"
        lease_expiry(db, now)
        create_jobs(db, now)
        channels = [
            channel
            for channel in ("email", "line")
            if reminders.settings.reminders_enabled and reminders.configured(channel)
        ]
        for raw in list(
            db.execute(
                "SELECT * FROM agency_notification_jobs WHERE status IN ('queued','retry')"
            )
        ):
            if raw["channel"] not in channels:
                db.execute(
                    "UPDATE agency_notification_jobs SET status='paused',revision=revision+1 WHERE id=?",
                    (raw["id"],),
                )
                event(db, dict(raw), "paused", kind="channel_pause", at=now)
        if not channels:
            return None, "idle"
        placeholders = ",".join("?" for _ in channels)
        for raw in list(
            db.execute(
                f"SELECT * FROM agency_notification_jobs WHERE status IN ('queued','retry','paused') AND channel IN ({placeholders}) AND next_attempt_at<=? ORDER BY send_at,id LIMIT 100",
                (*channels, now.isoformat()),
            )
        ):
            job = dict(raw)
            rule = record(db, "reminders", job["case_id"], job["rule_id"])
            try:
                require(
                    rule["enabled"] and rule["revision"] == job["rule_revision"],
                    "提醒已變更或停用",
                )
                address, body, _, guard = reminders.recipient(db, rule)
                require(guard == job["source_fingerprint"], "來源或接收人已變更")
                snapshot = json.loads(
                    decrypt(json.loads(job["payload_json"])["encrypted"])
                )
                require(
                    snapshot["recipient"] == address and snapshot["body"] == body,
                    "寄送內容已變更",
                )
            except (ValueError, KeyError):
                db.execute(
                    "UPDATE agency_notification_jobs SET status='cancelled',revision=revision+1 WHERE id=?",
                    (job["id"],),
                )
                event(db, job, "cancelled", error="source_changed", at=now)
                continue
            if (
                job["status"] == "paused"
                and not job["first_attempt_at"]
                and now - datetime.fromisoformat(job["send_at"])
                > timedelta(minutes=reminders.settings.reminder_grace_minutes)
            ):
                db.execute(
                    "UPDATE agency_notification_jobs SET status='missed',revision=revision+1 WHERE id=?",
                    (job["id"],),
                )
                event(db, job, "missed", error="schedule_missed", at=now)
                continue
            if (
                job["channel"] == "line"
                and job["first_attempt_at"]
                and now - datetime.fromisoformat(job["first_attempt_at"])
                >= LINE_RETRY_WINDOW
            ):
                db.execute(
                    "UPDATE agency_notification_jobs SET status='unknown',revision=revision+1 WHERE id=?",
                    (job["id"],),
                )
                event(db, job, "unknown", error="line_retry_window", at=now)
                continue
            token = str(uuid4())
            db.execute(
                "UPDATE agency_notification_jobs SET status='dispatching',revision=revision+1,lease_token=?,lease_until=?,attempt_no=attempt_no+1,first_attempt_at=coalesce(first_attempt_at,?) WHERE id=?",
                (
                    token,
                    (now + timedelta(seconds=LEASE_SECONDS)).isoformat(),
                    now.isoformat(),
                    job["id"],
                ),
            )
            job = dict(
                db.execute(
                    "SELECT * FROM agency_notification_jobs WHERE id=?", (job["id"],)
                ).fetchone()
            )
            event(db, job, "dispatching", kind="claim", at=now)
            return (job, snapshot), "claimed"
        return None, "idle"


def finish(job, result, now):
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        current = get_job(db, job["case_id"], job["id"])
        if (
            current["status"] != "dispatching"
            or current["lease_token"] != job["lease_token"]
            or datetime.fromisoformat(current["lease_until"]) <= now
        ):
            return False
        state = result.status
        if state == "retry" and current["attempt_no"] >= MAX_ATTEMPTS:
            state = "unknown" if current["channel"] == "line" else "failed"
        if (
            state == "retry"
            and current["channel"] == "line"
            and now - datetime.fromisoformat(current["first_attempt_at"])
            >= LINE_RETRY_WINDOW
        ):
            state = "unknown"
        delay = timedelta(seconds=min(3600, 60 * 2 ** min(current["attempt_no"], 5)))
        db.execute(
            "UPDATE agency_notification_jobs SET status=?,revision=revision+1,lease_token=NULL,lease_until=NULL,next_attempt_at=?,provider_request_id=? WHERE id=?",
            (
                state,
                (now + delay).isoformat(),
                result.provider_request_id,
                current["id"],
            ),
        )
        event(
            db,
            current,
            state,
            error=result.error_code,
            provider=result.provider_request_id,
            at=now,
        )
        if state == "accepted":
            accepted_history(
                db,
                current,
                "reminder-worker",
                result.provider_request_id or "通知通道受理",
                now,
            )
        return True


def tick_one(instance, now=None, send=outbound.send):
    injected = now is not None
    now = moment(now)
    try:
        claimed, state = claim(instance or str(uuid4()), now)
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            return {"status": "database_busy", "sent": 0}
        raise
    if not claimed:
        return {"status": state, "sent": 0}
    job, body = claimed
    # No database lock or connection is held during an external operation.
    try:
        result = send(
            job["channel"],
            body["recipient"],
            body["body"],
            job["retry_key"],
            f"<{job['id']}@travel-mom.local>",
        )
    except Exception:
        # An unexpected failure can occur after provider acceptance; preserve uncertainty.
        result = outbound.Delivery("unknown", "transport_unexpected")
    try:
        saved = finish(job, result, now if injected else moment())
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            return {"status": "result_not_recorded", "sent": 0}
        raise
    return {
        "status": result.status if saved else "lease_lost",
        "sent": int(saved and result.status == "accepted"),
    }


def tick(instance=None, now=None, send=outbound.send, *, max_jobs=50):
    """Drain a bounded batch without holding any lock between provider operations."""
    instance = instance or str(uuid4())
    deadline = time.monotonic() + 20
    sent = 0
    processed = 0
    last = {"status": "idle", "sent": 0}
    while processed < max_jobs and time.monotonic() < deadline:
        result = tick_one(instance, now, send)
        if result["status"] in {
            "idle",
            "restore_paused",
            "clock_conflict",
            "database_busy",
        }:
            if not processed:
                last = result
            break
        sent += result["sent"]
        processed += 1
        last = result
        if result["status"] in {"lease_lost", "result_not_recorded"}:
            break
    return {**last, "sent": sent, "processed": processed}
