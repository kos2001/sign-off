import pytest

from scripts.check_postgres_backup import client_command, postgres_environment, run_client


def test_postgres_environment_extracts_credentials_without_leaking_url(monkeypatch):
    monkeypatch.setenv('PGPASSWORD', 'old-password')
    environment, database = postgres_environment(
        'postgresql+psycopg://signoff:p%40ss@db.internal:5544/signoff?sslmode=require'
    )
    assert database == 'signoff'
    assert {key: environment[key] for key in (
        'PGHOST', 'PGPORT', 'PGUSER', 'PGPASSWORD', 'PGDATABASE', 'PGSSLMODE'
    )} == {
        'PGHOST': 'db.internal', 'PGPORT': '5544', 'PGUSER': 'signoff',
        'PGPASSWORD': 'p@ss', 'PGDATABASE': 'signoff', 'PGSSLMODE': 'require',
    }


def test_postgres_environment_rejects_non_postgres_and_unknown_options():
    with pytest.raises(ValueError, match='PostgreSQL'):
        postgres_environment('sqlite:///signoff.db')
    with pytest.raises(ValueError, match='unsupported'):
        postgres_environment('postgresql+psycopg://localhost/signoff?application_name=secret')


def test_container_client_requires_digest_and_passes_credentials_by_environment(monkeypatch):
    environment = {'PGHOST': '127.0.0.1', 'PGPASSWORD': 'private'}
    monkeypatch.setenv('SIGNOFF_POSTGRES_CLIENT_IMAGE', 'postgres:17-alpine')
    with pytest.raises(ValueError, match='sha256'):
        client_command('pg_dump', ['--format=custom'], environment)
    monkeypatch.setenv('SIGNOFF_POSTGRES_CLIENT_IMAGE', 'postgres:17-alpine@sha256:' + 'a' * 64)
    command = client_command('pg_dump', ['--format=custom'], environment)
    assert command[-2:] == ['pg_dump', '--format=custom']
    assert 'private' not in command
    assert command.count('PGPASSWORD') == 1


def test_container_client_can_use_a_host_visible_from_docker(monkeypatch):
    monkeypatch.setenv('SIGNOFF_POSTGRES_CLIENT_IMAGE', 'postgres:17@sha256:' + 'a' * 64)
    monkeypatch.setenv('SIGNOFF_POSTGRES_CLIENT_HOST', 'host.docker.internal')
    captured = {}
    def fake_run(command, **kwargs):
        captured.update(command=command, environment=kwargs['env'])
        return type('Result', (), {'returncode': 0, 'stderr': b''})()
    monkeypatch.setattr('scripts.check_postgres_backup.subprocess.run', fake_run)
    run_client('pg_dump', ['--version'], {'PGHOST': '127.0.0.1', 'PGDATABASE': 'signoff'})
    assert captured['environment']['PGHOST'] == 'host.docker.internal'
    assert 'host.docker.internal' not in captured['command']
