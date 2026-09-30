# Security Architecture & Threat Risk Assessment

This document outlines the security posture, threat mitigation strategies, and enterprise compliance roadmap for the **PBO Workforce Data Service**, aligned with the **Government of Canada's "Protected B, Medium Integrity, Medium Availability" (PBMM)** profile and **OWASP API Security Top 10** standards.

---

## 1. Threat Modeling & Risk Prioritization Matrix

Security risks were evaluated and prioritized based on vulnerability severity, exploitability, and potential impact on parliamentary data integrity:

| Threat / Risk Vector | OWASP API Category | Initial Risk Level | Implemented Mitigation | Residual Risk | Code Reference |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **SQL Injection (SQLi)** | API8:2023 Security Misconfiguration / Injection | **HIGH** | **SQLAlchemy Parameterization**: All user query inputs (`id`, `year`, `tenure`) are strictly parameterized. Raw SQL string concatenation is entirely prohibited. | **LOW** | [`app/main.py:get_department_fte`](../app/main.py) |
| **Invalid Input & Projection Injection** | API3:2023 Broken Object Property Level Authorization | **MEDIUM** | **Strict Whitelisting**: The `tenure` parameter is validated against a pre-compiled set (`{"indeterminate", "term", "casual", "student", "missing"}`). Non-matching inputs trigger an immediate HTTP 400 rejection. | **LOW** | [`app/main.py:get_department_fte`](../app/main.py) |
| **Container Privilege Escalation** | CWE-250 Execution with Unnecessary Privileges | **MEDIUM** | **Non-Root Execution**: Dockerfile provisions a dedicated system user (`appuser`, UID 10001) and strips root privileges before starting Uvicorn. | **LOW** | [`Dockerfile:USER appuser`](../Dockerfile) |
| **Denial of Service (Resource Exhaustion)** | API4:2023 Unrestricted Resource Consumption | **MEDIUM** | **Pydantic Type Coercion**: Type validation prevents arbitrary large payloads; compound indices prevent unindexed full table scans on analytical queries. | **LOW** | [`app/models.py:idx_dept_year_quarter`](../app/models.py) |
| **Container Image Vulnerability (CVEs)** | API8:2023 Security Misconfiguration | **MEDIUM** | **Multi-Stage Build**: Compilers, build dependencies, and temporary files are isolated in the builder stage. The final runtime image contains only minimal wheels. | **LOW** | [`Dockerfile:FROM python:3.11-slim`](../Dockerfile) |

---

## 2. Implemented Defense-in-Depth Mechanisms

### 2.1 Application-Level Defenses

* **Strict Type Safety**: Query parameters are typed and parsed via Pydantic/FastAPI (`id: int`, `year: Optional[int]`). Any malformed input (e.g., passing string characters into `id`) fails at the gateway layer with HTTP 422 before reaching business logic.
* **Zero Hardcoded Secrets**: No database passwords, private keys, or API tokens are checked into the repository. Configuration parameters are externalized through environment variables.
* **Probes for Cluster Health**: Orchestration platforms (Kubernetes / Azure App Service) can continuously verify process liveness (`/health/live`) and database connectivity readiness (`/health/ready`) to prevent routing traffic to unhealthy instances.

### 2.2 Container & Supply Chain Security

* **Minimal Base Image**: The container utilizes `python:3.11-slim`, significantly reducing the operating system footprint and reducing known CVE surfaces.
* **Deterministic Build Dependencies**: Production dependencies in `requirements.txt` are constrained with minimum version specifications to prevent upstream breaking changes or dependency tampering.

---

## 3. Cloud Roadmap: Government of Canada "Protected B" Architecture

For enterprise cloud deployment (e.g., Azure Canada Central or AWS Canada Central), the architecture evolves to satisfy federal Protected B compliance requirements:

```text
[ Internet Traffic ]
│ (TLS 1.3 Encryption in Transit)
▼
[ Azure Front Door / Application Gateway + WAF ]
Layer 7 OWASP Top 10 Rules, DDoS Protection, Rate Limiting
│
▼ (Private VNet Peering)
[ Compute Subnet: Azure Container Apps / AKS ]
Non-root API pods with System-Assigned Managed Identity (MI)
│
▼ (Azure Private Link / Private Endpoint)
[ Data Subnet: Azure Database for PostgreSQL (Flexible Server) ]
Fully isolated from public internet; zero public IP
Secretless database authentication via Microsoft Entra ID (Azure AD)
Data encrypted at rest via Customer-Managed Keys (CMK / AES-256)
```

### Key Architectural Controls:

1. **Secretless Authentication via Managed Identity (MI)**:
   * Eliminate stored credentials in environment variables or configuration files.
   * Compute instances authenticate directly to relational databases and Azure Key Vault via temporary Entra ID OAuth tokens.
2. **Network Perimeter Defense (Private Endpoints)**:
   * Databases and storage assets have zero public endpoints. All traffic traverses internal Virtual Network (VNet) private IP addresses.
3. **Auditability & Log Immutability**:
   * API access logs, container metrics, and readiness probe diagnostics are streamed to a centralized Security Information and Event Management (SIEM) system (Azure Monitor / Log Analytics) with retention policies adhering to Library and Archives Canada guidelines.