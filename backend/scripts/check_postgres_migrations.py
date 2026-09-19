"""Exercise fresh, legacy, concurrent, and repeatable PostgreSQL schema initialization."""

import os
import re
import secrets
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import create_engine, inspect, text

from app.db import Base
from app.migrations import initialize_schema
from app.models import Domain, RunStatus


def main():
    url = os.environ.get('SIGNOFF_POSTGRES_TEST_URL')
    if not url:
        raise SystemExit('SIGNOFF_POSTGRES_TEST_URL is required')
    schema = 'signoff_ci_' + secrets.token_hex(8)
    if re.fullmatch(r'[a-z0-9_]+', schema) is None:
        raise RuntimeError('invalid generated schema')
    administration = create_engine(url, pool_pre_ping=True)
    engine = None
    try:
        with administration.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'}, pool_pre_ping=True)
        with engine.begin() as connection:
            connection.execute(text("CREATE TYPE domain AS ENUM ('rtl', 'sta')"))
            connection.execute(text("CREATE TYPE runstatus AS ENUM ('running', 'passed', 'failed')"))
            connection.execute(text('''CREATE TABLE projects (
                id SERIAL PRIMARY KEY,
                name VARCHAR(120) UNIQUE NOT NULL,
                process_node VARCHAR(40) NOT NULL,
                foundry VARCHAR(60) NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL
            )'''))
            connection.execute(text("""INSERT INTO projects
                (name, process_node, foundry, created_at)
                VALUES ('legacy-project', '5nm', 'test-foundry', CURRENT_TIMESTAMP)"""))

        # Two startup workers must serialize the same legacy upgrade.
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(initialize_schema, engine) for _ in range(2)]
            for future in futures:
                future.result(timeout=120)
        initialize_schema(engine)

        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        expected_tables = set(Base.metadata.tables)
        if not expected_tables <= tables:
            raise RuntimeError(f'missing PostgreSQL tables: {sorted(expected_tables - tables)}')
        project_columns = {column['name'] for column in inspector.get_columns('projects')}
        for column in {'lifecycle_version', 'archived_at', 'archived_by_user_id',
                       'release_decision_chain_head_sha256'}:
            if column not in project_columns:
                raise RuntimeError(f'missing migrated projects.{column}')
        release_columns = {column['name'] for column in inspector.get_columns('signoff_release_decisions')}
        for column in {'gate_snapshot_sha256', 'chain_version', 'previous_decision_sha256',
                       'credential_confirmed_at', 'signature_version', 'signing_key_id',
                       'signing_public_key', 'decision_signature'}:
            if column not in release_columns:
                raise RuntimeError(f'missing migrated signoff_release_decisions.{column}')
        with engine.connect() as connection:
            def enum_values(name):
                return set(connection.execute(text('''
                    SELECT e.enumlabel FROM pg_enum e
                    JOIN pg_type t ON t.oid = e.enumtypid
                    JOIN pg_namespace n ON n.oid = t.typnamespace
                    WHERE n.nspname = current_schema() AND t.typname = :name
                '''), {'name': name}).scalars())
            if enum_values('domain') != {item.value for item in Domain}:
                raise RuntimeError('PostgreSQL domain enum migration is incomplete')
            if enum_values('runstatus') != {item.value for item in RunStatus}:
                raise RuntimeError('PostgreSQL runstatus enum migration is incomplete')
            legacy = connection.execute(text(
                "SELECT name, lifecycle_version FROM projects WHERE name='legacy-project'"
            )).one()
            if tuple(legacy) != ('legacy-project', 1):
                raise RuntimeError('legacy PostgreSQL project was not preserved')
            connection.execute(text("""INSERT INTO signoff_runs
                (project_id, domain, stage, tool, status, metrics, created_at)
                SELECT id, 'low_power', 'final', 'VC LP', 'incomplete', '{}'::json,
                       CURRENT_TIMESTAMP FROM projects WHERE name='legacy-project'"""))
            connection.commit()
        print(f'PostgreSQL migration verification passed in isolated schema {schema}')
    finally:
        if engine is not None:
            engine.dispose()
        with administration.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))
        administration.dispose()


if __name__ == '__main__':
    main()
