from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from scripts.database_backup import snapshot
from test_case_operations import client, family
from app.db import connect


def source_copy(tmp_path):
    path = tmp_path/'source.db'
    with connect() as db, closing(sqlite3.connect(path)) as copy:
        db.backup(copy)
    return path


def test_backup_reads_committed_wal_and_restore_matches_app_data(client, tmp_path):
    case, _ = family(client)
    source = source_copy(tmp_path)
    with closing(sqlite3.connect(source)) as writer:
        assert writer.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
        writer.execute('UPDATE trip_cases SET notes=? WHERE id=?', ('WAL 已提交',case['id']))
        writer.commit()
        backup = tmp_path/'backup.db'
        result = snapshot(source, backup)
        assert result['schema_version'] == 807 and result['cases'] > 0
        assert backup.stat().st_mode & 0o777 == 0o600
        restored = tmp_path/'restored.db'
        snapshot(backup, restored)
        with closing(sqlite3.connect(restored)) as db:
            assert db.execute('SELECT notes FROM trip_cases WHERE id=?',(case['id'],)).fetchone()[0] == 'WAL 已提交'
            assert db.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
    assert not list(tmp_path.glob('.mom-snapshot-*'))


@pytest.mark.parametrize('suffix', ['', '-wal','-shm','-journal'])
def test_backup_refuses_targets_sidecars_and_dangling_symlinks(client, tmp_path, suffix):
    source=source_copy(tmp_path); target=tmp_path/'target.db'
    item=Path(str(target)+suffix); item.symlink_to(tmp_path/'missing')
    with pytest.raises(FileExistsError): snapshot(source,target)
    assert item.is_symlink() and not list(tmp_path.glob('.mom-snapshot-*'))


def test_backup_rejects_future_schema_corruption_and_foreign_keys_without_publishing(client, tmp_path):
    source=source_copy(tmp_path)
    with closing(sqlite3.connect(source)) as db:
        db.execute("INSERT INTO schema_migrations VALUES(999,'unknown','now')"); db.commit()
    with pytest.raises(ValueError,match='schema'): snapshot(source,tmp_path/'future.db')
    assert not (tmp_path/'future.db').exists()
    broken=tmp_path/'broken.db'; broken.write_bytes(b'not sqlite')
    with pytest.raises(sqlite3.DatabaseError): snapshot(broken,tmp_path/'bad.db')
    assert not (tmp_path/'bad.db').exists()
    with closing(sqlite3.connect(source)) as db:
        db.execute('DELETE FROM schema_migrations WHERE version=999')
        db.execute("INSERT INTO agency_case_events VALUES('orphan','missing','{}','now')"); db.commit()
    with pytest.raises(ValueError,match='foreign key'): snapshot(source,tmp_path/'orphan.db')
    assert not (tmp_path/'orphan.db').exists() and not list(tmp_path.glob('.mom-snapshot-*'))


def test_backup_supports_803_before_upgrade_and_no_overwrite_race(client, tmp_path, monkeypatch):
    import scripts.database_backup as module
    source=source_copy(tmp_path)
    with closing(sqlite3.connect(source)) as db:
        db.execute('DROP TABLE agency_case_events'); db.execute('DELETE FROM schema_migrations WHERE version>=804'); db.commit()
    assert snapshot(source,tmp_path/'old.db')['schema_version'] == 803
    target=tmp_path/'race.db'; real=module.os.link
    def race(src,dst):
        target.write_bytes(b'concurrent target')
        real(src,dst)
    monkeypatch.setattr(module.os,'link',race)
    with pytest.raises(FileExistsError): snapshot(source,target)
    assert target.read_bytes() == b'concurrent target'
    assert not list(tmp_path.glob('.mom-snapshot-*'))


def test_missing_source_same_source_and_missing_triggers_fail_cleanly(client,tmp_path):
    source=source_copy(tmp_path)
    with pytest.raises(FileNotFoundError):snapshot(tmp_path/'missing.db',tmp_path/'target.db')
    with pytest.raises(ValueError,match='differ'):snapshot(source,source)
    with closing(sqlite3.connect(source)) as db:
        db.execute('DROP TRIGGER immutable_case_event_update');db.commit()
    with pytest.raises(ValueError,match='triggers'):snapshot(source,tmp_path/'target.db')
    assert not (tmp_path/'target.db').exists()
