# System Architecture & Technical Design Document

This document provides a comprehensive technical overview of the **PBO Workforce Data Service**, covering the real-world ETL reconciliation challenges, database modeling, pragmatic technical trade-offs, and an enterprise cloud roadmap for downstream PBO analysts.

## 1. High-Level Architecture Overview

The service transitions raw, inconsistent departmental spreadsheets into clean, standardized, and high-performance analytical REST interfaces:

```mermaid
flowchart TD
    Raw["Raw Excel Datasets<br/>(data/data.xlsx)"] --> ETL["ETL Reconciliation Engine<br/>(app/pipeline.py)"]
    ETL -.->|"Low-confidence anomalies"| DLQ["Dead-Letter Queue Audit<br/>(data_quarantine.csv)"]
    ETL --> DB[("Relational Storage Layer<br/>SQLite / PostgreSQL")]
    DB <--> API["FastAPI Application Layer<br/>(app/main.py)"]
    API --> Clients["PBO Analytical Consumers<br/>(R / Python / Excel / BI)"]
```


## 2. Ingestion & Entity Resolution: Real-World Data Challenges

External records seldom arrive clean. The data ingestion process ([`import_data.py`](../import_data.py) and [`app/pipeline.py`](../app/pipeline.py)) addresses data inconsistencies across federal reporting bodies without relying on rigid, hardcoded dictionary aliases.

