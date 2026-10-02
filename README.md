# Workforce Data Service

[![CI Quality Gate](https://github.com/wyzdr/workforce-data-service/actions/workflows/ci.yml/badge.svg)](https://github.com/wyzdr/workforce-data-service/actions/workflows/ci.yml)
[![Test Coverage](https://img.shields.io/badge/coverage-90%25%2B-brightgreen.svg)](tests/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![Docker Ready](https://img.shields.io/badge/docker-ready-2496ED.svg?logo=docker)](Dockerfile)

A production-grade backend service built to ingest, reconcile, standardize, and serve federal workforce datasets.

---

## ⚡Quickstart

You can run this application either directly on your **Local Machine** or using **Docker** (recommended for zero-dependency isolation).

### Option A: Run Locally (Python 3.11+)

1. **Create and activate a virtual environment**:

   - **Windows (PowerShell)**:
     ```powershell
     python -m venv .venv
     .venv\Scripts\Activate.ps1
     ```

   - **Linux / macOS**:
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```

2. **Install project dependencies**:
   ```bash
   pip install -r requirements-dev.txt
   ```

3. **Execute ETL pipeline (Ingest `data/data.xlsx` into database)**:
   ```bash
   python import_data.py
   ```

4. **Launch the FastAPI application**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

   Access the service at [http://localhost:8000/docs](http://localhost:8000/docs).

---

### Option B: Run with Docker

1. **Build the container image**:
   ```bash
   docker build -t workforce-service .
   ```

2. **Run the container**:
   ```bash
   docker run --name pbo-workforce -p 8000:8000 workforce-service
   ```

3. **Verify running instance**:
   Open your browser at [http://localhost:8000/docs](http://localhost:8000/docs) to access the interactive OpenAPI / Swagger UI.


---

## 📡 REST API Reference

The service strictly adheres to bilingual public sector schemas and federal reporting requirements.

| Method | Endpoint | Description | Implementation Reference |
| :--- | :--- | :--- | :--- |
| `GET` | `/health/live` | Container Liveness probe for orchestration | [`app.main.liveness_probe`](app/main.py#L33) |
| `GET` | `/health/ready` | Readiness probe verifying DB connectivity | [`app.main.readiness_probe`](app/main.py#L43) |
| `GET` | `/api/departments` | List all departments with bilingual metadata | [`app.main.get_departments`](app/main.py#L65) |
| `GET` | `/api/departments/{id}/fte` | Department quarterly FTE breakdown (filters: `year`, `tenure`) | [`app.main.get_department_fte`](app/main.py#L94) |

### Sample Response: `GET /api/departments`

```json
{
  "departments": [
    {
      "dept_id": 1,
      "dept_long": {
        "en": "Accessibility Standards Canada",
        "fr": "Normes d’accessibilité Canada"
      },
      "dept_short": {
        "en": "ASC",
        "fr": "NAC"
      }
    }
  ]
}
```

### Sample Response: `GET /api/departments/1/fte?year=2021`

```json
{
  "fte_per_quarter": [
    {
      "year": 2021,
      "quarter": 4,
      "indeterminate": 30.13,
      "term": 8.18,
      "casual": 0.0,
      "student": 0.0,
      "missing": 0.0
    }
  ]
}
```

---

## 🧪 Automated Testing & Quality Gates

The codebase enforces robust test-driven practices. Continuous Integration is validated on every push via GitHub Actions (`.github/workflows/ci.yml`).

Run the complete test suite and inspect code coverage locally:

```bash
python -m pytest --cov=app tests/ -v
```

### Test Suite Structure

* [`tests/test_api.py`](tests/test_api.py): Validates HTTP status codes, bilingual contract payloads, query parameters (`year`, `tenure`), and input validation (e.g. `404` on missing entities, `422` on invalid parameter types).
* [`tests/test_pipeline.py`](tests/test_pipeline.py): Unit tests for text normalization, Levenshtein fuzzy matching, resolution memoization, statutory tenure category mapping, and Dead-Letter Queue (DLQ) quarantine exports.

---

## 📂 System Architecture & Deep Dive Documentation

To maintain high developer experience and engineering modularity, detailed architectural analysis, design decisions, and security evaluations are organized in dedicated documents:

* 📐 **[Architecture & Data Design](docs/ARCHITECTURE.md)**:
  * ETL Pipeline Architecture & Multi-tier Entity Resolution ([`app/pipeline.py:DataCleaningPipeline`](app/pipeline.py#L16)).
  * Relational schema design, normalization, and compound indexing strategies ([`app/models.py`](app/models.py#L65)).
  * Key architectural assumptions, trade-offs (SQLite vs. PostgreSQL, synchronous vs. asynchronous I/O).
  * Advising Analysts and supporting downstream analytical workflows.

* 🛡️ **[Security Architecture & Threat Model](docs/SECURITY.md)**:
  * OWASP API Security risk prioritization and implemented mitigations.
  * Container non-root execution and parameterization defenses.
  * Enterprise Cloud Roadmap: Protected B compliance, Managed Identity (RBAC), and Private Endpoints.

* 📡 **[Cloud-native Logging & Incident Traceability](app/main.py#L28)**
  * Dual-channel routing (`stdout` & local persistent logs)
  * Asynchronous HTTP telemetry & anomaly tracing (2xx/4xx/5xx)
  * Resilient ETL execution & Dead-Letter Queue (DLQ) audit trail
---

### AI Tool Usage Disclosure

* **Tool Used**: Large Language Model assistants were utilized as an advisory peer-review tool.
* **Scope**: Assisted in brainstorming fuzzy reconciliation edge cases, generating boilerplates, drafting Markdown documentation structures, and validating bilingual naming fields.
* **Accountability**: All architecture, database models, business logic, pipeline transformations, and implementation decisions were authored, critically reviewed, tested, and validated by the author who retains full responsibility for all committed code.