import logging
import re

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def test_request_ids_are_server_generated_and_unique(client):
    responses = [client.get('/health', headers={'X-Request-ID': 'untrusted-request-id'}) for _ in range(2)]
    assert all(response.status_code == 200 for response in responses)
    identifiers = [response.headers['x-request-id'] for response in responses]
    assert all(re.fullmatch('[a-f0-9]{32}', value) for value in identifiers)
    assert len(set(identifiers)) == 2
    assert client.get('/does-not-exist').headers.get('x-request-id')


def test_readiness_queries_db_but_health_does_not(client, monkeypatch, caplog):
    secret = 'private-db-password-and-design-data'
    def broken_session():
        raise RuntimeError(secret)
    monkeypatch.setattr('app.main.SessionLocal', broken_session)
    with caplog.at_level(logging.WARNING, logger='uvicorn.error.signoff'):
        response = client.get('/ready')
    assert response.status_code == 503
    assert response.json() == {'status': 'not_ready'}
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['retry-after'] == '5'
    assert client.get('/health').json() == {'status': 'ok'}
    assert response.headers['x-request-id'] in caplog.text
    assert secret not in response.text and secret not in caplog.text


def test_readiness_requires_application_tables(client, monkeypatch, tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'empty.db'))
    monkeypatch.setattr('app.main.SessionLocal', sessionmaker(bind=engine))
    try:
        assert client.get('/ready').status_code == 503
    finally:
        engine.dispose()


def test_ready_is_public_in_authenticated_mode_and_is_not_cached(client, monkeypatch):
    monkeypatch.setenv('SIGNOFF_AUTH_MODE', 'required')
    client.cookies.clear()
    response = client.get('/ready')
    assert response.status_code == 200 and response.json() == {'status': 'ready'}
    assert response.headers['cache-control'] == 'no-store'
    assert client.get('/projects').status_code == 401


def test_unexpected_error_has_matching_support_id_and_sanitized_log(client, monkeypatch, caplog):
    secret = 'do-not-expose-db-credentials'
    def fail(*args, **kwargs):
        raise RuntimeError(secret)
    monkeypatch.setattr(Session, 'scalars', fail)
    with caplog.at_level(logging.INFO, logger='uvicorn.error.signoff'):
        response = client.get('/projects?private_query=do-not-log-query', headers={'Authorization': 'Bearer do-not-log-token'})
    assert response.status_code == 500
    assert response.json() == {'detail': 'internal server error', 'request_id': response.headers['x-request-id']}
    assert response.headers['cache-control'] == 'no-store'
    records = '\n'.join(record.getMessage() for record in caplog.records if record.name == 'uvicorn.error.signoff')
    assert response.headers['x-request-id'] in records
    assert 'route=/projects' in records and 'status=500' in records
    assert all(value not in records + response.text for value in [secret, 'do-not-log-query', 'do-not-log-token'])


def test_expected_validation_error_keeps_status_and_request_id(client):
    response = client.post('/projects', json={})
    assert response.status_code == 422
    assert isinstance(response.json()['detail'], list)
    assert re.fullmatch('[a-f0-9]{32}', response.headers['x-request-id'])
