"""Additive private customer/service records and durable notification dispatch."""


def install(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS agency_traveller_services (
          id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES trip_cases(id),
          traveller_id TEXT NOT NULL REFERENCES agency_travellers(id),
          booking_id TEXT NOT NULL REFERENCES agency_bookings(id),
          status TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_traveller_services_case ON agency_traveller_services(case_id,traveller_id,status);
        CREATE TABLE IF NOT EXISTS agency_customers (
          id TEXT PRIMARY KEY, display_name TEXT NOT NULL, revision INTEGER NOT NULL,
          payload_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS customer_commands (
          customer_id TEXT NOT NULL REFERENCES agency_customers(id), request_id TEXT NOT NULL,
          action TEXT NOT NULL, fingerprint TEXT NOT NULL, response_json TEXT NOT NULL,
          actor TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(customer_id,request_id)
        );
        CREATE TABLE IF NOT EXISTS agency_customer_links (
          id TEXT PRIMARY KEY, case_id TEXT NOT NULL UNIQUE REFERENCES trip_cases(id),
          customer_id TEXT NOT NULL REFERENCES agency_customers(id),
          payload_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_customer_links_customer ON agency_customer_links(customer_id);
        CREATE TABLE IF NOT EXISTS agency_communications (
          id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES trip_cases(id),
          customer_id TEXT NOT NULL REFERENCES agency_customers(id),
          status TEXT NOT NULL, notification_job_id TEXT UNIQUE REFERENCES agency_notification_jobs(id),
          payload_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_communications_customer ON agency_communications(customer_id,created_at);
        CREATE INDEX IF NOT EXISTS idx_communications_case ON agency_communications(case_id,created_at);
        CREATE TABLE IF NOT EXISTS agency_reminders (
          id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES trip_cases(id),
          source_kind TEXT NOT NULL, source_id TEXT NOT NULL, channel TEXT NOT NULL,
          customer_id TEXT REFERENCES agency_customers(id), enabled INTEGER NOT NULL DEFAULT 0,
          payload_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_reminders_source ON agency_reminders(case_id,source_kind,source_id);
        CREATE TABLE IF NOT EXISTS agency_notification_jobs (
          id TEXT PRIMARY KEY, rule_id TEXT NOT NULL REFERENCES agency_reminders(id),
          case_id TEXT NOT NULL REFERENCES trip_cases(id), rule_revision INTEGER NOT NULL,
          source_fingerprint TEXT NOT NULL, occurrence_date TEXT NOT NULL, channel TEXT NOT NULL,
          status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
          send_at TEXT NOT NULL, next_attempt_at TEXT NOT NULL,
          lease_until TEXT, lease_token TEXT, attempt_no INTEGER NOT NULL DEFAULT 0,
          first_attempt_at TEXT, retry_key TEXT NOT NULL, provider_request_id TEXT,
          payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
          UNIQUE(rule_id,rule_revision,source_fingerprint,occurrence_date)
        );
        CREATE TRIGGER IF NOT EXISTS immutable_notification_payload BEFORE UPDATE OF payload_json ON agency_notification_jobs
          WHEN NEW.payload_json != OLD.payload_json
          BEGIN SELECT RAISE(ABORT,'notification content is immutable'); END;
        CREATE INDEX IF NOT EXISTS idx_notification_claim ON agency_notification_jobs(next_attempt_at,send_at)
          WHERE status IN ('queued','retry');
        CREATE TABLE IF NOT EXISTS agency_notification_attempts (
          id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES agency_notification_jobs(id),
          attempt_no INTEGER NOT NULL, event TEXT NOT NULL, status TEXT NOT NULL,
          actor TEXT NOT NULL, reference TEXT NOT NULL DEFAULT '',
          provider_request_id TEXT, error_code TEXT, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_notification_attempt_job ON agency_notification_attempts(job_id,created_at);
        CREATE TRIGGER IF NOT EXISTS immutable_notification_attempt_update BEFORE UPDATE ON agency_notification_attempts
          BEGIN SELECT RAISE(ABORT,'notification attempts are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_notification_attempt_delete BEFORE DELETE ON agency_notification_attempts
          BEGIN SELECT RAISE(ABORT,'notification attempts are immutable'); END;
        CREATE TABLE IF NOT EXISTS agency_notification_state (
          id INTEGER PRIMARY KEY CHECK(id=1), restore_epoch TEXT NOT NULL DEFAULT '',
          acknowledged_epoch TEXT NOT NULL DEFAULT '', last_tick_at TEXT, worker_instance TEXT
        );
        INSERT OR IGNORE INTO agency_notification_state(id) VALUES(1);
    """)
