"""Tests for patient_api auth endpoints."""
from unittest.mock import MagicMock


def test_register_success(client, mock_db, pwd_context):
    mock_db.query.return_value.filter.return_value.first.return_value = None

    def _refresh(obj):
        import uuid
        obj.id = uuid.uuid4()

    mock_db.refresh.side_effect = _refresh

    resp = client.post("/v1/auth/register", json={
        "email": "new@example.com",
        "password": "securepass",
        "name": "New User",
        "dob": "1990-05-15",
        "sex": "female",
        "phone": "555-9876",
    })
    assert resp.status_code == 201
    assert "patient_id" in resp.json()


def test_register_duplicate_email(client, mock_db, sample_patient):
    mock_db.query.return_value.filter.return_value.first.return_value = sample_patient

    resp = client.post("/v1/auth/register", json={
        "email": "test@example.com",
        "password": "securepass",
        "name": "Another",
        "dob": "1990-05-15",
        "sex": "male",
        "phone": "555-0000",
    })
    assert resp.status_code == 400
    assert "already registered" in resp.json()["detail"].lower()


def test_register_password_too_short(client, mock_db):
    resp = client.post("/v1/auth/register", json={
        "email": "short@example.com",
        "password": "abc",
        "name": "User",
        "dob": "1990-05-15",
        "sex": "other",
        "phone": "555-0000",
    })
    assert resp.status_code == 422


def test_register_invalid_email(client, mock_db):
    resp = client.post("/v1/auth/register", json={
        "email": "not-an-email",
        "password": "securepass",
        "name": "User",
        "dob": "1990-05-15",
        "sex": "other",
        "phone": "555-0000",
    })
    assert resp.status_code == 422


def test_register_invalid_dob_format(client, mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = None
    resp = client.post("/v1/auth/register", json={
        "email": "user@example.com",
        "password": "securepass",
        "name": "User",
        "dob": "15/05/1990",  # Wrong format
        "sex": "other",
        "phone": "555-0000",
    })
    assert resp.status_code == 422


def test_register_invalid_sex(client, mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = None
    resp = client.post("/v1/auth/register", json={
        "email": "user@example.com",
        "password": "securepass",
        "name": "User",
        "dob": "1990-05-15",
        "sex": "unknown_value",
        "phone": "555-0000",
    })
    assert resp.status_code == 422


def test_login_success(client, mock_db, sample_patient):
    mock_db.query.return_value.filter.return_value.first.return_value = sample_patient

    resp = client.post("/v1/auth/token", data={
        "username": "test@example.com",
        "password": "password123",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "patient_id" in body
    assert body["token_type"] == "cookie"
    # TestClient (httpx) drops Secure cookies on HTTP; check the raw header instead
    assert "patient_access_token" in resp.headers.get("set-cookie", "")


def test_login_invalid_credentials(client, mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = None

    resp = client.post("/v1/auth/token", data={
        "username": "nobody@example.com",
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


def test_login_wrong_password(client, mock_db, sample_patient):
    mock_db.query.return_value.filter.return_value.first.return_value = sample_patient

    resp = client.post("/v1/auth/token", data={
        "username": "test@example.com",
        "password": "totally_wrong_password",
    })
    assert resp.status_code == 401


def test_logout(client):
    resp = client.post("/v1/auth/logout")
    assert resp.status_code == 200
    assert resp.json() == {"status": "logged out"}


def test_health_returns_status(client, mock_db):
    from sqlalchemy import text
    mock_db.execute.return_value = MagicMock()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert "status" in resp.json()
