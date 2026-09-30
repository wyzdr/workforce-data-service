# Security Architecture & Threat Risk Assessment

This document outlines the security controls, prioritized threat mitigation matrix, and enterprise auditing strategy implemented in the **PBO Workforce Data Service**, adhering to **OWASP API Security Top 10** standards and Government of Canada **Protected B** recommendations.

---

## 1. Threat Modeling & Risk Prioritization Matrix

Security vectors were analyzed and prioritized based on impact severity, exploitability, and risk to parliamentary data integrity:

| Threat Vector | OWASP API Category | Initial Risk | Implemented Mitigation | Residual Risk | Implementation Evidence |
| :--- | :--- | :---: | :--- | :---: | :--- |
| **SQL Injection (SQLi)** | API8:2023 Security Misconfiguration | **HIGH** | **Strict Parameterization**: Queries use SQLAlchemy 2.0 ORM expressions. Raw SQL concatenation is entirely prohibited. | **LOW** | [`app/main.py:get_department_fte`](../app/main.py) |
| **Projection / Property Injection** | API3:2023 Broken Object Property Level Authorization | **MEDIUM** | **Strict Whitelist Verification**: The `tenure` parameter is checked against a static set (`{"indeterminate", "term", "casual", "student", "missing"}`). Invalid entries immediately abort with HTTP 400. | **LOW** | [`app/main.py:get_department_fte`](../app/main.py) |
| **Container Privilege Escalation** | CWE-250 Unnecessary Privileges | **MEDIUM** | **Non-Root Execution**: Provisions and executes via a locked-down system user (`appuser`, UID 10001). | **LOW** | [`Dockerfile:USER appuser`](../Dockerfile) |
| **Resource Depletion / DoS** | API4:2023 Unrestricted Resource Consumption | **MEDIUM** | **Pydantic Type Boundaries**: Non-integer IDs or queries trigger instant 422 rejections at the gateway layer. Compound indices prevent table-scanning query attacks. | **LOW** | [`app/models.py:idx_dept_year_quarter`](../app/models.py) |
| **Supply Chain Vulnerability (CVE)** | API8:2023 Security Misconfiguration | **MEDIUM** | **Multi-Stage Minimal Runtime**: Build toolchains are discarded. Production runtime is based on stripped `python:3.11-slim`. | **LOW** | [`Dockerfile:FROM python:3.11-slim`](../Dockerfile) |

---

## 2. Implemented Defense-in-Depth

### 2.1 Application Gateway & Input Sanitation
* **Pydantic Structural Enforcement**: Fast-failing input filters prevent malformed payloads from consuming worker CPU.
* **Deterministic Configuration**: All runtime settings are externalized to environment variables; no secrets, tokens, or credentials exist in the source code.
* **Orchestration Probes**: Probes at `/health/live` and `/health/ready` verify internal health and database connectivity, ensuring unhealthy pods are severed from traffic instantly.

### 2.2 Container Hardening
* **Non-Root Execution Context**: The container runs under an unprivileged `appuser`. In the event of a zero-day application compromise, host root access cannot be achieved.
* **Read-Only / Ephemeral Boundaries**: The runtime container does not require elevated host capabilities or host volume bindings.

---

## 3. DevSecOps: Automated Supply Chain & Secret Scanning

To guarantee continuous assurance, the CI pipeline is architected to support immediate DevSecOps gate expansions:

```text
[ Git Commit ]
│
▼
[ GitHub Actions Quality Gate ]
├── 1. Code Quality & Test Suite (pytest, pytest-cov >= 90%)
├── 2. Secret Leak Detection (Trivy / Gitleaks / GitGuardian)
├── 3. Static Application Security Testing - SAST (Checkmarx / Bandit)
└── 4. Container Vulnerability Scan (Aqua Trivy / Snyk)
│
▼
[ Approved Build / Artifact Promotion ]
```

* **Immediate CI Enhancement**: Integrating open-source SAST (`bandit -r app/`) and vulnerability auditing (`pip-audit`) can be added directly to `.github/workflows/ci.yml` in under 10 lines of YAML.

---

## 4. Enterprise Auditing & Centralized Telemetry

For deployment within federal cloud environments (e.g., Azure Government Canada), runtime auditability is satisfied via centralized SIEM integration:

```text
[ Container Apps / AKS ]
│ (Structured JSON Diagnostic Logs via stdout)
▼
[ Azure Monitor Log Analytics / Event Hub ]
│
▼
[ Centralized SIEM / Microsoft Sentinel ]
  ├── Immutable Audit Trails
  ├── Unauthorized Access Pattern Alerts (HTTP 4xx Spikes)
  └── Retention Compliant with Library and Archives Canada Regulations
```

### Key Enterprise Security Controls:
1. **Secretless Infrastructure (Managed Identity)**: Eliminates stored connection strings. APIs authenticate directly to Azure PostgreSQL and Key Vault using ephemeral Entra ID (Azure AD) tokens.
2. **Network Isolation (Private Endpoints)**: Databases and backing services are provisioned strictly without public IP addresses, accessible solely via Virtual Network (VNet) private routing.
3. **Structured Audit Logging**: Incoming requests log client IP hashes, endpoint paths, response codes, and query latencies, streaming directly to Azure Event Hub / Log Analytics for real-time threat detection.