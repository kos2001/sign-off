"""Probe real Docker readiness using a disposable database and no worker jobs."""
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
image = sys.argv[1] if len(sys.argv) > 1 else 'signoff-rtl-worker:local'

with tempfile.TemporaryDirectory(prefix='signoff-readiness-') as directory:
    os.environ.update(SIGNOFF_DATABASE_URL='sqlite:///' + str(Path(directory) / 'test.db'),
                      SIGNOFF_AUTH_MODE='local', SIGNOFF_RTL_REAPER_ENABLED='0',
                      SIGNOFF_RTL_EXECUTION='container',
                      SIGNOFF_RTL_WORKER_IMAGE='signoff-probe-missing:' + uuid.uuid4().hex)
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.db import engine
    try:
        with TestClient(create_app()) as client:
            assert client.get('/ready').status_code == 503
            assert client.get('/health').status_code == 200
            os.environ['SIGNOFF_RTL_WORKER_IMAGE'] = image
            assert client.get('/ready').status_code == 200
            previous = {key: os.environ.get(key) for key in ['DOCKER_HOST', 'DOCKER_CONTEXT']}
            os.environ.pop('DOCKER_CONTEXT', None)
            os.environ['DOCKER_HOST'] = 'unix://' + str(Path(directory) / 'absent-docker.sock')
            try:
                assert client.get('/ready').status_code == 503
                assert client.get('/health').status_code == 200
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
            assert client.get('/ready').status_code == 200
        print(json.dumps({'result': 'PASS', 'checks': ['missing image returns 503', 'valid image returns 200',
              'unreachable daemon returns 503', 'health remains available', 'configuration recovery returns 200']}))
    finally:
        engine.dispose()
