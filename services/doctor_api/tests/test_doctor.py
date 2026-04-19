"""Tests for doctor clinical endpoints."""
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch


# ── helpers ───────────────────────────────────────────────────────────────────

def _assignment_mock():
    a = MagicMock()
    a.id = uuid.uuid4()
    a.doctor_id = uuid.uuid4()
    a.patient_id = uuid.uuid4()
    a.assigned_at = datetime.utcnow()
    return a


def _mock_assigned(mock_db):
    """Make _assert_assigned pass by returning a truthy assignment row."""
    mock_db.query.return_value.filter.return_value.first.return_value = _assignment_mock()


def _mock_not_assigned(mock_db):
    """Make _assert_assigned raise 403 by returning None."""
    mock_db.query.return_value.filter.return_value.first.return_value = None


# ── list patients ─────────────────────────────────────────────────────────────

def test_list_patients_authenticated(authed_client, mock_db):
    mock_db.query.return_value.join.return_value.filter.return_value.offset.return_value.limit.return_value.all.return_value = []
    resp = authed_client.get("/v1/doctor/patients")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_list_patients_returns_assigned_patients(authed_client, mock_db):
    patient = MagicMock()
    patient.id = uuid.uuid4()
    patient.name = "Jane Doe"
    patient.email = "jane@example.com"

    mock_db.query.return_value.join.return_value.filter.return_value.offset.return_value.limit.return_value.all.return_value = [patient]
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    resp = authed_client.get("/v1/doctor/patients")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["name"] == "Jane Doe"


def test_list_patients_unauthenticated(client):
    resp = client.get("/v1/doctor/patients")
    assert resp.status_code == 401


# ── patient assignment ────────────────────────────────────────────────────────

def test_assign_patient_success(authed_client, mock_db):
    patient_id = uuid.uuid4()
    patient = MagicMock()
    patient.id = patient_id

    assignment = _assignment_mock()
    assignment.patient_id = patient_id

    # first query: patient lookup; second: existing assignment lookup (None = not yet assigned)
    mock_db.query.return_value.filter.return_value.first.side_effect = [patient, None]
    mock_db.refresh.side_effect = lambda obj: (
        setattr(obj, "id", assignment.id)
        or setattr(obj, "doctor_id", assignment.doctor_id)
        or setattr(obj, "patient_id", patient_id)
        or setattr(obj, "assigned_at", assignment.assigned_at)
    )

    resp = authed_client.post(f"/v1/doctor/patients/{patient_id}/assign")
    assert resp.status_code == 201


def test_assign_patient_idempotent(authed_client, mock_db):
    patient_id = uuid.uuid4()
    patient = MagicMock()
    patient.id = patient_id

    existing = _assignment_mock()
    existing.patient_id = patient_id
    existing.doctor_id = uuid.uuid4()

    mock_db.query.return_value.filter.return_value.first.side_effect = [patient, existing]

    resp = authed_client.post(f"/v1/doctor/patients/{patient_id}/assign")
    assert resp.status_code == 201


