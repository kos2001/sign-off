"""SQLite online backups and verified restoration to a new database file.

No application imports: inspection and restoration never run schema migrations.
"""

import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timezone
import zipfile

FORMAT = 'signoff-hub-sqlite-backup'
REQUIRED_COLUMNS = {
    'projects': {'id', 'name', 'process_node', 'foundry', 'created_at'},
    'signoff_runs': {'id', 'project_id', 'domain', 'stage', 'tool', 'status', 'metrics', 'created_at'},
    'violations': {'id', 'run_id', 'check_name', 'severity', 'location', 'description', 'status'},
    'waivers': {'id', 'violation_id', 'reason', 'approved_by', 'created_at'},
}


def quote_identifier(value):
    return '"' + value.replace('"', '""') + '"'


def read_only(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=5)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_database(path):
    connection = read_only(path)
    try:
        if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('SQLite integrity check failed')
        if connection.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise ValueError('SQLite foreign key check failed')
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        for table, expected in REQUIRED_COLUMNS.items():
            if table not in tables:
                raise ValueError(f'not a Sign-off Hub database: missing table {table}')
            columns = {row[1] for row in connection.execute(f'PRAGMA table_info({quote_identifier(table)})')}
            if not expected.issubset(columns):
                raise ValueError(f'not a compatible Sign-off Hub database: missing columns in {table}')
        # Check references even in legacy SQLite schemas without FK enforcement.
        references = [('signoff_runs', 'project_id', 'projects'), ('violations', 'run_id', 'signoff_runs'), ('waivers', 'violation_id', 'violations')]
        references += [(table, column, target) for table, column, target in [
            ('run_agent_reviews', 'run_id', 'signoff_runs'),
            ('run_agent_reviews', 'requester_user_id', 'users'),
            ('violation_events', 'violation_id', 'violations'), ('run_evidence', 'run_id', 'signoff_runs'),
            ('run_artifacts', 'run_id', 'signoff_runs'),
            ('sta_batch_executions', 'project_id', 'projects'),
            ('sta_batch_executions', 'submitted_by_user_id', 'users'),
            ('sta_batch_execution_items', 'batch_id', 'sta_batch_executions'),
            ('sta_batch_execution_items', 'run_id', 'signoff_runs'),
        ] if table in tables]
        for child, column, parent in references:
            optional = f'c.{quote_identifier(column)} IS NOT NULL AND ' if (child, column) in {
                ('run_agent_reviews', 'requester_user_id'), ('sta_batch_executions', 'submitted_by_user_id'),
                ('sta_batch_execution_items', 'run_id'),
            } else ''
            orphan = connection.execute(
                f'SELECT 1 FROM {quote_identifier(child)} c LEFT JOIN {quote_identifier(parent)} p '
                f'ON c.{quote_identifier(column)} = p.id WHERE {optional}p.id IS NULL LIMIT 1'
            ).fetchone()
            if orphan:
                raise ValueError(f'database contains orphaned records in {child}')
        counts = {table: connection.execute(f'SELECT COUNT(*) FROM {quote_identifier(table)}').fetchone()[0] for table in tables}
        schema = connection.execute("SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name").fetchall()
        return {'row_counts': counts, 'schema_sha256': hashlib.sha256(json.dumps(schema, ensure_ascii=False).encode()).hexdigest()}
    finally:
        connection.close()


def publish(source, destination):
    """Atomic, no-clobber publication on the same filesystem."""
    os.chmod(source, 0o600)
    with open(source, 'rb') as file:
        os.fsync(file.fileno())
    os.link(source, destination)  # Fails if a file or symlink already exists.


def create_backup(database, output, timeout=120):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('timeout must be a positive finite number')
    output = Path(output).absolute()
    if os.path.lexists(output):
        raise FileExistsError('backup destination already exists')
    with tempfile.TemporaryDirectory(prefix='.signoff-backup-', dir=output.parent) as directory:
        snapshot = Path(directory) / 'database.sqlite'
        source = read_only(database)
        target = sqlite3.connect(snapshot)
        deadline = time.monotonic() + timeout
        def progress(status, remaining, total):
            if time.monotonic() > deadline:
                raise TimeoutError('backup deadline exceeded; no backup published')
        try:
            source.backup(target, pages=256, progress=progress, sleep=0.01)
        finally:
            target.close()
            source.close()
        manifest = {
            'format': FORMAT, 'format_version': 1,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'database_sha256': sha256(snapshot), 'database_bytes': snapshot.stat().st_size,
            **inspect_database(snapshot),
        }
        archive = Path(directory) / 'backup.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as bundle:
            bundle.write(snapshot, 'database.sqlite')
            bundle.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        publish(archive, output)
    return manifest


