import json
import os
import sqlite3
import zipfile
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.backup import create_backup, verify_backup, restore_backup, main
from app.db import Base
from app.models import RunAgentReview, AccountSecurityEvent, User, Project, RunArtifact, SignoffRun, Violation, Waiver, ViolationEvent, RunEvidence


@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'source.db'
    engine = create_engine(f'sqlite:///{path}')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        project = Project(name='복구 검증', process_node='5nm', foundry='test')
        run = SignoffRun(project=project, domain='rtl', stage='rtl', tool='rtl-signoff-ladder', status='incomplete', metrics={'cells': 12})
        violation = Violation(run=run, check_name='lint', severity='warning', status='waived', version=4)
        user = User(username='backup-audit-user', password_hash='unused-backup-fixture')
        session.add_all([project, run, violation, user])
        session.flush()
        session.add_all([
            Waiver(violation=violation, reason='검토 완료', approved_by='reviewer'),
            ViolationEvent(violation_id=violation.id, from_status='open', to_status='waived', actor='reviewer', reason='검토 완료'),
            RunEvidence(run=run, source='rtl_ladder', source_text='module top; endmodule\n', design_revision='abc123', result={'verdict': 'incomplete'}),
            RunArtifact(run=run, kind='netlist', content_text='module top; endmodule\n',
                        sha256='0' * 64, byte_length=22),
            AccountSecurityEvent(subject_user_id=user.id, subject_username=user.username, actor_user_id=user.id,
                                 actor=user.username, source='api', action='other_sessions_revoked', revoked_sessions=2),
        ])
        for requester, user_id in [('local', None), (user.username, user.id)]:
            session.add(RunAgentReview(run_id=run.id, request_key=str(uuid.uuid4()), requester=requester,
                                      requester_user_id=user_id, role='a1_rtl', status='completed',
                                      input_snapshot={'run_id': run.id}, review_policy='saved policy',
                                      model_alias='sign-off', outcome={'available': True, 'review': 'saved review'}))
        session.commit()
    engine.dispose()
    return path


def rows(path):
    with sqlite3.connect(path) as db:
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        return {name: db.execute(f'SELECT * FROM "{name}" ORDER BY id').fetchall() for name, in tables}


def repack(path, change):
    with zipfile.ZipFile(path) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    change(contents)
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in contents.items():
            archive.writestr(name, data)


def test_roundtrip_includes_live_wal_and_all_evidence(database, tmp_path):
    backup, restored = tmp_path / 'backup.zip', tmp_path / 'restored.db'
    with sqlite3.connect(database) as writer:
        assert writer.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
        writer.execute("UPDATE projects SET name='WAL 최신 데이터'")
        writer.commit()
        assert os.path.getsize(str(database) + '-wal') > 0
        expected = rows(database)
        manifest = create_backup(database, backup)
        assert verify_backup(backup) == manifest
        assert restore_backup(backup, restored) == manifest
        assert rows(restored) == expected
    assert backup.stat().st_mode & 0o777 == 0o600
    assert restored.stat().st_mode & 0o777 == 0o600
    assert manifest['row_counts']['violation_events'] == 1
    assert manifest['row_counts']['account_security_events'] == 1
    assert manifest['row_counts']['run_artifacts'] == 1
    assert rows(restored)['violations'][0][-1] == 4


@pytest.mark.parametrize('suffix', ['', '-wal', '-shm', '-journal'])
def test_restore_never_overwrites(database, tmp_path, suffix):
    backup, restored = tmp_path / 'backup.zip', tmp_path / 'restored.db'
    create_backup(database, backup)
    protected = tmp_path / ('restored.db' + suffix)
    protected.write_bytes(b'keep me')
    with pytest.raises(FileExistsError):
        restore_backup(backup, restored)
    assert protected.read_bytes() == b'keep me'


def test_symlink_and_existing_archive_protected(database, tmp_path):
    backup = tmp_path / 'backup.zip'
    backup.symlink_to(tmp_path / 'missing')
    with pytest.raises(FileExistsError):
        create_backup(database, backup)
    backup.unlink()
    create_backup(database, backup)
    before = backup.read_bytes()
    with pytest.raises(FileExistsError):
        create_backup(database, backup)
    assert backup.read_bytes() == before


@pytest.mark.parametrize('kind', ['checksum', 'counts', 'schema', 'version', 'traversal', 'size'])
def test_reject_bad_archive_without_publishing(database, tmp_path, kind):
    backup, restored = tmp_path / 'backup.zip', tmp_path / 'restored.db'
    create_backup(database, backup)
    def change(contents):
        manifest = json.loads(contents['manifest.json'])
        if kind == 'checksum':
            contents['database.sqlite'] += b'broken'
            manifest['database_bytes'] += 6
        elif kind == 'counts':
            manifest['row_counts']['projects'] = 9
        elif kind == 'schema':
            manifest['schema_sha256'] = 'bad'
        elif kind == 'version':
            manifest['format_version'] = True
        elif kind == 'traversal':
            contents['../escaped'] = b'bad'
        else:
            manifest['database_bytes'] = 1
        contents['manifest.json'] = json.dumps(manifest)
    repack(backup, change)
    with pytest.raises(ValueError):
        restore_backup(backup, restored)
    assert not restored.exists()
    assert not (tmp_path / 'escaped').exists()