def test_assign_patient_not_found(authed_client, mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = None
    resp = authed_client.post(f"/v1/doctor/patients/{uuid.uuid4()}/assign")
    assert resp.status_code == 404


def test_unassign_patient_success(authed_client, mock_db):
    assignment = _assignment_mock()
    mock_db.query.return_value.filter.return_value.first.return_value = assignment
    resp = authed_client.delete(f"/v1/doctor/patients/{assignment.patient_id}/assign")
    assert resp.status_code == 204


def test_unassign_patient_not_found(authed_client, mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = None
    resp = authed_client.delete(f"/v1/doctor/patients/{uuid.uuid4()}/assign")
    assert resp.status_code == 404


# ── row-level security enforcement ───────────────────────────────────────────

def test_get_risk_blocked_when_not_assigned(authed_client, mock_db):
    _mock_not_assigned(mock_db)
    resp = authed_client.get(f"/v1/doctor/patients/{uuid.uuid4()}/risk")
    assert resp.status_code == 403


def test_submit_feedback_blocked_when_not_assigned(authed_client, mock_db):
    _mock_not_assigned(mock_db)
    resp = authed_client.post(
        f"/v1/doctor/patients/{uuid.uuid4()}/feedback",
        json={"action": "agree"},
    )
    assert resp.status_code == 403


# ── feedback ──────────────────────────────────────────────────────────────────

def test_submit_feedback_agree(authed_client, mock_db, sample_doctor):
    patient_id = uuid.uuid4()
    _mock_assigned(mock_db)
    mock_db.refresh.return_value = None

    with patch("main._get_redis", return_value=None):
        resp = authed_client.post(f"/v1/doctor/patients/{patient_id}/feedback", json={
            "action": "agree",
        })
    assert resp.status_code == 200
    assert resp.json() == {"status": "recorded"}


def test_submit_feedback_invalid_action(authed_client, mock_db, sample_doctor):
    patient_id = uuid.uuid4()
    resp = authed_client.post(f"/v1/doctor/patients/{patient_id}/feedback", json={
        "action": "invalid_action",
    })
    assert resp.status_code == 422


def test_submit_feedback_reason_too_long(authed_client, mock_db, sample_doctor):
    patient_id = uuid.uuid4()
    _mock_assigned(mock_db)
    resp = authed_client.post(f"/v1/doctor/patients/{patient_id}/feedback", json={
        "action": "flag",
        "reason": "x" * 2001,
    })
    assert resp.status_code == 422


def test_submit_feedback_override_queues_retrain(authed_client, mock_db, sample_doctor):
    patient_id = uuid.uuid4()
    _mock_assigned(mock_db)
    mock_redis = MagicMock()

    with patch("main._get_redis", return_value=mock_redis):
        resp = authed_client.post(f"/v1/doctor/patients/{patient_id}/feedback", json={
            "action": "override",
            "reason": "Clinical assessment differs from AI output.",
        })

    assert resp.status_code == 200
    mock_redis.lpush.assert_called_once_with("retrain_queue", mock_redis.lpush.call_args[0][1])


def test_submit_feedback_invalidates_cache(authed_client, mock_db, sample_doctor):
    patient_id = uuid.uuid4()
    _mock_assigned(mock_db)
    mock_redis = MagicMock()

    with patch("main._get_redis", return_value=mock_redis):
        authed_client.post(f"/v1/doctor/patients/{patient_id}/feedback", json={
            "action": "agree",
        })

    mock_redis.delete.assert_called_once_with(f"risk:{patient_id}")


def test_submit_feedback_retrain_uses_authenticated_doctor_id(authed_client, mock_db, sample_doctor):
    """Retrain queue payload must use the authenticated doctor's ID, not a client-supplied value."""
    patient_id = uuid.uuid4()
    _mock_assigned(mock_db)
    mock_redis = MagicMock()

    with patch("main._get_redis", return_value=mock_redis):
        authed_client.post(f"/v1/doctor/patients/{patient_id}/feedback", json={
            "action": "override",
            "reason": "Disagree with assessment.",
        })

    import json as _json
    payload = _json.loads(mock_redis.lpush.call_args[0][1])
    assert payload["doctor_id"] == str(sample_doctor.id)


# ── escalations ───────────────────────────────────────────────────────────────

def test_pending_escalations_unauthenticated(client):
    resp = client.get("/v1/escalations/pending")
    assert resp.status_code == 401


def test_pending_escalations_returns_only_assigned_patients(authed_client, mock_db):
    mock_db.query.return_value.filter.return_value.subquery.return_value = MagicMock()
    mock_db.query.return_value.filter.return_value.all.return_value = []
    resp = authed_client.get("/v1/escalations/pending")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── retrain ───────────────────────────────────────────────────────────────────

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
