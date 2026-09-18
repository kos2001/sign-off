"""Destructively restore an isolated PostgreSQL schema and verify application data."""

import hashlib
import os
import re
import secrets
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base
from app.migrations import initialize_schema
from app.models import (
    Domain,
    Project,
    RunArtifact,
    RunEvidence,
    RunStatus,
    Severity,
    SignoffReleaseDecision,
    SignoffRun,
    Stage,
    Violation,
)

CLIENT_IMAGE_ENV = 'SIGNOFF_POSTGRES_CLIENT_IMAGE'
CLIENT_HOST_ENV = 'SIGNOFF_POSTGRES_CLIENT_HOST'


def postgres_environment(url: str) -> tuple[dict[str, str], str]:
    parsed = make_url(url)
    if parsed.get_backend_name() != 'postgresql' or not parsed.database:
        raise ValueError('SIGNOFF_POSTGRES_TEST_URL must be a PostgreSQL database URL')
    environment = os.environ.copy()
    values = {
        'PGHOST': parsed.host,
        'PGPORT': str(parsed.port) if parsed.port else None,
        'PGUSER': parsed.username,
        'PGPASSWORD': parsed.password,
        'PGDATABASE': parsed.database,
    }
    for key, value in values.items():
        if value is not None:
            environment[key] = value
        else:
            environment.pop(key, None)
    supported = {'sslmode': 'PGSSLMODE', 'sslrootcert': 'PGSSLROOTCERT'}
    unknown = set(parsed.query) - set(supported)
    if unknown:
        raise ValueError(f'unsupported PostgreSQL URL options: {sorted(unknown)}')
    for key, target in supported.items():
        value = parsed.query.get(key)
        if value is not None:
            environment[target] = str(value)
    return environment, parsed.database


def client_command(tool: str, arguments: list[str], environment: dict[str, str]) -> list[str]:
    image = os.environ.get(CLIENT_IMAGE_ENV)
    if not image:
        return [tool, *arguments]
    if re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}', image) is None:
        raise ValueError(f'{CLIENT_IMAGE_ENV} must pin the container image by sha256 digest')
    return [
        'docker', 'run', '--rm', '-i', '--network', 'host',
        *sum((['-e', key] for key in (
            'PGHOST', 'PGPORT', 'PGUSER', 'PGPASSWORD', 'PGDATABASE',
            'PGSSLMODE', 'PGSSLROOTCERT',
        ) if key in environment), []),
        image, tool, *arguments,
    ]


def run_client(tool: str, arguments: list[str], environment: dict[str, str], *,
               stdin=None, stdout=None):
    client_environment = environment.copy()
    client_host = os.environ.get(CLIENT_HOST_ENV)
    if client_host:
        if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,252}', client_host) is None:
            raise ValueError(f'{CLIENT_HOST_ENV} is invalid')
        client_environment['PGHOST'] = client_host
    command = client_command(tool, arguments, client_environment)
    try:
        result = subprocess.run(
            command, env=client_environment, stdin=stdin, stdout=stdout,
            stderr=subprocess.PIPE, timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f'{tool} did not complete') from error
    if result.returncode:
        detail = result.stderr.decode('utf-8', errors='replace')[-2000:]
        raise RuntimeError(f'{tool} failed: {detail}')


def seed(engine) -> dict:
    package = b'PK\x03\x04signoff-backup-drill\x00\xff'
    source = 'module chip; // 복구 검증\nendmodule\n'
    with Session(engine) as db:
        project = Project(name='backup-drill-chip', process_node='3nm', foundry='verification-foundry')
        run = SignoffRun(
            project=project, domain=Domain.sta, stage=Stage.final,
            tool='PrimeTime backup drill', status=RunStatus.incomplete,
            metrics={'wns_ps': -12.5, 'corners': ['ss_0p72v_125c'], 'complete': False},
        )
        run.evidence = RunEvidence(
            source='commercial_sta_report', source_text=source,
            source_sha256=hashlib.sha256(source.encode()).hexdigest(),
            design_revision='release/복구-r1', result={'metadata': {'scenario': 'func-ss'}},
        )
        run.artifacts.append(RunArtifact(
            kind='sdc', content_text='create_clock -period 1.0 [get_ports clk]\n',
            sha256='a' * 64, byte_length=43,
        ))
        run.violations.append(Violation(
            check_name='setup', severity=Severity.critical,
            location='u_core/reg[7]', description='negative slack',
        ))
        db.add(project)
        db.flush()
        decision = SignoffReleaseDecision(
            project_id=project.id, stage=Stage.final, decision='blocked',
            reason='backup drill evidence', design_revision='release/복구-r1',
            decided_by='backup-drill', gate_snapshot={'ready': False},
            gate_snapshot_sha256='b' * 64, evidence_snapshot_sha256='c' * 64,
            manifest={'format': 'signoff/package/v1', 'run_id': run.id},
            manifest_sha256='d' * 64, package_sha256=hashlib.sha256(package).hexdigest(),
            decision_sha256='e' * 64, chain_version=1,
            package_bytes=package, byte_length=len(package),
        )
        db.add(decision)
        db.commit()
        return {'project_id': project.id, 'run_id': run.id, 'package': package, 'source': source}


