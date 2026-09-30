# Security Architecture & Threat Risk Assessment

This document outlines the security controls, prioritized threat mitigation matrix, and enterprise auditing strategy, adhering to **OWASP API Security Top 10** standards and Government of Canada **Protected B** recommendations.

---

## 1. Threat Modeling & Risk Prioritization Matrix

Security risks were evaluated and prioritized based on vulnerability severity, exploitability, and potential impact on parliamentary data integrity:

| Threat Vector | OWASP API Category | Initial Risk | Implemented Mitigation | Residual Risk | Implementation Evidence |
| :--- | :--- | :---: | :--- | :---: | :--- |
| **SQL Injection (SQLi)** | API8:2023 Security Misconfiguration | **HIGH** | **Strict Parameterization**: Queries use SQLAlchemy 2.0 ORM expressions. Raw SQL concatenation is entirely prohibited. | **LOW** | [`app/main.py:get_department_fte`](../app/main.py) |
| **Projection / Property Injection** | API3:2023 Broken Object Property Level Authorization | **MEDIUM** | **Strict Whitelist Verification**: The `tenure` parameter is checked against a static set (`{"indeterminate", "term", "casual", "student", "missing"}`). Invalid entries immediately abort with HTTP 400. | **LOW** | [`app/main.py:get_department_fte`](../app/main.py) |
| **Container Privilege Escalation** | CWE-250 Unnecessary Privileges | **MEDIUM** | **Non-Root Execution**: Provisions and executes via a locked-down system user (`appuser`, UID 10001). | **LOW** | [`Dockerfile:USER appuser`](../Dockerfile) |
| **Resource Depletion / DoS** | API4:2023 Unrestricted Resource Consumption | **MEDIUM** | **Pydantic Type Boundaries**: Non-integer IDs or queries trigger instant 422 rejections at the gateway layer. Compound indices prevent table-scanning query attacks. | **LOW** | [`app/models.py:idx_dept_year_quarter`](../app/models.py) |
| **Supply Chain Vulnerability (CVE)** | API8:2023 Security Misconfiguration | **MEDIUM** | **Multi-Stage Minimal Runtime**: Build toolchains are discarded. Production runtime is based on stripped `python:3.11-slim`. | **LOW** | [`Dockerfile:FROM python:3.11-slim`](../Dockerfile) |

---

## 2. Implemented Defense-in-Depth

### 2.1 Application-Level Defenses

* **Strict Type Safety**: Query parameters are typed and parsed via Pydantic/FastAPI (`id: int`, `year: Optional[int]`). Any malformed input (e.g., passing string characters into `id`) fails at the gateway layer with HTTP 422 before reaching business logic.
* **Zero Hardcoded Secrets**: No database passwords, private keys, or API tokens are checked into the repository. Configuration parameters are externalized through environment variables.
* **Probes for Cluster Health**: Orchestration platforms (Kubernetes / Azure App Service) can continuously verify process liveness (`/health/live`) and database connectivity readiness (`/health/ready`) to prevent routing traffic to unhealthy instances.

### 2.2 Container & Supply Chain Security

* **Minimal Base Image**: The container utilizes `python:3.11-slim`, significantly reducing the operating system footprint and reducing known CVE surfaces.
* **Deterministic Build Dependencies**: Production dependencies in `requirements.txt` are constrained with minimum version specifications to prevent upstream breaking changes or dependency tampering.

---

## 3. DevSecOps: Automated Supply Chain & Secret Scanning

To guarantee continuous assurance, the CI pipeline is architected to support immediate DevSecOps gate expansions:

```mermaid
flowchart TD
    Commit["Git Commit / Pull Request"] --> Gate["GitHub Actions Quality Gate"]

    subgraph SecurityChecks ["Automated Validation Gates"]
        Test["1. Test Suite & Coverage (pytest >= 90%)"]
        Secrets["2. Secret Leak Detection (Gitleaks / Trivy)"]
        SAST["3. Static Code Analysis (Bandit / Checkmarx)"]
        Container["4. Container Image Vulnerability (Aqua Trivy)"]
    end

    Gate --> Test
    Gate --> Secrets
    Gate --> SAST
    Gate --> Container

    Test --> Promotion["Approved Build / Artifact Promotion"]
    Secrets --> Promotion
    SAST --> Promotion
    Container --> Promotion
```

* **Immediate CI Enhancement**: Integrating open-source SAST (`bandit -r app/`) and vulnerability auditing (`pip-audit`) can be added directly to `.github/workflows/ci.yml` in under 10 lines of YAML.

## 4. Cloud Roadmap: Government of Canada "Protected B" Architecture

For enterprise cloud deployment (e.g., Azure Canada Central or AWS Canada Central), the architecture evolves to satisfy federal Protected B compliance requirements:
```mermaid
flowchart TD
    Internet["Internet Traffic (TLS 1.3 Encryption in Transit)"] --> WAF["Azure Front Door / Application Gateway + WAF<br/>(OWASP Rules, DDoS Protection, Rate Limiting)"]

    subgraph ProtectedVNet ["Private Virtual Network (Protected B Profile)"]
        subgraph ComputeSubnet ["Compute Subnet (Private VNet Peering)"]
            AppService["Azure Container Apps / AKS Cluster<br/>(Non-root API Pods, System-Assigned Managed Identity)"]
        end

        subgraph DataSubnet ["Data Subnet (Fully Isolated, No Public IP)"]
            DB[("Azure Database for PostgreSQL<br/>(Encrypted at Rest with CMK AES-256)")]
        end
    end

    WAF --> ComputeSubnet
    AppService -->|"Private Link & Secretless Auth (Entra ID)"| DB
```

### Key Architectural Controls:

1. **Secretless Authentication via Managed Identity (MI)**:
   * Eliminate stored credentials in environment variables or configuration files.
   * Compute instances authenticate directly to relational databases and Azure Key Vault via temporary Entra ID OAuth tokens.
2. **Network Perimeter Defense (Private Endpoints)**:
   * Databases and storage assets have zero public endpoints. All traffic traverses internal Virtual Network (VNet) private IP addresses.
3. **Auditability & Log Immutability**:
   * API access logs, container metrics, and readiness probe diagnostics are streamed to a centralized Security Information and Event Management (SIEM) system (Azure Monitor / Log Analytics) with retention policies adhering to Library and Archives Canada guidelines.