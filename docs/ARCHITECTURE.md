# System Architecture & Technical Design Document

This document provides an in-depth architectural breakdown of the **PBO Workforce Data Service**, detailing the ETL reconciliation pipeline, relational database modeling, key technical assumptions, trade-offs, and strategies for empowering downstream PBO analysts.

---

## 1. High-Level System Architecture

The service bridges heterogeneous public sector data sources and downstream parliamentary analysis workflows through a robust, decoupled pipeline:

```text
[ Raw Excel Datasets ]
│ (data/data.xlsx)
▼
[ ETL Reconciliation Engine ] ──► [ Dead-Letter Queue (DLQ) Audit ]
app/pipeline.py (Levenshtein Fuzzy Matching, Memoization Cache)
│
▼
[ Structured Relational Storage ]
SQLite (Production Prototype) / PostgreSQL Ready (SQLAlchemy ORM)
Compound Indexing: (dept_id, year, quarter)
│
▼
[ FastAPI Service Layer ] ──► [ Container Probes: /health/live, /health/ready ]
Parameter Whitelisting, Dynamic Projections, Open Data Contract
│
▼
[ Downstream Clients: PBO Economists, Policy Analysts, Excel/R/BI Dashboards ]
```

---

## 2. Data Cleaning & Reconciliation Pipeline

The data ingestion process (`import_data.py` and `app/pipeline.py`) addresses data inconsistencies across federal reporting bodies without relying on rigid, hardcoded dictionary aliases.

### 2.1 Multi-Tier Entity Resolution (`DataCleaningPipeline.resolve_department`)

Federal department names frequently exhibit minor spelling variants, acronym variations, or extraneous whitespace. The resolution follows a tiered fallback mechanism:

1. **Tier 1: Canonical Exact Matching**: Inputs are normalized via `DataCleaningPipeline.normalize_text` (collapsing contiguous whitespaces, trimming ends) and checked against ground-truth keys derived dynamically from the canonical dimension tab.
2. **Tier 2: Memoization Cache (`self.match_cache`)**: Once a raw variant is resolved, the result is stored in memory. Subsequent occurrences of the same string bypass string similarity algorithms, reducing computational time from $O(N \cdot M)$ to $O(1)$.
3. **Tier 3: Fuzzy Matching Heuristic**: Unmatched names are evaluated against the canonical set using Levenshtein distance heuristics (`difflib.get_close_matches`) with a strict similarity cutoff ($0.85$ default). Matches meeting or exceeding this threshold are linked automatically.
4. **Tier 4: Dead-Letter Queue (DLQ) Isolation**: Inputs falling below the confidence threshold are quarantined (`self.quarantine_records`) rather than dropped silently. Quarantined records can be exported via `export_quarantine_report()` to `data_quarantine.csv` for human-in-the-loop auditor review.

### 2.2 Statutory Tenure Normalization (`DataCleaningPipeline.normalize_tenure`)

Federal employment statuses are reconciled into the five statutory categories required by the API contract: `indeterminate`, `term`, `casual`, `student`, and `missing`.

* **Domain Business Rule**: Records with a tenure label of `"Combined"` (frequently reported for military personnel and RCMP regular service members) are mapped to permanent `"indeterminate"` status, reflecting their operational permanence under federal career structures.
* **Schema Boundary**: Null, missing, or unrecognized status labels default to `"missing"`, preventing schema violations downstream.

---

## 3. Database Schema & Query Optimization

The relational schema is implemented in `app/models.py` using SQLAlchemy 2.0.

### 3.1 Schema Design

* **`departments` (Dimension Table)**:
  * `id` (Integer, Primary Key, Autoincrement)
  * `long_name_en` (String, Indexed, Not Null)
  * `long_name_fr` (String, Not Null)
  * `short_name_en` / `short_name_fr` (String, Nullable acronyms)
* **`quarterly_fte` (Fact Table)**:
  * `id` (Integer, Primary Key)
  * `dept_id` (Integer, Foreign Key $\rightarrow$ `departments.id`, On Delete Cascade)
  * `year` (Integer, Not Null)
  * `quarter` (Integer, Not Null)
  * `indeterminate`, `term`, `casual`, `student`, `missing` (Float, Default 0.0)

### 3.2 Performance & Compound Indexing

To ensure low-latency analytical queries across multi-year historical series:
* A compound index `idx_dept_year_quarter` is created on `quarterly_fte (dept_id, year, quarter)`.
* This matches the predominant analytical query pattern: retrieving quarterly breakdowns filtered by department ID and specific fiscal/calendar years.

---

## 4. Key Assumptions & Architectural Trade-offs

| Decision | Selected Option | Alternative Considered | Rationale & Trade-off Evaluation |
| :--- | :--- | :--- | :--- |
| **Storage Engine** | **SQLite (via SQLAlchemy)** | PostgreSQL | **Decision**: SQLite provides zero-dependency, self-contained portability for local evaluation and containerized distribution. <br>**Trade-off**: Lacks native concurrent write scaling. Because the service is analytical (read-heavy, batch ETL writes), SQLite handles high concurrent read loads efficiently. Switching to managed PostgreSQL requires only altering the `DATABASE_URL` connection string without modifying business models. |
| **I/O Concurrency** | **Synchronous ORM + FastAPI Threadpool** | Fully Async (asyncpg / greenlet) | **Decision**: Standard synchronous ORM sessions execute in FastAPI's internal `anyio` worker threadpool. <br>**Trade-off**: Avoids the operational overhead and debugging complexity of async database drivers while easily delivering sub-15ms response times for analytical queries. |
| **Matching Strategy** | **Algorithmic Heuristic (difflib) + DLQ** | Hardcoded Static Dict | **Decision**: Dynamic Levenshtein matching adapts to new data files automatically. <br>**Trade-off**: Slightly higher initial ingestion CPU cost, fully mitigated by resolution memoization (`match_cache`). |

---

## 5. Advising PBO Analysts & Workflow Integration

To address the asset qualifications regarding analyst advisory and downstream adaptation:

1. **Direct Integration with Analytical Toolchains**:
   * PBO analysts primarily conduct econometric modeling in **R**, **Python (pandas)**, and **Excel/PowerBI**.
   * The API provides predictable, machine-readable JSON schemas that map directly to tabular DataFrames (`pd.read_json` or `httr` in R).
2. **Dynamic Field Projection**:
   * The `GET /api/departments/{id}/fte?tenure=...` endpoint supports projection filtering. Analysts investigating casualization trends can query only casual numbers without processing unwanted categories, reducing network payload and client-side transformation effort.
3. **Data Quality Transparency**:
   * The presence of the `missing` category alongside DLQ quarantine audit logs ensures that analysts have full visibility into data gaps, preventing statistical skew in parliamentary cost estimations.