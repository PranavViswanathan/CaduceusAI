"""Tests for postcare_api endpoints."""
import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from conftest import TEST_PATIENT_ID


# --- Care Plan ---

def test_generate_care_plan_requires_internal_key(client):
    resp = client.post("/v1/careplan/generate", json={
        "patient_id": str(uuid.uuid4()),
        "visit_notes": "Patient presented with mild hypertension and fatigue.",
    })
    assert resp.status_code == 403


def test_generate_care_plan_wrong_key(client):
    resp = client.post(
        "/v1/careplan/generate",
        json={"patient_id": str(uuid.uuid4()), "visit_notes": "Some notes here."},
        headers={"x-internal-key": "wrong"},
    )
    assert resp.status_code == 403


def test_generate_care_plan_empty_notes(client):
    resp = client.post(
        "/v1/careplan/generate",
        json={"patient_id": str(uuid.uuid4()), "visit_notes": "   "},
        headers={"x-internal-key": "test-internal-key"},
    )
    assert resp.status_code == 422


def test_generate_care_plan_success(client, mock_db):
    plan_id = uuid.uuid4()
    patient_id = uuid.uuid4()

    static_plan = {
        "follow_up_date": "2026-04-18",
        "medications_to_monitor": ["Lisinopril"],
        "lifestyle_recommendations": ["Low-sodium diet"],
        "warning_signs": ["Chest pain"],
    }

    def _refresh(obj):
        obj.id = plan_id
        obj.patient_id = patient_id
        obj.follow_up_date = date(2026, 4, 18)
        obj.medications_to_monitor = ["Lisinopril"]
        obj.lifestyle_recommendations = ["Low-sodium diet"]
        obj.warning_signs = ["Chest pain"]
        obj.visit_notes = "Patient has hypertension."
        obj.created_at = datetime.utcnow()

    mock_db.refresh.side_effect = _refresh

    with patch("main.generate_care_plan", new=AsyncMock(return_value=static_plan)):
        resp = client.post(
            "/v1/careplan/generate",
            json={"patient_id": str(patient_id), "visit_notes": "Patient has hypertension."},
            headers={"x-internal-key": "test-internal-key"},
        )

    assert resp.status_code == 201


def test_get_care_plan_unauthenticated(client):
    patient_id = uuid.uuid4()
    resp = client.get(f"/v1/careplan/{patient_id}")
    assert resp.status_code == 401


def test_get_care_plan_not_found(patient_client, mock_db):
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    # Must use the patient's own ID (matches JWT sub) to pass ownership check
    resp = patient_client.get(f"/v1/careplan/{TEST_PATIENT_ID}")
    assert resp.status_code == 404


def test_get_care_plan_success(patient_client, mock_db):
    plan = MagicMock()
    plan.id = uuid.uuid4()
    plan.patient_id = uuid.UUID(TEST_PATIENT_ID)
    plan.follow_up_date = date(2026, 4, 18)
    plan.medications_to_monitor = []
    plan.lifestyle_recommendations = []
    plan.warning_signs = []
    plan.visit_notes = "Routine checkup."
    plan.created_at = datetime.utcnow()

    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = plan
    # Must use the patient's own ID (matches JWT sub) to pass ownership check
    resp = patient_client.get(f"/v1/careplan/{TEST_PATIENT_ID}")
    assert resp.status_code == 200


# --- Check-in ---

def test_checkin_unauthenticated(client):
    resp = client.post("/v1/followup/checkin", json={
        "patient_id": str(uuid.uuid4()),
        "symptom_report": "Feeling fine today.",
    })
    assert resp.status_code == 401


def test_checkin_symptom_report_too_short(patient_client):
    resp = patient_client.post("/v1/followup/checkin", json={
        "patient_id": str(uuid.uuid4()),
        "symptom_report": "short",
    })
    assert resp.status_code == 422


def test_checkin_success_routine(patient_client, mock_db):
    # patient_id must match the JWT sub so the ownership check passes
    patient_id = TEST_PATIENT_ID
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    checkin_record = MagicMock()
    checkin_record.id = uuid.uuid4()
    checkin_record.patient_id = patient_id
    checkin_record.symptom_report = "Feeling a bit tired but otherwise okay today."
    checkin_record.urgency = "routine"
    checkin_record.reason = "No urgent keywords detected."
    checkin_record.created_at = datetime.utcnow()

    def _refresh(obj):
        obj.id = checkin_record.id
        obj.patient_id = patient_id
        obj.symptom_report = "Feeling a bit tired but otherwise okay today."
        obj.urgency = "routine"
        obj.reason = "No urgent keywords detected."
        obj.created_at = datetime.utcnow()

    mock_db.refresh.side_effect = _refresh

    urgency_result = {"urgency": "routine", "reason": "No urgent keywords detected."}
    with patch("main.assess_checkin_urgency", new=AsyncMock(return_value=urgency_result)):
        resp = patient_client.post("/v1/followup/checkin", json={
            "patient_id": patient_id,
            "symptom_report": "Feeling a bit tired but otherwise okay today.",
        })

    assert resp.status_code == 201
    assert resp.json()["urgency"] == "routine"


# --- Escalations ---

def test_pending_escalations_requires_doctor_role(patient_client):
    resp = patient_client.get("/v1/escalations/pending")
    assert resp.status_code == 403


def test_pending_escalations_doctor(doctor_client, mock_db):
    mock_db.query.return_value.filter.return_value.all.return_value = []
    resp = doctor_client.get("/v1/escalations/pending")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_acknowledge_escalation_not_found(doctor_client, mock_db):
    mock_db.query.return_value.filter.return_value.first.return_value = None
    resp = doctor_client.post(f"/v1/escalations/{uuid.uuid4()}/acknowledge")
    assert resp.status_code == 404


def test_acknowledge_escalation_success(doctor_client, mock_db):
    esc = MagicMock()
    esc.id = uuid.uuid4()
    esc.acknowledged = False

    mock_db.query.return_value.filter.return_value.first.return_value = esc
    resp = doctor_client.post(f"/v1/escalations/{esc.id}/acknowledge")
    assert resp.status_code == 200
    assert esc.acknowledged is True
