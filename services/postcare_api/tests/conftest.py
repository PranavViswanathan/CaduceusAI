import os
import sys
from unittest.mock import MagicMock

from cryptography.fernet import Fernet

# Must be set before any app module imports
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_postcare.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-testing-must-be-long-enough")
os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("INTERNAL_API_KEY", "test-internal-key")
os.environ.setdefault("OLLAMA_URL", "http://localhost:11434")
os.environ["TESTING"] = "true"

# Add service root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from datetime import datetime, timedelta


def _make_token(role: str = "patient") -> str:
    from settings import settings
    payload = {
        "sub": "test-user-id",
        "role": role,
        "exp": datetime.utcnow() + timedelta(minutes=30),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def patient_token() -> str:
    return _make_token("patient")


@pytest.fixture
def doctor_token() -> str:
    return _make_token("doctor")


@pytest.fixture
def client(mock_db):
    from main import app
    from database import get_db

    app.dependency_overrides[get_db] = lambda: mock_db
    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc
    app.dependency_overrides.clear()


@pytest.fixture
def patient_client(mock_db, patient_token):
    """Client authenticated as a patient via Authorization Bearer header."""
    from main import app
    from database import get_db

    app.dependency_overrides[get_db] = lambda: mock_db
    with TestClient(app, raise_server_exceptions=False) as tc:
        tc.headers = {"Authorization": f"Bearer {patient_token}"}
        yield tc
    app.dependency_overrides.clear()


@pytest.fixture
def doctor_client(mock_db, doctor_token):
    """Client authenticated as a doctor via Authorization Bearer header."""
    from main import app
    from database import get_db

    app.dependency_overrides[get_db] = lambda: mock_db
    with TestClient(app, raise_server_exceptions=False) as tc:
        tc.headers = {"Authorization": f"Bearer {doctor_token}"}
        yield tc
    app.dependency_overrides.clear()
