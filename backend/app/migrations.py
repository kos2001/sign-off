"""Additive startup migrations, serialized across application workers."""

from sqlalchemy import inspect, text

from .db import Base


def initialize_schema(engine):
    with engine.connect() as connection:
        try:
            if engine.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            elif engine.dialect.name == "postgresql":
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
            connection.commit()
        except Exception:
            connection.rollback()
            raise
