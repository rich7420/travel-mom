from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any

from app.config import settings

_lock = RLock()


@contextmanager
def connect():
    """Yield a configured SQLite connection and always close it.

    sqlite3.Connection's own context manager commits/rolls back but does not
    close the connection. The previous POC leaked connections during tests and
    long-running browser labs. This wrapper preserves transactional semantics
    and guarantees cleanup.
    """

    path = Path(settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        conn.close()


def _ensure_column(db: sqlite3.Connection, table: str, name: str, declaration: str) -> None:
    columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    if name not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def init_db() -> None:
    with _lock, connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              applied_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trip_cases (
              id TEXT PRIMARY KEY,
              customer_name TEXT NOT NULL,
              destination TEXT,
              origin TEXT,
              depart_date TEXT,
              return_date TEXT,
              adults INTEGER NOT NULL,
              children INTEGER NOT NULL,
              budget_twd INTEGER,
              notes TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS guided_sessions (
              session_id TEXT PRIMARY KEY,
              case_id TEXT,
              state_json TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS approvals (
              id TEXT PRIMARY KEY,
              case_id TEXT,
              action_type TEXT NOT NULL,
              summary TEXT NOT NULL,
              amount_twd INTEGER,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              decided_at TEXT
            );

            CREATE TABLE IF NOT EXISTS hotel_site_grants (
              id TEXT PRIMARY KEY,
              hotel_name TEXT NOT NULL,
              domain TEXT NOT NULL,
              official_url TEXT NOT NULL,
              trust_source TEXT NOT NULL,
              evidence_url TEXT,
              notes TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL,
              approved_at TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS hotel_search_runs (
              id TEXT PRIMARY KEY,
              case_id TEXT,
              request_json TEXT NOT NULL,
              task_ids_json TEXT NOT NULL,
              status TEXT NOT NULL,
              selected_task_id TEXT,
              selected_option_id TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS flight_search_runs (
              id TEXT PRIMARY KEY,
              case_id TEXT,
              request_json TEXT NOT NULL,
              task_ids_json TEXT NOT NULL,
              manual_handoffs_json TEXT NOT NULL,
              unsupported_airlines_json TEXT NOT NULL,
              status TEXT NOT NULL,
              selected_task_id TEXT,
              selected_option_id TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS browser_tasks (
              id TEXT PRIMARY KEY,
              case_id TEXT,
              search_run_id TEXT,
              parent_task_id TEXT,
              parent_option_id TEXT,
              kind TEXT NOT NULL,
              source_url TEXT NOT NULL,
              instructions TEXT NOT NULL,
              provider_code TEXT,
              expected_schema TEXT,
              status TEXT NOT NULL,
              result_text TEXT,
              result_json TEXT,
              review_state TEXT NOT NULL DEFAULT 'not_reviewed',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS browser_attempts (
              id TEXT PRIMARY KEY,
              task_id TEXT NOT NULL,
              attempt_no INTEGER NOT NULL,
              source TEXT NOT NULL,
              browser_profile TEXT NOT NULL,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              duration_ms INTEGER,
              outcome TEXT NOT NULL,
              result_status TEXT,
              validation_errors_json TEXT NOT NULL DEFAULT '[]',
              blocker TEXT,
              result_hash TEXT,
              created_at TEXT NOT NULL,
              UNIQUE(task_id, attempt_no)
            );

            CREATE TABLE IF NOT EXISTS inbound_events (
              channel TEXT NOT NULL,
              event_id TEXT NOT NULL,
              payload_hash TEXT NOT NULL,
              status TEXT NOT NULL,
              response_json TEXT,
              received_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY(channel, event_id)
            );

            CREATE TABLE IF NOT EXISTS audit_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              case_id TEXT,
              actor TEXT NOT NULL,
              action TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pii_vault (
              case_id TEXT PRIMARY KEY,
              encrypted_payload BLOB NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_preferences (
              profile_id TEXT PRIMARY KEY,
              default_origin TEXT NOT NULL,
              preferred_airlines_json TEXT NOT NULL,
              font_scale TEXT NOT NULL,
              simple_mode INTEGER NOT NULL,
              onboarding_complete INTEGER NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS skill_feedback (
              id TEXT PRIMARY KEY,
              skill_key TEXT NOT NULL,
              feedback_type TEXT NOT NULL,
              case_id TEXT,
              source TEXT NOT NULL,
              draft_redacted TEXT,
              final_redacted TEXT,
              note_redacted TEXT,
              skill_hash TEXT,
              edit_ratio REAL,
              possible_pii INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_browser_tasks_run ON browser_tasks(search_run_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_browser_tasks_parent ON browser_tasks(parent_task_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_browser_attempts_task ON browser_attempts(task_id, attempt_no);
            CREATE INDEX IF NOT EXISTS idx_inbound_events_status ON inbound_events(channel, status, updated_at);
            CREATE INDEX IF NOT EXISTS idx_search_runs_case ON flight_search_runs(case_id, created_at);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_hotel_site_grants_domain_status ON hotel_site_grants(domain, status);
            CREATE INDEX IF NOT EXISTS idx_hotel_search_runs_case ON hotel_search_runs(case_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_skill_feedback_skill ON skill_feedback(skill_key, created_at);
            CREATE INDEX IF NOT EXISTS idx_skill_feedback_case ON skill_feedback(case_id, created_at);

            CREATE TABLE IF NOT EXISTS agency_quotes (
              id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES trip_cases(id),
              version INTEGER NOT NULL, status TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
              UNIQUE(case_id, version)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_agency_accepted ON agency_quotes(case_id) WHERE status='accepted';
            CREATE TABLE IF NOT EXISTS agency_work_items (
              id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES trip_cases(id),
              status TEXT NOT NULL, due_at TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_agency_due ON agency_work_items(status,due_at);
            CREATE TABLE IF NOT EXISTS agency_bookings (
              id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES trip_cases(id),
              quote_id TEXT NOT NULL REFERENCES agency_quotes(id), kind TEXT NOT NULL, status TEXT NOT NULL,
              supplier_key TEXT NOT NULL, confirmation_key TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_agency_booking_reference ON agency_bookings(case_id,kind,supplier_key,confirmation_key) WHERE status='confirmed';
            CREATE TABLE IF NOT EXISTS agency_documents (
              id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES trip_cases(id), payload_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agency_ledger (
              id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES trip_cases(id), payload_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agency_pretrip (
              id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES trip_cases(id), version INTEGER NOT NULL,
              payload_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(case_id,version)
            );
            CREATE TABLE IF NOT EXISTS agency_case_events (
              id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES trip_cases(id),
              payload_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_agency_case_events ON agency_case_events(case_id,created_at);
            CREATE TRIGGER IF NOT EXISTS immutable_case_event_update BEFORE UPDATE ON agency_case_events
              BEGIN SELECT RAISE(ABORT,'case lifecycle events are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_case_event_delete BEFORE DELETE ON agency_case_events
              BEGIN SELECT RAISE(ABORT,'case lifecycle events are immutable'); END;

            CREATE TABLE IF NOT EXISTS agency_commands (
              case_id TEXT NOT NULL REFERENCES trip_cases(id), request_id TEXT NOT NULL,
              action TEXT NOT NULL, fingerprint TEXT NOT NULL, response_json TEXT NOT NULL, actor TEXT NOT NULL,
              created_at TEXT NOT NULL, PRIMARY KEY(case_id,request_id)
            );

            CREATE TABLE IF NOT EXISTS case_options (
              id TEXT PRIMARY KEY,
              case_id TEXT NOT NULL REFERENCES trip_cases(id),
              kind TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_case_options_case ON case_options(case_id, created_at);
            CREATE TABLE IF NOT EXISTS case_option_selections (
              case_id TEXT NOT NULL REFERENCES trip_cases(id),
              kind TEXT NOT NULL,
              option_id TEXT NOT NULL,
              snapshot_json TEXT NOT NULL,
              selected_at TEXT NOT NULL,
              PRIMARY KEY(case_id, kind)
            );
            """
        )
        # Upgrade v0.4/v0.5 databases in place.
        _ensure_column(db, "browser_tasks", "provider_code", "TEXT")
        _ensure_column(db, "browser_tasks", "expected_schema", "TEXT")
        _ensure_column(db, "browser_tasks", "result_json", "TEXT")
        _ensure_column(db, "browser_tasks", "review_state", "TEXT NOT NULL DEFAULT 'not_reviewed'")
        _ensure_column(db, "browser_tasks", "search_run_id", "TEXT")
        _ensure_column(db, "browser_tasks", "parent_task_id", "TEXT")
        _ensure_column(db, "browser_tasks", "parent_option_id", "TEXT")
        _ensure_column(db, "browser_tasks", "result_attempt_id", "TEXT")
        _ensure_column(db, "browser_attempts", "result_status", "TEXT")
        _ensure_column(db, "skill_feedback", "skill_hash", "TEXT")
        _ensure_column(db, "trip_cases", "infants", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(db, "trip_cases", "children_ages_json", "TEXT")
        db.execute(
            "INSERT OR IGNORE INTO schema_migrations(version,name,applied_at) VALUES(?,?,datetime('now'))",
            (701, "v0.7.1 reviewed hardening"),
        )
        db.execute(
            "INSERT OR IGNORE INTO schema_migrations(version,name,applied_at) VALUES(?,?,datetime('now'))",
            (801, "v0.8.1 Mom Mode unified UX and Skill feedback evidence"),
        )
        db.execute(
            "INSERT OR IGNORE INTO schema_migrations(version,name,applied_at) VALUES(?,?,datetime('now'))",
            (802, "Web case workflow and manual supplier options"),
        )
        db.execute(
            "INSERT OR IGNORE INTO schema_migrations(version,name,applied_at) VALUES(?,?,datetime('now'))",
            (803, "Manual agency operations: quotes, deadlines, confirmations, ledger and pretrip"),
        )
        db.execute(
            "INSERT OR IGNORE INTO schema_migrations(version,name,applied_at) VALUES(?,?,datetime('now'))",
            (804, "Explicit business close/reopen with immutable lifecycle events"),
        )
        db.commit()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def audit(case_id: str | None, actor: str, action: str, payload: dict[str, Any], created_at: str) -> None:
    with _lock, connect() as db:
        db.execute(
            "INSERT INTO audit_log(case_id,actor,action,payload_json,created_at) VALUES(?,?,?,?,?)",
            (case_id, actor, action, json.dumps(payload, ensure_ascii=False), created_at),
        )
        db.commit()
