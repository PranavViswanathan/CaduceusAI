import os
import sys
from unittest.mock import MagicMock

from cryptography.fernet import Fernet

# Must be set before any app module imports
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_patient.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-testing-must-be-long-enough")
os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())
os.environ.setdefault("INTERNAL_API_KEY", "test-internal-key")
os.environ["TESTING"] = "true"

# Add service root to sys.path so imports work from tests/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@pytest.fixture(scope="session")
def pwd_context():
    return _pwd_context


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def client(mock_db):
    from main import app
    from database import get_db

    app.dependency_overrides[get_db] = lambda: mock_db
    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc
    app.dependency_overrides.clear()


@pytest.fixture
def sample_patient(pwd_context):
    """A mock Patient ORM object."""
    import uuid
    from datetime import datetime
    p = MagicMock()
    p.id = uuid.uuid4()
    p.email = "test@example.com"
    p.name = "Test Patient"
    p.hashed_password = pwd_context.hash("password123")
    p.dob_encrypted = None
    p.sex = "other"
    p.phone = "555-1234"
    p.created_at = datetime.utcnow()
    return p


@pytest.fixture
def authed_client(mock_db, sample_patient):
    """Client with get_current_patient overridden to return sample_patient."""
    from main import app
    from database import get_db
    from auth import get_current_patient

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_patient] = lambda: sample_patient
    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc
    app.dependency_overrides.clear()
