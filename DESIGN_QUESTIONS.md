# Workforce Data Platform: Scaling, Synchronization & Analyst Experience

## Contents

- [Question 1: Scaling to Tens of Millions of Records](#question-1-scaling-to-tens-of-millions-of-records)
- [Question 2: Daily External API Sync & Historical Revisions](#question-2-daily-external-api-sync--historical-revisions)
- [Question 3: Improving Analyst Experience (Power BI & Python)](#question-3-improving-analyst-experience-power-bi--python)

---

## Question 1: Scaling to Tens of Millions of Records

When workforce records scale from thousands to tens of millions, a single-machine script with pandas and SQLite will quickly reach its bottleneck, resulting in Out-Of-Memory (OOM) crashes and database write locks.

Here is how we can evolve the architecture:

### 1. Ingestion & ETL Pipeline

- **Stream in Chunks instead of Bulk Load:** Replace single-instance `pandas.read_excel()` with stream chunking (e.g., loading 50,000–100,000 rows per batch) or high-performance columnar engines like DuckDB / Polars to keep memory consumption strictly bounded.

- **Bypass ORM Overhead:** Instantiating millions of SQLAlchemy ORM objects (`db.bulk_save_objects`) creates massive memory and CPU overhead. Instead, use database-native bulk loaders like PostgreSQL’s `COPY` command or cloud ETL bulk loaders (e.g., Azure Data Factory bulk copy), cutting write latency by 10x–50x.

- **Decouple with Message Queues:** Decouple file ingestion from the user-facing API using an event-driven queue (e.g., Celery backed by Redis, or Kafka). Dedicated background workers clean and validate batches in parallel without starving API threads of CPU and I/O resources.

### 2. Database & Analytical Storage

- **Range Partitioning:** Migrate from SQLite to an enterprise relational engine like PostgreSQL. Partition the fact table by year (e.g., `quarterly_fte_2024`, `quarterly_fte_2025`). Queries filtering by a specific department and year will scan only the target partition rather than traversing tens of millions of rows across disk.

- **Pre-Aggregations & Covering Indexes:** Computing quarterly averages from millions of monthly snapshots on the fly is too slow for real-time API responses. Instead of recalculating metrics on each request, pre-aggregate monthly figures into a physical analytical quarterly table (or a refreshed `MATERIALIZED VIEW`) with a covering index:

```sql
-- Pre-aggregated summary table refreshed via scheduled ETL/triggers
CREATE TABLE quarterly_fte_summary AS
SELECT
    dept_id,
    year,
    quarter,
    AVG(indeterminate) AS indeterminate,
    AVG(term) AS term,
    AVG(casual) AS casual,
    AVG(student) AS student,
    AVG(missing) AS missing
FROM raw_monthly_workforce
GROUP BY dept_id, year, quarter;

-- Covering index enabling fast index-only scans without heap lookups
CREATE INDEX idx_fte_lookup
ON quarterly_fte_summary (dept_id, year, quarter)
INCLUDE (indeterminate, term, casual, student, missing);
```

#### Read-Write Separation & Tiered Caching

- Store stable dimension data (departments) in an in-memory application cache (Redis or in-memory LRU) since organizational structures change infrequently.
- Route analytical read traffic to read replicas, preserving the primary database instance strictly for ETL bulk writes.

---

## Question 2: Daily External API Sync & Historical Revisions

In public sector reporting, upstream feeds frequently revise past figures (e.g., adjusting prior-year headcounts), but analysts have already published official briefs using earlier figures. We cannot simply issue destructive `UPDATE` or `DELETE` statements on historical data.

### 1. Automated Sync & Data Quality Assurance

- **Change Data Capture (CDC):** Fetch daily updates using change-detection watermarks (e.g., `Last-Modified` timestamps). Ingestion jobs must be strictly idempotent: running the same synchronization multiple times converges to the exact same database state without duplicate metrics.

- **Append-Only Data Versioning (SCD Type 2):** Never overwrite existing rows in place. Use versioned records:
  - Each fact row includes `version_id`, `effective_from`, `effective_to`, and `is_current`.
  - When a revised number arrives, flag the previous record as inactive (`is_current = FALSE`, `effective_to = NOW()`), and insert the revised number as the active entry.

- **Quality Gates & DLQ:** Reuse our existing `DataCleaningPipeline` to catch upstream schema drift or unmapped department labels. Any anomaly (e.g., an unexpected tenure label or an abrupt headcount fluctuation) routes directly to the Dead-Letter Queue (DLQ) with automated alerts, while clean records continue to ingest without interruption.

### 2. Adapting Delivery to Analysts’ Workflows

#### Point-in-Time & Snapshot Queries

Analysts must be able to reproduce past econometric models and published briefs even after historical figures are revised. We can support snapshot queries directly via API parameters:

```http
GET /api/departments/1/fte?as_of=2026-03-01
GET /api/departments/1/fte?version=2025Q4_Baseline
```

This guarantees that previously published analyses remain 100% reproducible over time.

#### Proactive Changelog & Revision Diff API

Expose an endpoint tracking modifications:

```http
GET /api/revisions?since=2026-09-01
```

Complement this with automated weekly or monthly notifications (e.g., automated email or Teams alerts noting “National Defence revised 2024 Q3 Indeterminate FTE by +120”), enabling analysts to update ongoing models without surprises.

### 3. PR Review Priorities (Ordering of Concerns)

When reviewing a colleague’s synchronization PR, I evaluate and prioritize risks across four clear tiers:

#### P0 — Data Integrity & Transaction Safety (Highest)

Is the sync wrapped in an atomic transaction? If network connectivity drops halfway through, will it leave partial/corrupted data or break existing snapshots? Is the script strictly idempotent to prevent duplicated records upon retries?

#### P1 — Backward Compatibility & Data Contracts

Do the new versioning fields or revision endpoints break the existing REST API contract, or will they disrupt existing analysts’ scripts and downstream pipelines?

#### P2 — Error Handling & Logging

If the external API returns 5xx errors or malformed payloads, does the sync job retry with exponential backoff and isolate anomalies without crashing? Are row counts (inserted, revised, quarantined) and sync latencies recorded in persistent audit logs (`pipeline.log`) for diagnostics?

#### P3 — Code Hygiene & Network Resilience

Does the code configure realistic HTTP timeouts, clean connection pooling, and circuit-breaker protections? Are these backed by comprehensive unit tests and mock fixtures covering edge cases and upstream outages?

---

## Question 3: Improving Analyst Experience (Power BI & Python)

Analysts should not have to spend time writing boilerplate code, managing token refreshes, or manually flattening nested JSON payloads. Here are concrete improvements:

### 1. For Power BI Analysts

- **Flat Star-Schema Views:** Provide pre-flattened database views (e.g., `vw_workforce_cube`) joining dimension tables (bilingual department names, acronyms) directly with fact metrics (quarterly FTE aggregates). Power BI users can connect via ODBC / PostgreSQL drivers to drag-and-drop fields without writing custom Power Query (M) transformations or parsing nested JSON.

- **Direct Database / OData Connectivity:** Provide direct read-only SQL connection strings or an OData feed so Power BI can utilize native DirectQuery mode alongside scheduled automatic data refreshes.

- **One-Click Export Formats:** Support standard HTTP Content Negotiation and query parameters on existing REST endpoints:

```http
GET /api/departments/1/fte?format=csv
Accept: text/csv
```

Streaming flat CSV data directly allows analysts to use Power BI’s native `Web.Contents` connector, which infers column types automatically and avoids JSON transformation overhead.

### 2. For Python Analysts & Data Scientists

- **Dedicated Lightweight SDK (`pbo-workforce`):** Wrap the REST API into an installable Python package (`pip install pbo-workforce`). The SDK abstracts away pagination, authentication headers, and network retries, returning clean Pandas or Polars DataFrames out of the box. Instead of raw requests code, analysts simply write:

```python
from pbo_workforce import WorkforceClient

client = WorkforceClient(base_url="https://api.pbo-dpb.ca")

# Retrieve fully cleaned, strongly-typed DataFrames in a single line
df = client.get_department_fte(dept_id=1, as_dataframe=True)
```

- **Vectorized Columnar Exports (Apache Arrow / Parquet):** For heavy econometric regressions or cross-departmental batch processing, we can provide endpoints returning binary columnar formats (`/api/departments/fte/export.parquet`). Analysts can load millions of records into memory in milliseconds using `polars.read_parquet()` or `pyarrow`, preserving native float precision and timestamp datatypes without JSON parsing penalties.

### 3. Clear Data Dictionary Endpoint

- Add a `/api/metadata/dictionary` endpoint documenting standardized tenure definitions, statutory conversion assumptions (e.g., mapping military/RCMP combined counts to indeterminate FTE), and dataset vintage dates. This metadata can also be wired directly into Power BI report tooltips to ensure shared domain understanding across teams.
