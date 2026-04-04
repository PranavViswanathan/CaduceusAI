"""Tests for patient data endpoints."""
import uuid
from datetime import datetime
from unittest.mock import MagicMock


def test_submit_intake_unauthenticated(client):
    resp = client.post("/v1/patients/intake", json={
        "conditions": [],
        "medications": [],
        "allergies": [],
        "symptoms": "I have been feeling unwell for several days",
    })
    assert resp.status_code == 401


def test_submit_intake_symptoms_too_short(authed_client):
    resp = authed_client.post("/v1/patients/intake", json={
        "conditions": [],
        "medications": [],
        "allergies": [],
        "symptoms": "short",
    })
    assert resp.status_code == 422


def test_submit_intake_success(authed_client, mock_db):
    intake_id = uuid.uuid4()
    patient_id = uuid.uuid4()

    mock_intake = MagicMock()
    mock_intake.id = intake_id
    mock_intake.patient_id = patient_id
    mock_intake.conditions = []
    mock_intake.medications = []
    mock_intake.allergies = []
    mock_intake.symptoms = "I have been experiencing persistent headaches and fatigue."
    mock_intake.submitted_at = datetime.utcnow()

    def _refresh(obj):
        obj.id = intake_id
        obj.patient_id = patient_id
        obj.conditions = []
        obj.medications = []
        obj.allergies = []
        obj.symptoms = "I have been experiencing persistent headaches and fatigue."
        obj.submitted_at = datetime.utcnow()

    mock_db.refresh.side_effect = _refresh

    resp = authed_client.post("/v1/patients/intake", json={
        "conditions": ["Hypertension"],
        "medications": [],
        "allergies": [],
        "symptoms": "I have been experiencing persistent headaches and fatigue.",
    })
    assert resp.status_code == 201


def test_get_patient_self(authed_client, mock_db, sample_patient):
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    resp = authed_client.get(f"/v1/patients/{sample_patient.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == sample_patient.email


def test_get_patient_other_patient_forbidden(authed_client):
    other_id = uuid.uuid4()
    resp = authed_client.get(f"/v1/patients/{other_id}")
    assert resp.status_code == 403


def test_submit_intake_conditions_item_too_long(authed_client):
    resp = authed_client.post("/v1/patients/intake", json={
        "conditions": ["A" * 201],
        "medications": [],
        "allergies": [],
        "symptoms": "I have been experiencing persistent headaches and fatigue.",
    })
    assert resp.status_code == 422


def test_submit_intake_symptoms_too_long(authed_client):
    resp = authed_client.post("/v1/patients/intake", json={
        "conditions": [],
        "medications": [],
        "allergies": [],
        "symptoms": "x" * 5001,
    })
    assert resp.status_code == 422
