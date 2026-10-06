from contextlib import closing
from dataclasses import replace
import fcntl
import json
from pathlib import Path
import sqlite3

from cryptography.fernet import Fernet, InvalidToken
import pytest

from app.db import connect
from test_travel_files import client, crypto_settings, document, upload, traveller
from test_case_operations import family, post
from scripts.backup_bundle import backup, restore, status


def source_copy(tmp_path):
    path=tmp_path/'source.db'
    with connect() as db, closing(sqlite3.connect(path)) as copy:db.backup(copy)
    return path


def setup_source(client, crypto_settings, tmp_path):
    case,_=family(client);doc=document(client,case)
    assert upload(client,case,doc).status_code==200
    assert post(client,case,'travellers',traveller()).status_code==200
    # Fixed test DB is shared across tests; copy only this case's private rows for isolated files root.
    source=source_copy(tmp_path)
    with closing(sqlite3.connect(source)) as db:
        for table in ('agency_attachments','agency_travellers','agency_rosters'):
            db.execute(f'DELETE FROM {table} WHERE case_id<>?',(case['id'],))
        db.execute('DELETE FROM pii_vault')
        db.commit()
    return source


def test_encrypted_bundle_roundtrip_permissions_and_real_restored_rows(client,crypto_settings,tmp_path):
    source=setup_source(client,crypto_settings,tmp_path)
    result=backup(source=source)
    bundle=Path(result['bundle'])
    assert result['attachments']==1 and not (bundle/'plain.sqlite').exists()
    assert all(file.stat().st_mode & 0o777==0o600 for file in bundle.rglob('*') if file.is_file())
    assert b'PRIVATE-' not in (bundle/'database.fernet').read_bytes()
    restored=tmp_path/'restored.db';files=tmp_path/'restored-files'
    info=restore(bundle,restored,files,crypto_settings.pii_fernet_key)
    assert info['attachments']==1 and info['schema_version']==807
    with closing(sqlite3.connect(restored)) as db:
        row=json.loads(db.execute('SELECT payload_json FROM agency_travellers').fetchone()[0])
        assert b'PRIVATE-PASSPORT' in Fernet(crypto_settings.pii_fernet_key.encode()).decrypt(row['encrypted'])
    assert len(list(files.glob('*.fernet')))==1
    assert status()['last_success'] and not status()['running']
    with pytest.raises(FileExistsError):restore(bundle,restored,files,crypto_settings.pii_fernet_key)


def test_wrong_keys_corruption_missing_blobs_and_failure_keep_success(client,crypto_settings,tmp_path):
    source=setup_source(client,crypto_settings,tmp_path);result=backup(source=source)
    bundle=Path(result['bundle']);success=status()['last_success']
    with pytest.raises(ValueError,match='key differs'):backup(source=source,key=Fernet.generate_key().decode())
    assert status()['last_success']==success and status()['last_failure']
    with pytest.raises(InvalidToken):restore(bundle,tmp_path/'wrong.db',tmp_path/'wrong-files',Fernet.generate_key().decode())
    assert not (tmp_path/'wrong.db').exists()
    file=next(Path(crypto_settings.attachments_dir).glob('*.fernet'));file.unlink()
    with pytest.raises(ValueError,match='原件遺失'):backup(source=source)
    assert status()['last_success']==success
    encrypted=bundle/'database.fernet';encrypted.write_bytes(encrypted.read_bytes()+b'tampered')
    with pytest.raises(ValueError,match='checksum'):restore(bundle,tmp_path/'bad.db',tmp_path/'bad-files',crypto_settings.pii_fernet_key)
    assert not (tmp_path/'bad.db').exists() and not (tmp_path/'bad-files').exists()
    assert not list(Path(crypto_settings.backup_dir).glob('.bundle-*'))


def test_backup_lock_retention_and_report_only_orphans(client,crypto_settings,tmp_path):
    source=setup_source(client,crypto_settings,tmp_path)
    first=backup(source=source,retention=2)
    root=Path(crypto_settings.backup_dir);untouched=root/'unrelated';untouched.mkdir();(untouched/'keep').write_text('keep')
    with (root/'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert status()['running']
        with pytest.raises(ValueError,match='already running'):backup(source=source)
    for _ in range(3):backup(source=source,retention=2)
    assert len(list(root.glob('bundle-*')))==2 and (untouched/'keep').read_text()=='keep'
    assert not Path(first['bundle']).exists()


def test_restore_refuses_symlinks_and_sidecars(client,crypto_settings,tmp_path):
    source=setup_source(client,crypto_settings,tmp_path);bundle=Path(backup(source=source)['bundle'])
    target=tmp_path/'target.db';Path(str(target)+'-wal').symlink_to(tmp_path/'missing')
    with pytest.raises(FileExistsError):restore(bundle,target,tmp_path/'files-new',crypto_settings.pii_fernet_key)
    assert not target.exists()
    other=tmp_path/'other.db';files=tmp_path/'files-new';files.symlink_to(tmp_path/'missing-files')
    with pytest.raises(FileExistsError):restore(bundle,other,files,crypto_settings.pii_fernet_key)
    assert not other.exists()


def test_forced_kill_keeps_plaintext_outside_backup_root_and_next_run_cleans(client,crypto_settings,tmp_path):
    import os
    import subprocess
    import sys
    source=setup_source(client,crypto_settings,tmp_path)
    root=Path(crypto_settings.backup_dir);files=Path(crypto_settings.attachments_dir)
    code='''import os, signal, sys
from pathlib import Path
import scripts.backup_bundle as b
real=b.crypto
class KillBeforeEncrypt:
 def decrypt(self,token):return real().decrypt(token)
 def encrypt(self,data):os.kill(os.getpid(),signal.SIGKILL)
b.crypto=lambda key=None:KillBeforeEncrypt()
b.backup(source=Path(sys.argv[1]),attachments=Path(sys.argv[2]),root=Path(sys.argv[3]))
'''
    env={**os.environ,'PII_FERNET_KEY':crypto_settings.pii_fernet_key}
    result=subprocess.run([sys.executable,'-c',code,str(source),str(files),str(root)],env=env,capture_output=True)
    assert result.returncode==-9,result.stderr
    assert not list(root.rglob('*.sqlite')) and not list(root.glob('bundle-*'))
    work=list(source.parent.glob('.mom-backup-work-*/snapshot-*'))
    assert len(work)==1 and (work[0]/'plain.sqlite').exists()
    assert backup(source=source)['attachments']==1
    assert not list(source.parent.glob('.mom-backup-work-*/snapshot-*'))
    assert not list(root.glob('.bundle-*'))