def parse_manifest(raw):
    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('backup manifest contains duplicate fields')
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError('backup manifest contains a non-finite number')

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            reject_constant(value)
        return number

    try:
        manifest = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_fields,
                              parse_constant=reject_constant, parse_float=finite_float)
    except (UnicodeError, RecursionError) as error:
        raise ValueError('backup manifest is not valid UTF-8 JSON') from error
    if not isinstance(manifest, dict) or manifest.get('format') != FORMAT or type(manifest.get('format_version')) is not int or manifest['format_version'] != 1:
        raise ValueError('unsupported backup format')
    size = manifest.get('database_bytes')
    if type(size) is not int or size <= 0:
        raise ValueError('backup manifest database_bytes must be a positive integer')
    for field in ['database_sha256', 'schema_sha256']:
        value = manifest.get(field)
        if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
            raise ValueError(f'backup manifest {field} must be a lowercase SHA-256 digest')
    counts = manifest.get('row_counts')
    if not isinstance(counts, dict) or not counts or any(
        not table or type(count) is not int or count < 0 for table, count in counts.items()
    ):
        raise ValueError('backup manifest row_counts must contain nonnegative integer counts')
    created = manifest.get('created_at')
    try:
        if not isinstance(created, str) or datetime.fromisoformat(created).utcoffset() is None:
            raise ValueError()
    except ValueError as error:
        raise ValueError('backup manifest created_at must include a valid timestamp and timezone') from error
    return manifest


def unpack_verified(backup, directory):
    snapshot = Path(directory) / 'database.sqlite'
    with zipfile.ZipFile(backup) as bundle:
        members = bundle.infolist()
        if len(members) != 2 or {item.filename for item in members} != {'database.sqlite', 'manifest.json'}:
            raise ValueError('backup must contain exactly database.sqlite and manifest.json')
        if any(item.compress_type != zipfile.ZIP_STORED or item.flag_bits & 1 for item in members):
            raise ValueError('compressed or encrypted backup members are not supported')
        if bundle.getinfo('manifest.json').file_size > 65536:
            raise ValueError('backup manifest is too large')
        manifest = parse_manifest(bundle.read('manifest.json'))
        size = manifest.get('database_bytes')
        if type(size) is not int or size != bundle.getinfo('database.sqlite').file_size:
            raise ValueError('database size does not match manifest')
        with bundle.open('database.sqlite') as source, open(snapshot, 'xb') as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
    if sha256(snapshot) != manifest.get('database_sha256'):
        raise ValueError('database checksum does not match manifest')
    inspected = inspect_database(snapshot)
    if inspected['row_counts'] != manifest.get('row_counts') or inspected['schema_sha256'] != manifest.get('schema_sha256'):
        raise ValueError('database schema or row counts do not match manifest')
    return snapshot, manifest


def verify_backup(backup):
    with tempfile.TemporaryDirectory(prefix='signoff-verify-') as directory:
        _, manifest = unpack_verified(backup, directory)
    return manifest


def restore_backup(backup, database):
    destination = Path(database).absolute()
    # Sidecars can belong to another database generation, even if its main file
    # has been moved. Never combine them with the restored snapshot.
    if any(os.path.lexists(str(destination) + suffix) for suffix in ['', '-wal', '-shm', '-journal']):
        raise FileExistsError('restore requires a new destination without SQLite sidecar files')
    with tempfile.TemporaryDirectory(prefix='.signoff-restore-', dir=destination.parent) as directory:
        snapshot, manifest = unpack_verified(backup, directory)
        publish(snapshot, destination)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description='Create, verify, or restore a Sign-off Hub SQLite backup')
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create', help='take an online SQLite snapshot')
    create.add_argument('--database', required=True, type=Path)
    create.add_argument('--output', required=True, type=Path)
    create.add_argument('--timeout', type=float, default=120)
    verify = commands.add_parser('verify', help='verify checksums, integrity, schema and row counts')
    verify.add_argument('--backup', required=True, type=Path)
    restore = commands.add_parser('restore', help='restore into a NEW database path')
    restore.add_argument('--backup', required=True, type=Path)
    restore.add_argument('--database', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'create':
            manifest = create_backup(args.database, args.output, args.timeout)
        elif args.command == 'verify':
            manifest = verify_backup(args.backup)
        else:
            manifest = restore_backup(args.backup, args.database)
    except (OSError, ValueError, sqlite3.Error, zipfile.BadZipFile, RuntimeError) as error:
        print(f'{args.command} failed: {error}', file=sys.stderr)
        return 1
    print(json.dumps({'operation': args.command, 'status': 'ok', 'manifest': manifest}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
