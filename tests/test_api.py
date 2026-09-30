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
    """Verify that the service and SQLite database connection pool are ready."""
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
    
    # Validate schema contract against the first department record
    first_dept = data["departments"][0]
    assert "id" in first_dept
    assert "name_en" in first_dept
    assert "name_fr" in first_dept
    assert isinstance(first_dept["id"], int)

# ==============================================================================
# 3. Core Business & Metric Query Endpoints
# ==============================================================================

def test_get_valid_department_fte():
    """Verify quarterly FTE metric retrieval for an existing department."""
    # Dynamically fetch an existing department ID to prevent brittle hardcoded tests
    dept_res = client.get("/api/departments")
    first_dept_id = dept_res.json()["departments"][0]["id"]

    response = client.get(f"/api/departments/{first_dept_id}/fte")
    assert response.status_code == 200
    data = response.json()

    # Validate response schema
    assert "department_id" in data
    assert data["department_id"] == first_dept_id
    assert "records" in data
    assert isinstance(data["records"], list)
    
    # Assert data types of quarterly timeseries entries if present
    if len(data["records"]) > 0:
        record = data["records"][0]
        assert "year" in record
        assert "quarter" in record
        assert "fte" in record
        assert isinstance(record["year"], int)
        assert isinstance(record["quarter"], str)
        assert isinstance(record["fte"], (int, float))

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