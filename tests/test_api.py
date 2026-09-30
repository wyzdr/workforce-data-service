from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_liveness_probe():
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}

def test_readiness_probe():
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"

def test_get_departments():
    response = client.get("/api/departments")
    assert response.status_code == 200
    data = response.json()
    assert "departments" in data
    assert len(data["departments"]) > 0

def test_get_department_fte_not_found():
    response = client.get("/api/departments/999999/fte")
    assert response.status_code == 404
