import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# ==============================================================================
# 1. Health & Infrastructure Probes
# ==============================================================================

def test_liveness_probe():
    """Verify that the service is running and passes container liveness check."""
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}

def test_readiness_probe():
    """Verify that the service and database connection pool are ready."""
    response = client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data.get("database") == "connected"

# ==============================================================================
# 2. Department Resource Endpoints
# ==============================================================================

def test_get_departments_success():
    """Verify retrieval of all public sector departments and bilingual schema contract."""
    response = client.get("/api/departments")
    assert response.status_code == 200
    data = response.json()
    
    assert "departments" in data
    assert isinstance(data["departments"], list)
    assert len(data["departments"]) > 0
    
    # Validate bilingual schema contract on a sample department record
    sample_dept = data["departments"][0]
    assert "dept_id" in sample_dept
    assert "dept_long" in sample_dept
    assert "dept_short" in sample_dept
    assert isinstance(sample_dept["dept_id"], int)
    
    assert "en" in sample_dept["dept_long"]
    assert "fr" in sample_dept["dept_long"]
    assert "en" in sample_dept["dept_short"]
    assert "fr" in sample_dept["dept_short"]

# ==============================================================================
# 3. Core Business & Metric Query Endpoints
# ==============================================================================

def test_get_valid_department_fte():
    """Verify quarterly FTE metric retrieval for an existing department."""
    # Dynamically retrieve an existing department ID to prevent brittle hardcoded tests
    dept_res = client.get("/api/departments")
    sample_dept_id = dept_res.json()["departments"][0]["dept_id"]

    response = client.get(f"/api/departments/{sample_dept_id}/fte")
    assert response.status_code == 200
    data = response.json()

    # Validate actual response contract containing fte_per_quarter array
    assert "fte_per_quarter" in data
    assert isinstance(data["fte_per_quarter"], list)
    assert len(data["fte_per_quarter"]) > 0

    # Validate metric record types
    first_record = data["fte_per_quarter"][0]
    assert "year" in first_record
    assert "quarter" in first_record
    assert isinstance(first_record["year"], int)
    assert isinstance(first_record["quarter"], int)

# ==============================================================================
# 4. Edge Cases & Request Validation (Error Handling)
# ==============================================================================

def test_get_department_fte_not_found():
    """Verify that querying a non-existent department returns HTTP 404 Not Found."""
    response = client.get("/api/departments/999999/fte")
    assert response.status_code == 404
    assert "detail" in response.json()

def test_get_department_fte_invalid_id_type():
    """Verify that malformed path parameters trigger HTTP 422 Unprocessable Entity."""
    response = client.get("/api/departments/invalid-id/fte")
    assert response.status_code == 422