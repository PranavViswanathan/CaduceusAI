"""Tests for doctor_api auth endpoints."""


def test_register_doctor_success(client, mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = None
    import uuid
    mock_db.refresh.side_effect = lambda obj: setattr(obj, "id", uuid.uuid4())

    resp = client.post("/v1/auth/register", json={
        "email": "dr.new@hospital.com",
        "password": "securepass",
        "name": "Dr. New",
        "specialty": "Internal Medicine",
    })
    assert resp.status_code == 201
    assert "doctor_id" in resp.json()


def test_register_duplicate_email(client, mock_db, sample_doctor):
    mock_db.query.return_value.filter.return_value.first.return_value = sample_doctor

    resp = client.post("/v1/auth/register", json={
        "email": "doctor@example.com",
        "password": "securepass",
        "name": "Dr. Duplicate",
    })
    assert resp.status_code == 400


def test_register_invalid_email(client, mock_db):
    resp = client.post("/v1/auth/register", json={
        "email": "not-an-email",
        "password": "securepass",
        "name": "Dr. Bad",
    })
    assert resp.status_code == 422


def test_register_short_password(client, mock_db):
    resp = client.post("/v1/auth/register", json={
        "email": "dr@hospital.com",
        "password": "short",
        "name": "Dr. Short",
    })
    assert resp.status_code == 422


def test_login_success(client, mock_db, sample_doctor):
    mock_db.query.return_value.filter.return_value.first.return_value = sample_doctor

    resp = client.post("/v1/auth/token", data={
        "username": "doctor@example.com",
        "password": "password123",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "doctor_id" in body
    assert body["token_type"] == "cookie"
    # TestClient (httpx) drops Secure cookies on HTTP; check the raw header instead
    assert "doctor_access_token" in resp.headers.get("set-cookie", "")


def test_login_wrong_credentials(client, mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = None

    resp = client.post("/v1/auth/token", data={
        "username": "nobody@example.com",
        "password": "wrong",
    })
    assert resp.status_code == 401


def test_logout(client):
    resp = client.post("/v1/auth/logout")
    assert resp.status_code == 200
    assert resp.json() == {"status": "logged out"}


def test_protected_endpoint_unauthenticated(client):
    resp = client.get("/v1/doctor/patients")
    assert resp.status_code == 401
