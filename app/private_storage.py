"""Encryption inventory shared by backup and restore, including historical revisions.

Names and operational routing metadata remain searchable. These registered private
records keep bodies encrypted; the registry is not a claim of whole-file encryption.
"""

import json

PRIVATE_TABLES = (
    "agency_travellers",
    "agency_traveller_services",
    "agency_customers",
    "agency_communications",
    "agency_reminders",
    "agency_notification_jobs",
    "agency_attachments",
)
TOKEN_FIELDS = frozenset({"encrypted", "filename_encrypted"})


def tokens(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in TOKEN_FIELDS and child:
                yield child
            else:
                yield from tokens(child)
    elif isinstance(value, list):
        for child in value:
            yield from tokens(child)


def validate_private(db, cipher):
    tables = {
        r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for table in PRIVATE_TABLES:
        if table in tables:
            for row in db.execute(f"SELECT payload_json FROM {table}"):
                for token in tokens(json.loads(row[0])):
                    cipher.decrypt(token.encode())
    if "pii_vault" in tables:
        for row in db.execute("SELECT encrypted_payload FROM pii_vault"):
            cipher.decrypt(row[0].encode() if isinstance(row[0], str) else row[0])


def pause_after_restore(db):
    """A restored snapshot cannot replay accepted notifications or rearm future rules."""
    from uuid import uuid4
    from app.operations_repository import encode
    from app.models import now_iso, new_id

    tables = {
        r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "agency_notification_state" not in tables:
        return
    for row in list(db.execute("SELECT id,payload_json FROM agency_reminders")):
        rule = json.loads(row[1])
        rule.update(
            enabled=False, pause_reason="backup_restored", revision=rule["revision"] + 1
        )
        db.execute(
            "UPDATE agency_reminders SET enabled=0,payload_json=? WHERE id=?",
            (encode(rule), row[0]),
        )
    for row in list(
        db.execute(
            "SELECT id,attempt_no,status FROM agency_notification_jobs WHERE status IN ('queued','retry','dispatching','paused')"
        )
    ):
        state = "unknown" if row[2] == "dispatching" else "paused_after_restore"
        db.execute(
            "UPDATE agency_notification_jobs SET status=?,revision=revision+1,lease_until=NULL,lease_token=NULL WHERE id=?",
            (state, row[0]),
        )
        db.execute(
            "INSERT INTO agency_notification_attempts VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                new_id("attempt"),
                row[0],
                row[1],
                "restore",
                state,
                "backup-restore",
                "還原後暫停，需人工核對",
                None,
                None,
                now_iso(),
            ),
        )
    db.execute(
        "UPDATE agency_notification_state SET restore_epoch=?,acknowledged_epoch=?,last_tick_at=NULL,worker_instance=NULL WHERE id=1",
        (str(uuid4()), ""),
    )
