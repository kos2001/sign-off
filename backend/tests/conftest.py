import os
import tempfile

import pytest

_fd, _db_path = tempfile.mkstemp(prefix="signoff_test_", suffix=".db")
os.close(_fd)
os.environ["SIGNOFF_DATABASE_URL"] = f"sqlite:///{_db_path}"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(create_app()) as c:
        yield c
    os.unlink(_db_path)
