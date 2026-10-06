"""Create or restore a validated SQLite snapshot into a NEW file.

Usage: python scripts/database_backup.py backup SOURCE TARGET
       python scripts/database_backup.py restore SNAPSHOT NEW_TARGET
Stop the app before switching its configured database to a restored file.
Both operations refuse existing targets and sidecars, including dangling symlinks.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile


REQUIRED_TABLES = {'trip_cases', 'case_options', 'case_option_selections', 'audit_log',
                   'agency_quotes', 'agency_work_items', 'agency_bookings', 'agency_ledger',
                   'agency_documents', 'agency_pretrip', 'agency_commands'}


def validate(db: sqlite3.Connection) -> dict:
    if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise ValueError('SQLite integrity check failed')
    if db.execute('PRAGMA foreign_key_check').fetchone():
        raise ValueError('SQLite foreign key check failed')
    version = db.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
    if version not in {803, 804, 805, 806, 807}:
        raise ValueError(f'Unsupported schema version: {version}; expected 803 through 807')
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required = REQUIRED_TABLES | ({'agency_case_events'} if version >= 804 else set())
    if version >= 805:
        required |= {'agency_travellers', 'agency_rosters', 'agency_attachments'}
    if version >= 806:
        required.add('agency_service_orders')
    if version >= 807:
        required |= {'agency_traveller_services','agency_customers','customer_commands','agency_customer_links',
                     'agency_communications','agency_reminders','agency_notification_jobs',
                     'agency_notification_attempts','agency_notification_state'}
        triggers = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        if not {'immutable_notification_attempt_update','immutable_notification_attempt_delete','immutable_notification_payload'} <= triggers:
            raise ValueError('Snapshot is missing notification immutability triggers')
        if db.execute('SELECT COUNT(*) FROM agency_notification_state WHERE id=1').fetchone()[0] != 1:
            raise ValueError('Snapshot is missing notification state')
    if not required <= tables:
        raise ValueError('Snapshot is missing required application tables')
    if version >= 804:
        triggers = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='agency_case_events'")}
        if not {'immutable_case_event_update','immutable_case_event_delete'} <= triggers:
            raise ValueError('Snapshot is missing lifecycle immutability triggers')
    return {'schema_version': version, 'cases': db.execute('SELECT COUNT(*) FROM trip_cases').fetchone()[0]}


def snapshot(source: Path | str, target: Path | str, *, restored=False) -> dict:
    source, target = Path(source).resolve(strict=True), Path(target).absolute()
    if not source.is_file():
        raise ValueError('Source must be a regular SQLite database')
    if target.resolve() == source:
        raise ValueError('Source and target must differ')
    def refuse_existing():
        for item in (target, *(Path(str(target)+suffix) for suffix in ('-wal', '-shm', '-journal'))):
            if os.path.lexists(item):
                raise FileExistsError(f'Refusing existing target or sidecar: {item}')
    refuse_existing()
    # Do not create directories automatically: the operator chooses the backup location.
    fd, temp_name = tempfile.mkstemp(prefix='.mom-snapshot-', dir=target.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)) as original, closing(sqlite3.connect(temp)) as copy:
            original.backup(copy)
            copy.execute('PRAGMA journal_mode=DELETE')
            result = validate(copy)
            if restored:
                from app.private_storage import pause_after_restore
                pause_after_restore(copy)
                copy.commit()
                validate(copy)
        with temp.open('rb') as handle:
            os.fsync(handle.fileno())
        refuse_existing()
        # Atomic publication without replacement; fails if another process created the target.
        os.link(temp, target)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return {**result, 'target': str(target), 'bytes': target.stat().st_size}
    finally:
        temp.unlink(missing_ok=True)
        for suffix in ('-wal', '-shm', '-journal'):
            Path(str(temp)+suffix).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('backup', 'restore'))
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    args = parser.parse_args()
    import json
    print(json.dumps({'action': args.action, **snapshot(args.source, args.target, restored=args.action=='restore')}))


if __name__ == '__main__':
    main()