def counts(engine) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table.name: connection.scalar(select(text('count(*)')).select_from(table))
            for table in Base.metadata.sorted_tables
        }


def verify(engine, expected: dict, expected_counts: dict[str, int]):
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    required = set(Base.metadata.tables)
    if tables != required:
        raise RuntimeError(f'restored tables differ: missing={sorted(required - tables)}, extra={sorted(tables - required)}')
    for name, table in Base.metadata.tables.items():
        actual_columns = {column['name'] for column in inspector.get_columns(name)}
        expected_columns = set(table.columns.keys())
        if actual_columns != expected_columns:
            raise RuntimeError(f'restored columns differ for {name}')
    if counts(engine) != expected_counts:
        raise RuntimeError('restored table row counts differ')
    with Session(engine) as db:
        project = db.get(Project, expected['project_id'])
        run = db.get(SignoffRun, expected['run_id'])
        decision = db.scalar(select(SignoffReleaseDecision).where(
            SignoffReleaseDecision.project_id == expected['project_id']))
        if project is None or project.name != 'backup-drill-chip':
            raise RuntimeError('restored project differs')
        if run is None or run.metrics != {'wns_ps': -12.5, 'corners': ['ss_0p72v_125c'], 'complete': False}:
            raise RuntimeError('restored JSON metrics differ')
        if run.domain != Domain.sta or run.stage != Stage.final or run.status != RunStatus.incomplete:
            raise RuntimeError('restored enum values differ')
        if run.evidence is None or run.evidence.source_text != expected['source']:
            raise RuntimeError('restored Unicode evidence differs')
        if decision is None or decision.package_bytes != expected['package']:
            raise RuntimeError('restored binary release package differs')
        next_project = Project(name='post-restore-sequence-check', process_node='3nm', foundry='verification-foundry')
        db.add(next_project)
        db.flush()
        if next_project.id <= expected['project_id']:
            raise RuntimeError('restored project sequence did not advance')
        db.rollback()
        db.add(SignoffRun(
            project_id=2_000_000_000, domain=Domain.rtl, stage=Stage.rtl,
            tool='foreign-key-check', status=RunStatus.failed, metrics={},
        ))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise RuntimeError('restored foreign key constraint is not enforced')


def main():
    url = os.environ.get('SIGNOFF_POSTGRES_TEST_URL')
    if not url:
        raise SystemExit('SIGNOFF_POSTGRES_TEST_URL is required')
    environment, database = postgres_environment(url)
    schema = 'signoff_backup_ci_' + secrets.token_hex(8)
    if re.fullmatch(r'[a-z0-9_]+', schema) is None:
        raise RuntimeError('invalid generated schema')
    administration = create_engine(url, pool_pre_ping=True)
    engine = None
    try:
        with administration.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'}, pool_pre_ping=True)
        initialize_schema(engine)
        expected = seed(engine)
        expected_counts = counts(engine)
        with tempfile.TemporaryDirectory(prefix='signoff-postgres-backup-') as directory:
            archive = Path(directory) / 'signoff.dump'
            with archive.open('wb') as output:
                run_client('pg_dump', [
                    '--dbname', database, '--format=custom', '--compress=0',
                    '--no-owner', '--no-privileges', '--schema', schema,
                ], environment, stdout=output)
            if archive.stat().st_size == 0:
                raise RuntimeError('pg_dump produced an empty archive')
            engine.dispose()
            engine = None
            with administration.begin() as connection:
                connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            with archive.open('rb') as source:
                run_client('pg_restore', [
                    '--dbname', database, '--no-owner', '--no-privileges',
                    '--exit-on-error', '--single-transaction',
                ], environment, stdin=source)
        engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'}, pool_pre_ping=True)
        verify(engine, expected, expected_counts)
        print(f'PostgreSQL backup restore verification passed in isolated schema {schema}')
    finally:
        if engine is not None:
            engine.dispose()
        with administration.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))
        administration.dispose()


if __name__ == '__main__':
    main()