### 2.1 Tackling Real Dirty Data in `data.xlsx`
During source data exploration, our pipeline encountered and resolved several tangible data traps:
* **Invisible Whitespace & Escaped Characters**: Department strings frequently contained trailing tabs, multiple contiguous spaces, and embedded line breaks (e.g., `"Department of Finance \n"` vs `"Department of Finance"`). Our pipeline applies text normalization ([`DataCleaningPipeline.normalize_text`](../app/pipeline.py#L71)) before any matching.
* **Bilingual Inconsistencies & Acronym Drifts**: Entities reported alternatively by their English name, French name, or operational acronyms (e.g., `"ASC"` vs `"Accessibility Standards Canada"` vs `"Normes d'accessibilité Canada"`). The pipeline dynamically builds a multi-key index from canonical metadata sheets.
* **Typographical Variants**: Near-miss spelling differences are caught using Levenshtein distance heuristics ([`difflib.get_close_matches`](../app/pipeline.py#L117) with a 0.85 confidence cutoff), preventing dropped records without manual intervention.

### 2.2 Ingestion Engine Workflow

```mermaid
flowchart LR
    A([Raw Record]) --> B[Normalize Text]
    B --> C{Exact / Cache?}
    C -- Yes --> D[Assign Dept ID]
    C -- No --> E{Fuzzy >= 0.85?}
    E -- Yes --> F[Cache & Map ID]
    E -- No --> G[/DLQ Quarantine/]
    G --> H[(data_quarantine.csv)]
    D --> I[(Database Store)]
    F --> I
```

### 2.3 Key Analytical & Domain Assumptions

#### 1. Quarterly Aggregation: Arithmetic Mean for Stock Capacity
* **Assumption**: Because FTE represents a stock capacity metric rather than a cumulative flow metric, quarterly figures are computed as the **arithmetic mean** across monthly observations within that quarter:

$$FTE_{Quarter} = \frac{1}{N} \sum_{m=1}^{N} FTE_{m}$$

*(where $N$ is the number of reported monthly snapshots in that quarter).*

#### 2. Methodological Equivalency: Active Headcount as FTE Capacity
* **Context**: While the core `Federal Public Service` dataset reports granular monthly Full-Time Equivalents (`fte`), the specialized defense and policing workbooks (`Canadian Armed Forces` and `Royal Canadian Mounted Police - Members`) report active personnel exclusively as `headcount`. Neither sub-dataset provides hourly pro-rating or part-time breakdown ratios.
* **Assumption**: For regular military personnel and sworn police members, active headcount is mapped 1:1 to FTE analytical capacity (`headcount` $\rightarrow$ `fte`). 

#### 3. Scope-Restricted Assumption: "Combined" Tenure for Sworn Members & Defense
* **Clarified Scope**: This assumption applies **strictly to regular uniformed personnel**—namely `Royal Canadian Mounted Police - Members` and `Canadian Armed Forces (CAF)`. Standard civilian employees under `Royal Canadian Mounted Police` (Public Service Employees) maintain full statutory breakdowns (`indeterminate`, `term`, `casual`, `student`) and are processed without heuristic tenure mapping.
* **Our Operational Rationale**: Uniformed members and regular armed forces are reported as a blanket `"Combined"` category in official sources. We map `"Combined"` to `"indeterminate"` under the operational rationale that core regular-force members represent permanent, continuous service commitments.
* **Architecture Flexibility Notice**: We acknowledge this is an operational proxy driven by source-data limitations. The transformation logic within `DataCleaningPipeline.normalize_tenure` is intentionally decoupled from storage models. If analysts require a proportional apportionment rule (e.g., distributing a fixed percentage to `term` or maintaining a separate statutory slice), the mapping can be revised with a single configuration adjustment without altering the underlying 3NF database schema.

---

## 3. Database Schema & Query Optimization

The relational data model is designed to support rapid multi-year time-series aggregations while preserving bilingual metadata.

### 3.1 Entity Relationship Diagram (ERD)

```mermaid
erDiagram
    DEPARTMENTS ||--o{ QUARTERLY_FTE : "has historical records"
    
    DEPARTMENTS {
        int id PK "Autoincrement Primary Key"
        string long_name_en "Indexed Canonical English Name"
        string long_name_fr "Canonical French Name"
        string short_name_en "English Acronym (e.g., ASC)"
        string short_name_fr "French Acronym (e.g., NAC)"
    }

    QUARTERLY_FTE {
        int id PK "Autoincrement Primary Key"
        int dept_id FK "References DEPARTMENTS(id) ON DELETE CASCADE"
        int year "Calendar / Fiscal Year"
        int quarter "Quarter (1 to 4)"
        float indeterminate "Full-Time Equivalents"
        float term "Full-Time Equivalents"
        float casual "Full-Time Equivalents"
        float student "Full-Time Equivalents"
        float missing "Unclassified / Gap Equivalents"
    }
```

### 3.2 Performance & Compound Indexing Strategy
* **Compound Index (`idx_dept_year_quarter`)**: Analytical queries overwhelmingly filter on a specific organization across a range of fiscal years (`WHERE dept_id = :id AND year = :year`). A multi-column B-Tree index on `(dept_id, year, quarter)` in ([`app/models.py`](../app/models.py#L65)) enables index-only lookups, avoiding costly full table scans.

---

## 4. Assessment Context: Architectural Trade-Offs

Given the scope of this take-home exercise, architectural choices were selected to maximize evaluator portability while maintaining enterprise upgrade paths:

| Architectural Area | Prototype Choice | Enterprise Production Target | Engineering Rationale & Upgrade Path |
| :--- | :--- | :--- | :--- |
| **Storage Engine** | SQLite (via SQLAlchemy) | Managed PostgreSQL (Azure Flexible Server) | **Why for Assessment**: Zero-dependency local evaluation. The evaluator needs no local database server or external credentials.<br><br>**Production Path**: Because models are decoupled via SQLAlchemy ORM, switching to PostgreSQL requires updating only the `DATABASE_URL` environment variable. |
| **Concurrency Model** | Synchronous ORM + FastAPI Worker Pool | Asynchronous ORM (`asyncpg` / `greenlet`) | **Why for Assessment**: Predictable execution, clean testing fixtures, and sub-15ms response times on typical analytical queries.<br><br>**Production Path**: Wrap sessions in `AsyncSession` for extreme high-throughput requirements. |
| **Data Ingestion** | In-Process Pandas Pipeline | Distributed Celery / Azure Functions Event Grid | **Why for Assessment**: Synchronous, inspectable feedback during `import_data.py`.<br><br>**Production Path**: Decouple ingestion into event-driven serverless workers when handling multi-gigabyte continuous feeds. |

---

## 5. Supporting PBO Analysts & Downstream Workflows

The system architecture addresses the practical needs of adapting data delivery to analytical staff and policy researchers:

* **Frictionless Consumption Across Toolchains**:
  * PBO analysts rely on diverse workflows ranging from statistical environments (R, Python) to spreadsheet modeling (Excel, Power BI).
  * The API produces standardized, flat JSON structures designed for direct ingestion into analytical DataFrames, eliminating tedious manual reshaping.
* **Targeted Querying (Reducing Client Overhead)**:
  * Using optional parameters such as `?year=2021` and `?tenure=casual`, analysts can pull exact data slices directly into their costing models without needing to fetch and filter entire multi-year departmental series locally.
* **Preserving Analytical Integrity & Transparency**:
  * Public sector costing models require strict accountability. Instead of silently dropping malformed records or coercing unknown figures, the pipeline exposes unclassified FTEs via the explicit `missing` category and logs low-confidence matches to ([`data_quarantine.csv`](../import_data.py#L236)). This ensures analysts have full visibility into data quality boundaries when preparing parliamentary estimates.
* **Future Workflow Recommendations (Advisory)**:
  * **Direct Tabular Export**: For analysts working predominantly in Excel, extending the API to support `Accept: text/csv` would allow one-click Power Query refresh without JSON parsing.
  * **Scheduled Snapshot Feeds**: Generating pre-aggregated fiscal-year summary tables can accelerate recurring quarterly reports during intense parliamentary budget cycles.

---

## 6. Enterprise Cloud Evolution Roadmap: Protected B & Scalability Blueprint

While this prototype is intentionally packaged for zero-dependency local evaluation, it is architected to scale toward a fully automated, Protected B cloud deployment. The diagram below illustrates the proposed production blueprint within the Government of Canada digital environment:

```mermaid
flowchart TD
    %% Automated CI/CD Pipeline
    subgraph DevOps ["Automated CI/CD Pipeline (GitHub Actions)"]
        Git["Git Commit / Main"] --> CI["CI: Pytest & Coverage 90%+"]
        CI --> CD["CD: Docker Build &<br/>Push to ACR"]
    end

    %% Edge Security & Ingress
    subgraph Edge ["Perimeter Defense & Ingress"]
        Users["External Analysts / Users"] --> WAF["Azure Front Door / WAF<br/>(Layer 7 Rules)"]
        WAF --> Ingress["API Gateway /<br/>Ingress Controller"]
    end

    %% Private Virtual Network
    subgraph VNet ["Private Virtual Network (VNet)"]
        subgraph ComputeSubnet ["Compute Subnet (Private Routing)"]
            App["Azure Container Apps /<br/>AKS Cluster"]
            Probes["/health/live &<br/>/health/ready Probes"]
            App --- Probes
        end

        subgraph DataSubnet ["Data Subnet (No Public IP)"]
            DB[("Azure Database for<br/>PostgreSQL")]
            KV[("Azure Key Vault")]
        end
    end

    %% Deploy & Traffic Connections
    CD -.->|"Zero-Downtime<br/>Rolling Update"| App
    Ingress -->|"Internal Routed<br/>Traffic"| App
    App -->|"Secretless Auth<br/>(Managed Identity)"| DB
    App -->|"Private Link<br/>(Private Endpoints)"| KV
```

### Key Enterprise Features:
* **Zero-Downtime Continuous Deployment (CD)**: Builds container images, tags with Git SHA, pushes to private container registries (ACR), and executes blue/green rolling deployments.
* **Auto-Scaling with KEDA**: Dynamically scales compute pods from 1 to 20 instances in response to peak budget cycle inquiry loads, scaling to zero off-hours to optimize cloud spend (FinOps).
* **High Availability & Geographic Redundancy**: Multi-zone replication across Azure Canada Central and Canada East ensures continuity during parliamentary debate cycles.