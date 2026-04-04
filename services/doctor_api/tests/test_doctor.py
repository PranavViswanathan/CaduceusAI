"""Tests for doctor clinical endpoints."""
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch


def test_list_patients_authenticated(authed_client, mock_db):
    mock_db.query.return_value.all.return_value = []
    resp = authed_client.get("/v1/doctor/patients")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_list_patients_returns_patients(authed_client, mock_db):
    patient = MagicMock()
    patient.id = uuid.uuid4()
    patient.name = "Jane Doe"
    patient.email = "jane@example.com"

    mock_db.query.return_value.all.return_value = [patient]
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    resp = authed_client.get("/v1/doctor/patients")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["name"] == "Jane Doe"


def test_submit_feedback_agree(authed_client, mock_db, sample_doctor):
    patient_id = uuid.uuid4()
    mock_db.refresh.return_value = None

    with patch("main._get_redis", return_value=None):
        resp = authed_client.post(f"/v1/doctor/patients/{patient_id}/feedback", json={
            "action": "agree",
            "doctor_id": str(sample_doctor.id),
        })
    assert resp.status_code == 200
    assert resp.json() == {"status": "recorded"}


def test_submit_feedback_invalid_action(authed_client, mock_db, sample_doctor):
    patient_id = uuid.uuid4()
    resp = authed_client.post(f"/v1/doctor/patients/{patient_id}/feedback", json={
        "action": "invalid_action",
        "doctor_id": str(sample_doctor.id),
    })
    assert resp.status_code == 422


def test_submit_feedback_reason_too_long(authed_client, mock_db, sample_doctor):
    patient_id = uuid.uuid4()
    resp = authed_client.post(f"/v1/doctor/patients/{patient_id}/feedback", json={
        "action": "flag",
        "reason": "x" * 2001,
        "doctor_id": str(sample_doctor.id),
    })
    assert resp.status_code == 422


def test_submit_feedback_override_queues_retrain(authed_client, mock_db, sample_doctor):
    patient_id = uuid.uuid4()
    mock_redis = MagicMock()

    with patch("main._get_redis", return_value=mock_redis):
        resp = authed_client.post(f"/v1/doctor/patients/{patient_id}/feedback", json={
            "action": "override",
            "reason": "Clinical assessment differs from AI output.",
            "doctor_id": str(sample_doctor.id),
        })

    assert resp.status_code == 200
    mock_redis.lpush.assert_called_once_with("retrain_queue", mock_redis.lpush.call_args[0][1])


def test_submit_feedback_invalidates_cache(authed_client, mock_db, sample_doctor):
    patient_id = uuid.uuid4()
    mock_redis = MagicMock()

    with patch("main._get_redis", return_value=mock_redis):
        authed_client.post(f"/v1/doctor/patients/{patient_id}/feedback", json={
            "action": "agree",
            "doctor_id": str(sample_doctor.id),
        })

    mock_redis.delete.assert_called_once_with(f"risk:{patient_id}")


def test_pending_escalations_unauthenticated(client):
    resp = client.get("/v1/escalations/pending")
    assert resp.status_code == 401


def test_pending_escalations_authenticated(authed_client, mock_db):
    mock_db.query.return_value.filter.return_value.all.return_value = []
    resp = authed_client.get("/v1/escalations/pending")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_retrain_trigger_no_key(client):
    resp = client.post("/v1/doctor/retrain/trigger")
    assert resp.status_code == 403


def test_retrain_trigger_wrong_key(client):
    resp = client.post("/v1/doctor/retrain/trigger", headers={"x-internal-key": "wrong"})
    assert resp.status_code == 403


def test_retrain_trigger_correct_key(client):
    with patch("main._get_redis", return_value=None):
        resp = client.post("/v1/doctor/retrain/trigger", headers={"x-internal-key": "test-internal-key"})
    assert resp.status_code == 200
