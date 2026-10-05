"""Encrypted, locked, retained SQLite + immutable attachment backups.

Run with python -m scripts.backup_bundle run --env-file .env.
Restore is offline, exclusively to NEW database and NEW attachment directory.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import re
import time
import uuid

from cryptography.fernet import Fernet, InvalidToken
from app.config import settings
from scripts.database_backup import snapshot, validate
from app.services.travel_files import blob_path, private_dir, bounded_blob, directory_handle

MAX_DB_BYTES = 128 * 1024 * 1024
RETENTION = 14


def root_dir():
    return Path(settings.backup_dir or str(Path(settings.db_path).parent / 'backups')).absolute()


def now():
    return datetime.now(timezone.utc).isoformat()


def crypto(key=None):
    value = key if key is not None else settings.pii_fernet_key
    if not value:
        raise ValueError('Encryption key required; backup was not created')
    return Fernet(value.encode())


def key_id(key):
    return hmac.new(key.encode(), b'travel-mom-backup-key-id-v1', hashlib.sha256).hexdigest()


def atomic_json(path, value):
    fd, name = tempfile.mkstemp(prefix='.status-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def read_status(root):
    try:
        return json.loads((root / 'status.json').read_text())
    except FileNotFoundError:
        return {'last_success': None, 'last_failure': None}


def status():
    root = root_dir()
    state = read_status(root)
    running = False
    if (root / '.lock').is_file():
        with (root / '.lock').open('r') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                running = True
    # No paths, filenames or keys in the HTTP response.
    return {'running': running, 'last_success': state.get('last_success'),
            'last_failure': state.get('last_failure'), 'retention': RETENTION,
            'configured': bool(settings.pii_fernet_key), 'maintenance_warning': state.get('maintenance_warning')}


def backup(source=None, attachments=None, root=None, key=None, retention=RETENTION):
    source = Path(source or settings.db_path)
    attachments = Path(attachments or settings.attachments_dir or source.parent / 'attachments')
    root = private_dir(Path(root or root_dir()))
    key = key if key is not None else settings.pii_fernet_key
    with os.fdopen(os.open(root / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'a') as lock:
        os.chmod(root / '.lock', 0o600)
        for attempt in range(5):
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if attempt == 4:
                    raise ValueError('A backup is already running')
                time.sleep(.05)
        state = read_status(root)
        if source.absolute().is_relative_to(root.absolute()):
            raise ValueError('Backup root must not contain the live database')
        # Plain snapshots remain on the live DB volume, NEVER in the syncable backup root.
        work = private_dir(source.absolute().parent / ('.mom-backup-work-' + hashlib.sha256(str(root.absolute()).encode()).hexdigest()[:12]))
        for abandoned in root.glob('.bundle-*'):
            if re.fullmatch(r'\.bundle-[a-z0-9_]{8}', abandoned.name) and abandoned.is_dir() and not abandoned.is_symlink():
                shutil.rmtree(abandoned)
        for abandoned in work.glob('snapshot-*'):
            if re.fullmatch(r'snapshot-[a-z0-9_]{8}', abandoned.name) and abandoned.is_dir() and not abandoned.is_symlink():
                shutil.rmtree(abandoned)
        staging = Path(tempfile.mkdtemp(prefix='.bundle-', dir=root))
        plain_staging = Path(tempfile.mkdtemp(prefix='snapshot-', dir=work))
        try:
            cipher = crypto(key)
            expected_id = key_id(key)
            if state.get('key_id') and state['key_id'] != expected_id:
                raise ValueError('Backup key differs from previous successful backup')
            if source.stat().st_size > MAX_DB_BYTES:
                raise ValueError('Database exceeds 128 MB encrypted backup limit')
            if shutil.disk_usage(work).free < source.stat().st_size * 2 + 64 * 1024 * 1024:
                raise ValueError('Insufficient database-volume snapshot space')
            if shutil.disk_usage(root).free < source.stat().st_size * 4 + 64 * 1024 * 1024:
                raise ValueError('Insufficient backup space')
            info = snapshot(source, plain_staging / 'plain.sqlite')
            plain = plain_staging / 'plain.sqlite'
            if plain.stat().st_size > MAX_DB_BYTES:
                raise ValueError('Database exceeds 128 MB encrypted backup limit')
            encrypted = staging / 'database.fernet'
            encrypted.write_bytes(cipher.encrypt(plain.read_bytes()))
            os.chmod(encrypted, 0o600)
            blobs = private_dir(staging / 'attachments')
            inventory = []
            with closing(sqlite3.connect(plain)) as db:
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'agency_travellers' in tables:
                    for row in db.execute('SELECT payload_json FROM agency_travellers'):
                        cipher.decrypt(json.loads(row[0])['encrypted'].encode())
                for row in db.execute('SELECT encrypted_payload FROM pii_vault'):
                    cipher.decrypt(row[0].encode() if isinstance(row[0], str) else row[0])
                values = [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM agency_attachments')] if 'agency_attachments' in tables else []
            for record in values:
                source_blob = blob_path(record['storage_id'], attachments)
                token = bounded_blob(source_blob)
                cipher.decrypt(record['filename_encrypted'].encode())
                raw = cipher.decrypt(token)
                if len(raw) != record['size'] or hashlib.sha256(raw).hexdigest() != record['sha256']:
                    raise ValueError('Referenced attachment is corrupt')
                (blobs / source_blob.name).write_bytes(token)
                os.chmod(blobs / source_blob.name, 0o600)
                inventory.append({'storage_id': record['storage_id'], 'sha256_encrypted': hashlib.sha256(token).hexdigest()})
            plain.unlink()
            manifest = {'format': 1, 'completed_at': now(), 'key_id': expected_id, **info,
                        'database_sha256': hashlib.sha256(encrypted.read_bytes()).hexdigest(), 'attachments': inventory}
            # Encrypt manifest too: authenticated inventory and no case counts/IDs exposed at rest.
            (staging / 'manifest.fernet').write_bytes(cipher.encrypt(json.dumps(manifest).encode()))
            os.chmod(staging / 'manifest.fernet', 0o600)
            destination = root / ('bundle-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8])
            for file in staging.rglob('*'):
                if file.is_file():
                    with file.open('rb') as handle:
                        os.fsync(handle.fileno())
            os.rename(staging, destination)
            with directory_handle(root):
                pass
            state.pop('maintenance_warning', None)
            state.update(key_id=expected_id, last_success={'at': manifest['completed_at'], 'cases': info['cases'], 'attachments': len(inventory)})
            atomic_json(root / 'status.json', state)
            orphans = None
            try:
                # Only this tool's authenticated bundles are eligible for retention. Never arbitrary dirs.
                candidates = []
                for candidate in root.glob('bundle-*'):
                    if candidate.is_symlink() or not candidate.is_dir():
                        continue
                    try:
                        old = json.loads(cipher.decrypt((candidate / 'manifest.fernet').read_bytes()))
                        if old.get('format') == 1 and old.get('key_id') == expected_id:
                            candidates.append((old['completed_at'], candidate))
                    except (OSError, ValueError, InvalidToken):
                        continue
                for _, candidate in sorted(candidates, reverse=True)[max(1, retention):]:
                    if candidate != destination:
                        shutil.rmtree(candidate)
                referenced = {record['storage_id'] + '.fernet' for record in values}
                orphans = sum(file.name not in referenced and file.stat().st_mtime < datetime.now().timestamp() - 86400 for file in attachments.glob('*.fernet'))
            except (OSError, ValueError):
                state['maintenance_warning'] = {'at': now(), 'message': '備份已完成，但歷史清理或孤立檔案檢查失敗'}
                atomic_json(root / 'status.json', state)
            return {**info, 'attachments': len(inventory), 'orphans_older_than_24h': orphans, 'bundle': str(destination)}
        except Exception:
            # Bounded public failure description. Never leak filenames, key values or private records.
            state['last_failure'] = {'at': now(), 'message': '備份失敗，請由管理員檢查服務日誌、金鑰及儲存容量'}
            atomic_json(root / 'status.json', state)
            raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)
            shutil.rmtree(plain_staging)


def restore(bundle, database, attachments, key):
    bundle, database, attachments = Path(bundle), Path(database).absolute(), Path(attachments).absolute()
    for target in (database, attachments, *(Path(str(database) + suffix) for suffix in ('-wal', '-shm', '-journal'))):
        if os.path.lexists(target):
            raise FileExistsError('Restore targets must be new paths')
    if bundle.is_symlink():
        raise ValueError('Bundle cannot be a symlink')
    cipher = crypto(key)
    manifest = json.loads(cipher.decrypt((bundle / 'manifest.fernet').read_bytes()))
    if manifest.get('format') != 1 or manifest.get('key_id') != key_id(key):
        raise ValueError('Unsupported backup or wrong key')
    if (bundle / 'database.fernet').stat().st_size > 180 * 1024 * 1024:
        raise ValueError('Encrypted database exceeds supported size')
    encrypted = (bundle / 'database.fernet').read_bytes()
    if hashlib.sha256(encrypted).hexdigest() != manifest['database_sha256']:
        raise ValueError('Encrypted database checksum failed')
    staging = Path(tempfile.mkdtemp(prefix='.restore-', dir=database.parent))
    file_staging = Path(tempfile.mkdtemp(prefix='.restore-files-', dir=attachments.parent))
    published_db = False
    try:
        plain = cipher.decrypt(encrypted)
        if len(plain) > MAX_DB_BYTES:
            raise ValueError('Database exceeds supported backup size')
        working_db = staging / 'database.sqlite'
        working_db.write_bytes(plain)
        os.chmod(working_db, 0o600)
        with closing(sqlite3.connect(working_db)) as db:
            info = validate(db)
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            records = [json.loads(r[0]) for r in db.execute('SELECT payload_json FROM agency_attachments')] if 'agency_attachments' in tables else []
        inventory = {item['storage_id']: item for item in manifest['attachments']}
        if set(inventory) != {record['storage_id'] for record in records}:
            raise ValueError('Attachment inventory differs from database')
        for record in records:
            token = bounded_blob(blob_path(record['storage_id'], bundle / 'attachments'))
            if hashlib.sha256(token).hexdigest() != inventory[record['storage_id']]['sha256_encrypted']:
                raise ValueError('Encrypted attachment checksum failed')
            raw = cipher.decrypt(token)
            if len(raw) != record['size'] or hashlib.sha256(raw).hexdigest() != record['sha256']:
                raise ValueError('Restored attachment content differs from database')
            target = blob_path(record['storage_id'], file_staging)
            target.write_bytes(token)
            os.chmod(target, 0o600)
            with target.open('rb') as handle:
                os.fsync(handle.fileno())
        with working_db.open('rb') as handle:
            os.fsync(handle.fileno())
        os.link(working_db, database)  # refuses even a concurrently created destination
        published_db = True
        # mkdir refuses existing directories, including concurrently created ones.
        attachments.mkdir(mode=0o700)
        try:
            for file in file_staging.iterdir():
                os.link(file, attachments / file.name)
        except Exception:
            shutil.rmtree(attachments)
            raise
        for directory in (attachments, attachments.parent, database.parent):
            with directory_handle(directory):
                pass
        return {**info, 'attachments': len(records)}
    except Exception:
        if published_db:
            database.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(staging)
        shutil.rmtree(file_staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('run', 'status', 'restore'))
    parser.add_argument('--env-file')
    parser.add_argument('--bundle')
    parser.add_argument('--database')
    parser.add_argument('--attachments')
    args = parser.parse_args()
    if args.env_file:
        from dotenv import dotenv_values
        from dataclasses import replace
        global settings
        values = dotenv_values(args.env_file)
        settings = replace(settings, db_path=values.get('TRAVEL_DESK_DB') or settings.db_path,
                           pii_fernet_key=values.get('PII_FERNET_KEY') or settings.pii_fernet_key,
                           attachments_dir=values.get('ATTACHMENTS_DIR') or settings.attachments_dir,
                           backup_dir=values.get('BACKUP_DIR') or settings.backup_dir)
    if args.action == 'run':
        result = backup()
    elif args.action == 'status':
        result = status()
    else:
        if not all((args.bundle, args.database, args.attachments)):
            parser.error('Restore requires --bundle, --database and --attachments (new targets)')
        result = restore(args.bundle, args.database, args.attachments, settings.pii_fernet_key)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
