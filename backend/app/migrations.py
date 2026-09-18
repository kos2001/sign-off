"""Additive startup migrations, serialized across application workers."""

from sqlalchemy import inspect, text

from .db import Base
from .models import Domain


def initialize_schema(engine):
    with engine.connect() as connection:
        try:
            if engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            elif engine.dialect.name == "postgresql":
                connection.execute(text("SELECT pg_advisory_xact_lock(738421905)"))
                # create_all does not extend an existing PostgreSQL enum. Add
                # newly shipped domains in their own committed transaction so
                # later startup work can use them immediately on every
                # supported PostgreSQL version.
                domain_type_exists = connection.execute(text(
                    "SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'domain')"
                )).scalar_one()
                if domain_type_exists:
                    for value in Domain:
                        literal = value.value.replace("'", "''")
                        connection.execute(text(f"ALTER TYPE domain ADD VALUE IF NOT EXISTS '{literal}'"))
                    connection.commit()
                    connection.execute(text("SELECT pg_advisory_xact_lock(738421905)"))
            Base.metadata.create_all(connection)
            # create_all skips indexes for tables that already exist. Upgrade
            # those tables under the same startup lock as schema additions.
            for table_name, index_name in [('auth_sessions', 'ix_auth_sessions_expiry_id'),
                                           ('login_buckets', 'ix_login_buckets_expiry_id')]:
                for index in Base.metadata.tables[table_name].indexes:
                    if index.name == index_name:
                        index.create(connection, checkfirst=True)
            columns = {column["name"] for column in inspect(connection).get_columns("violations")}
            if "version" not in columns:
                connection.execute(text("ALTER TABLE violations ADD COLUMN version INTEGER NOT NULL DEFAULT 1"))
            for table, column in [("violation_events", "actor_user_id"), ("waivers", "approved_user_id")]:
                columns = {item["name"] for item in inspect(connection).get_columns(table)}
                if column not in columns:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} INTEGER REFERENCES users(id)"))
            timestamp_type = "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME"
            for table, columns in {
                "waivers": {"design_revision": "VARCHAR(160)", "expires_at": timestamp_type},
                "violation_events": {"waiver_design_revision": "VARCHAR(160)", "waiver_expires_at": timestamp_type},
            }.items():
                existing = {item["name"] for item in inspect(connection).get_columns(table)}
                for column, definition in columns.items():
                    if column not in existing:
                        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
            release_columns = {item['name'] for item in inspect(connection).get_columns('signoff_release_decisions')}
            if 'gate_snapshot' not in release_columns:
                connection.execute(text('ALTER TABLE signoff_release_decisions ADD COLUMN gate_snapshot JSON'))
            if 'gate_snapshot_sha256' not in release_columns:
                connection.execute(text('ALTER TABLE signoff_release_decisions ADD COLUMN gate_snapshot_sha256 VARCHAR(64)'))
            if 'evidence_snapshot_sha256' not in release_columns:
                connection.execute(text('ALTER TABLE signoff_release_decisions ADD COLUMN evidence_snapshot_sha256 VARCHAR(64)'))
            if 'decision_sha256' not in release_columns:
                connection.execute(text('ALTER TABLE signoff_release_decisions ADD COLUMN decision_sha256 VARCHAR(64)'))
            batch_columns = {item["name"] for item in inspect(connection).get_columns("sta_batch_executions")}
            for column, definition in {
                "cancel_requested": "BOOLEAN NOT NULL DEFAULT 0",
                "worker_token": "VARCHAR(32)",
                "started_at": "DATETIME",
                "lease_expires_at": "INTEGER",
                "retry_of_batch_id": "INTEGER REFERENCES sta_batch_executions(id)",
                "retry_request_key": "VARCHAR(36)",
                "attempt": "INTEGER NOT NULL DEFAULT 1",
            }.items():
                if column not in batch_columns:
                    connection.execute(text(f"ALTER TABLE sta_batch_executions ADD COLUMN {column} {definition}"))
            for index in Base.metadata.tables['sta_batch_executions'].indexes:
                if index.name == 'ux_sta_batch_executions_retry_request_key':
                    index.create(connection, checkfirst=True)
            item_columns = {item["name"] for item in inspect(connection).get_columns("sta_batch_execution_items")}
            for column in ('started_at', 'finished_at'):
                if column not in item_columns:
                    connection.execute(text(f"ALTER TABLE sta_batch_execution_items ADD COLUMN {column} DATETIME"))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