def test_orphans_rejected(database, tmp_path):
    with sqlite3.connect(database) as db:
        db.execute('UPDATE violations SET run_id=999')
    with pytest.raises(ValueError):
        create_backup(database, tmp_path / 'backup.zip')
    assert not (tmp_path / 'backup.zip').exists()


def test_missing_source_not_created(tmp_path):
    source = tmp_path / 'missing.db'
    with pytest.raises(sqlite3.Error):
        create_backup(source, tmp_path / 'backup.zip')
    assert not source.exists()


def test_foreign_database_rejected(tmp_path):
    source = tmp_path / 'foreign.db'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE unrelated(id INTEGER)')
    with pytest.raises(ValueError, match='not a Sign-off'):
        create_backup(source, tmp_path / 'backup.zip')


def test_cli_and_readonly_verification(database, tmp_path, capsys):
    backup = tmp_path / 'backup.zip'
    assert main(['create', '--database', str(database), '--output', str(backup)]) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'ok'
    before = backup.read_bytes()
    assert main(['verify', '--backup', str(backup)]) == 0
    assert backup.read_bytes() == before
    assert main(['restore', '--backup', str(backup), '--database', str(database)]) == 1
    assert 'new destination' in capsys.readouterr().err


def test_copy_timeout_leaves_no_archive(database, tmp_path):
    with pytest.raises(TimeoutError):
        create_backup(database, tmp_path / 'backup.zip', timeout=1e-12)
    assert not (tmp_path / 'backup.zip').exists()


def test_legacy_schema_preserved_without_migration(database, tmp_path):
    with sqlite3.connect(database) as db:
        db.execute('DROP TABLE violation_events')
        db.execute('DROP TABLE run_evidence')
        db.execute('ALTER TABLE violations DROP COLUMN version')
    expected = rows(database)
    backup, restored = tmp_path / 'backup.zip', tmp_path / 'restored.db'
    create_backup(database, backup)
    verify_backup(backup)
    restore_backup(backup, restored)
    assert rows(restored) == expected
    with sqlite3.connect(restored) as db:
        assert 'version' not in {row[1] for row in db.execute('PRAGMA table_info(violations)')}


def test_compressed_archive_rejected(database, tmp_path):
    backup = tmp_path / 'backup.zip'
    create_backup(database, backup)
    with zipfile.ZipFile(backup) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    with zipfile.ZipFile(backup, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    with pytest.raises(ValueError, match='compressed'):
        verify_backup(backup)


@pytest.mark.parametrize('field,value', [
    ('row_counts', {'projects': True}),
    ('row_counts', {'projects': 1.0}),
    ('row_counts', {'projects': -1}),
    ('row_counts', []),
    ('database_bytes', True),
    ('database_bytes', 0),
    ('database_sha256', 'g' * 64),
    ('schema_sha256', None),
    ('created_at', '2026-01-01T00:00:00'),
    ('created_at', 'invalid'),
    ('created_at', None),
])
def test_invalid_manifest_fields_rejected_before_database_copy(database, tmp_path, field, value, monkeypatch):
    backup, restored = tmp_path / 'backup.zip', tmp_path / 'restored.db'
    create_backup(database, backup)
    def change(contents):
        manifest = json.loads(contents['manifest.json'])
        if field == 'row_counts' and isinstance(value, dict):
            manifest[field].update(value)
        else:
            manifest[field] = value
        contents['manifest.json'] = json.dumps(manifest)
    repack(backup, change)
    def unexpected_copy(*args, **kwargs):
        pytest.fail('invalid manifest must be rejected before database extraction')
    monkeypatch.setattr('app.backup.shutil.copyfileobj', unexpected_copy)
    with pytest.raises(ValueError, match='backup manifest'):
        restore_backup(backup, restored)
    assert not restored.exists()


@pytest.mark.parametrize('kind', ['duplicate', 'nested_duplicate', 'nan', 'overflow', 'utf8', 'deep'])
def test_ambiguous_manifest_json_rejected_cleanly(database, tmp_path, capsys, kind):
    backup, restored = tmp_path / 'backup.zip', tmp_path / 'restored.db'
    create_backup(database, backup)
    def change(contents):
        raw = contents['manifest.json'].decode()
        if kind == 'duplicate':
            raw = raw.replace('"format_version": 1', '"format_version": 999, "format_version": 1')
        elif kind == 'nested_duplicate':
            raw = raw.replace('"projects": 1', '"projects": 999, "projects": 1')
        elif kind == 'nan':
            raw = raw[:-1] + ', "extra": NaN}'
        elif kind == 'overflow':
            raw = raw[:-1] + ', "extra": 1e400}'
        elif kind == 'deep':
            raw = '[' * 2000 + '0' + ']' * 2000
        contents['manifest.json'] = b'\xff' if kind == 'utf8' else raw.encode()
    repack(backup, change)
    assert main(['restore', '--backup', str(backup), '--database', str(restored)]) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert 'restore failed:' in captured.err
    assert not restored.exists()
