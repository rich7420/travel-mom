"""Bounded private traveller records and immutable encrypted original documents."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.db import connect
from app.models import now_iso
from app.operations_repository import command, encode, fingerprint, new_record, record, rows, save
from app.repositories import _case_from_row
from app.services.case_workflow import trip_snapshot
from app.services.case_operations import require

UPLOAD_LIMIT = 10 * 1024 * 1024
CASE_FILE_LIMIT = 100
CASE_BYTE_LIMIT = 200 * 1024 * 1024


def cipher() -> Fernet:
    try:
        return Fernet(settings.pii_fernet_key.encode())
    except (ValueError, TypeError) as exc:
        raise ValueError("請由管理員先設定有效的旅客資料加密金鑰") from exc


def encrypt(value: bytes) -> str:
    return cipher().encrypt(value).decode()


def decrypt(value: str | bytes) -> bytes:
    try:
        return cipher().decrypt(value.encode() if isinstance(value, str) else value)
    except InvalidToken as exc:
        raise ValueError("資料無法解密或已損壞，請由管理員檢查金鑰與備份") from exc


def files_dir() -> Path:
    return Path(settings.attachments_dir or str(Path(settings.db_path).parent / 'attachments')).absolute()


def private_dir(path: Path) -> Path:
    if path.is_symlink():
        raise ValueError("Private storage cannot be a symlink")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def blob_path(storage_id: str, root: Path | None = None) -> Path:
    import re
    if not re.fullmatch(r'[a-f0-9]{32}', storage_id):
        raise ValueError("Invalid private storage ID")
    value = (root or files_dir()) / (storage_id + '.fernet')
    if value.is_symlink():
        raise ValueError("Private file cannot be a symlink")
    return value


def roster_state_from(case, travellers, proofs) -> dict:
    active = [t for t in travellers if t['status'] == 'active']
    version = {'trip': trip_snapshot(case), 'travellers': [(t['id'], t['revision'], t['status']) for t in travellers]}
    state = fingerprint(version)
    proof = next(iter(proofs), None)
    counts = {category: sum(t['category'] == category for t in active) for category in ('adult', 'child', 'infant')}
    matches = counts == {'adult': case.adults, 'child': case.children, 'infant': case.infants}
    return {'used': bool(travellers), 'count': len(active), 'counts': counts, 'counts_match': matches,
            'expected_state': state, 'current': bool(proof and proof['expected_state'] == state and matches),
            'proof': proof}


def roster_state(db, case):
    return roster_state_from(case, rows(db, 'travellers', case.id), rows(db, 'rosters', case.id))

def traveller_write(case_id, data, actor, traveller_id=None):
    # Require usable crypto even on a retry; private fingerprints never hash low-entropy PII alone.
    cipher()
    def execute(db, case):
        payload = data.model_dump(mode='json', exclude={'request_id', 'expected_revision', 'category'})
        if traveller_id:
            value = record(db, 'travellers', case_id, traveller_id)
            require(value['status'] == 'active' and value['revision'] == data.expected_revision, '旅客資料已更新，請重新開啟核對')
            value['revision'] += 1
        else:
            require(data.expected_revision is None, '新增旅客不需修訂標示')
            require(len(rows(db, 'travellers', case_id)) < 100, '單一案件最多登錄 100 位旅客')
            value = new_record(case_id, 'traveller', {})
        value.update(category=data.category, status='active', encrypted=encrypt(encode(payload).encode()))
        save(db, 'travellers', value)
        return {key: value[key] for key in ('id', 'revision', 'status')}
    return command(case_id, data, actor, f'traveller.{traveller_id or "new"}.write', execute, private=True)


def verify_roster(case_id, data, actor):
    def execute(db, case):
        state = roster_state(db, case)
        require(state['used'] and state['counts_match'], '旅客人數與案件的大人、小孩、嬰兒人數不符，請先補齊或修正')
        require(state['expected_state'] == data.expected_state, '名冊或需求已變更，請重新核對')
        value = state['proof'] or new_record(case_id, 'roster', {})
        if state['proof']:
            value['revision'] += 1
        value.update(expected_state=state['expected_state'], reference=data.reference,
                     occurred_at=data.occurred_at.isoformat(), actor=actor)
        return save(db, 'rosters', value)
    return command(case_id, data, actor, 'roster.verify', execute)


def list_private(case_id):
    with connect() as db:
        found = db.execute('SELECT * FROM trip_cases WHERE id=?', (case_id,)).fetchone()
        if not found:
            raise KeyError(case_id)
        case = _case_from_row(found)
        # No decrypted content, filenames, DOB or passport fragments are delivered to summaries.
        travellers = [{k: t[k] for k in ('id', 'revision', 'status', 'category')} for t in rows(db, 'travellers', case_id)]
        attachments = [{k: a[k] for k in ('id', 'document_id', 'revision', 'status', 'media_type', 'size', 'created_at')} for a in rows(db, 'attachments', case_id)]
        from app.services.case_operations import pack_source_from, document_current
        from app.services.traveller_services import pack_state
        roster = roster_state(db, case)
        documents = rows(db, 'documents', case_id)
        quote = next((q for q in rows(db, 'quotes', case_id) if q['status'] == 'accepted'), None)
        services=pack_state(db,case)
        source = pack_source_from(case, quote, rows(db, 'bookings', case_id), documents, roster,traveller_services=services)
        for doc in documents:
            doc['needs_recheck'] = doc['status'] == 'ready' and not document_current(doc, source)
        return {'case_closed': case.status.value == 'closed', 'travellers': travellers,
                'roster': roster, 'attachments': attachments, 'documents': documents,'traveller_services':services,
                'bookings':[{k:b[k] for k in ('id','revision','kind','title','status')} for b in rows(db,'bookings',case_id)]}


def reveal_traveller(case_id, traveller_id, actor):
    import json
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        value = record(db, 'travellers', case_id, traveller_id)
        payload = json.loads(decrypt(value['encrypted']))
        db.execute('INSERT INTO audit_log(case_id,actor,action,payload_json,created_at) VALUES(?,?,?,?,?)',
                   (case_id, actor, 'agency.traveller.reveal', encode({'record_id': traveller_id}), now_iso()))
        return {**payload, 'category': value['category'], 'id': traveller_id, 'revision': value['revision']}


def valid_file(data, content):
    def file_check(condition, message):
        if not condition:
            raise ValueError(message)
    file_check(len(content) == data.size and 0 < len(content) <= UPLOAD_LIMIT, '檔案大小不符合限制')
    signatures = {'application/pdf': content.startswith(b'%PDF-'),
                  'image/jpeg': content.startswith(b'\xff\xd8\xff'),
                  'image/png': content.startswith(b'\x89PNG\r\n\x1a\n')}
    extensions = {'application/pdf': '.pdf', 'image/jpeg': ('.jpg', '.jpeg'), 'image/png': '.png'}
    file_check(signatures[data.media_type] and data.filename.lower().endswith(extensions[data.media_type]), '只接受檔名與內容相符的 PDF、JPEG 或 PNG')
    file_check(not any(ord(c) < 32 for c in data.filename) and '/' not in data.filename and '\\' not in data.filename, '檔名不可含路徑或控制字元')
    file_check(hashlib.sha256(content).hexdigest() == data.sha256, '檔案內容不符，請重新選擇')


def invalidate_document(db, doc, actor, reason):
    doc.setdefault('history', []).append({'at': now_iso(), 'actor': actor, 'reason': reason,
                                         'before': {'status': doc['status'], 'verification': doc.get('verification')}})
    doc.update(status='missing', verification=None, attachment_state=attachment_stamp(db, doc['case_id'], doc['id']))
    doc['revision'] += 1
    save(db, 'documents', doc)


def upload(case_id, document_id, data, content, actor):
    valid_file(data, content)
    cipher()
    def execute(db, case):
        import uuid
        doc = record(db, 'documents', case_id, document_id)
        require(doc['revision'] == data.expected_revision, '文件已更新，請重新開啟核對')
        existing = rows(db, 'attachments', case_id)
        require(len(existing) < CASE_FILE_LIMIT and sum(a['size'] for a in existing) + len(content) <= CASE_BYTE_LIMIT,
                '案件原件已達 100 份或 200 MB 上限，請由管理員處理儲存容量')
        root = private_dir(files_dir())
        require(shutil.disk_usage(root).free >= 64 * 1024 * 1024 + len(content) * 2, '儲存空間不足，請由管理員處理')
        storage_id = uuid.uuid4().hex
        target = blob_path(storage_id, root)
        token = cipher().encrypt(content)
        with target.open('xb') as handle:
            os.chmod(target, 0o600)
            handle.write(token)
            handle.flush()
            os.fsync(handle.fileno())
        with directory_handle(root):
            pass
        value = new_record(case_id, 'attachment', {'document_id': document_id, 'status': 'active',
            'storage_id': storage_id, 'filename_encrypted': encrypt(data.filename.encode()),
            'media_type': data.media_type, 'size': data.size, 'sha256': data.sha256})
        save(db, 'attachments', value)
        invalidate_document(db, doc, actor, '原件新增，需重新核對')
        return {'id': value['id'], 'revision': 1, 'document_revision': doc['revision'], 'status': 'active'}
    # command checks replay before execute, under one lock: retries never create another blob.
    return command(case_id, data, actor, f'attachment.{document_id}.upload', execute, private=True)


def archive(case_id, attachment_id, data, actor):
    def execute(db, case):
        value = record(db, 'attachments', case_id, attachment_id)
        require(value['revision'] == data.expected_revision and value['status'] == 'active', '原件已更新或已封存，請重新開啟')
        value.update(status='archived', revision=value['revision'] + 1,
                     archive={'reason': data.reason, 'actor': actor, 'reference': data.reference, 'occurred_at': data.occurred_at.isoformat()})
        save(db, 'attachments', value)
        invalidate_document(db, record(db, 'documents', case_id, value['document_id']), actor, '原件封存，需重新核對')
        return {k: value[k] for k in ('id', 'revision', 'status')}
    return command(case_id, data, actor, f'attachment.{attachment_id}.archive', execute)


def attachment_stamp(db, case_id, document_id):
    values = [a for a in rows(db, 'attachments', case_id) if a['document_id'] == document_id]
    return {'used': bool(values), 'active': sum(a['status'] == 'active' for a in values),
            'state': fingerprint([(a['id'], a['revision'], a['status']) for a in values])}


from contextlib import contextmanager


@contextmanager
def directory_handle(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
        yield
    finally:
        os.close(fd)


def bounded_blob(path):
    try:
        if path.stat().st_size > 14 * 1024 * 1024:
            raise ValueError('原件大小異常，請由管理員檢查備份')
        return path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError('原件遺失，請由管理員檢查備份') from exc


def download(case_id, attachment_id, actor):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        value = record(db, 'attachments', case_id, attachment_id)
        raw = decrypt(bounded_blob(blob_path(value['storage_id'])))
        require(len(raw) == value['size'] and hashlib.sha256(raw).hexdigest() == value['sha256'], '原件已損壞，請由管理員檢查備份')
        db.execute('INSERT INTO audit_log(case_id,actor,action,payload_json,created_at) VALUES(?,?,?,?,?)',
                   (case_id, actor, 'agency.attachment.download', encode({'record_id': attachment_id}), now_iso()))
        # Generated filename never leaks original traveller names into download history.
        extension = {'application/pdf': 'pdf', 'image/jpeg': 'jpg', 'image/png': 'png'}[value['media_type']]
        return raw, value['media_type'], attachment_id + '.' + extension


def upload_receipt(case_id, request_id, actor):
    with connect() as db:
        if not db.execute('SELECT 1 FROM trip_cases WHERE id=?', (case_id,)).fetchone():
            raise KeyError(case_id)
        value = db.execute("SELECT response_json FROM agency_commands WHERE case_id=? AND request_id=? AND actor=? AND action LIKE 'attachment.%.upload'", (case_id, str(request_id), actor)).fetchone()
        import json
        return {'committed': bool(value), 'result': json.loads(value[0]) if value else None}


def archive_traveller(case_id, traveller_id, data, actor):
    def execute(db, case):
        value = record(db, 'travellers', case_id, traveller_id)
        require(value['revision'] == data.expected_revision and value['status'] == 'active', '旅客已更新，請重新開啟')
        value.update(status='archived', revision=value['revision'] + 1)
        save(db, 'travellers', value)
        return {k: value[k] for k in ('id', 'revision', 'status')}
    return command(case_id, data, actor, f'traveller.{traveller_id}.archive', execute)
