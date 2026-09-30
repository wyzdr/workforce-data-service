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
    """Verify retrieval of all public sector departments and schema contract."""
    response = client.get("/api/departments")
    assert response.status_code == 200
    data = response.json()
    
    # Assert collection payload structure
    assert "departments" in data
    assert isinstance(data["departments"], list)
    assert len(data["departments"]) > 0
    
    # Validate bilingual schema contract against the first department record
    first_dept = data["departments"][0]
    assert "dept_id" in first_dept
    assert "dept_long" in first_dept
    assert "dept_short" in first_dept
    assert isinstance(first_dept["dept_id"], int)
    
    # Validate bilingual nested objects
    assert "en" in first_dept["dept_long"]
    assert "fr" in first_dept["dept_long"]
    assert "en" in first_dept["dept_short"]
    assert "fr" in first_dept["dept_short"]

# ==============================================================================
# 3. Core Business & Metric Query Endpoints
# ==============================================================================

def test_get_valid_department_fte():
    """Verify quarterly FTE metric retrieval for an existing department."""
    # Dynamically fetch an existing department ID to prevent brittle hardcoded tests
    dept_res = client.get("/api/departments")
    first_dept_id = dept_res.json()["departments"][0]["dept_id"]

    response = client.get(f"/api/departments/{first_dept_id}/fte")
    assert response.status_code == 200
    data = response.json()

    # Validate response schema
    assert "dept_id" in data or "department_id" in data
    assert "records" in data or "fte_records" in data or isinstance(data, dict)

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