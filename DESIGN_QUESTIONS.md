# System Design & Architecture Responses

---

## Question 1: Scaling to Tens of Millions of Rows

If our data grows from a few thousand rows to tens of millions, the current setup will hit two immediate bottlenecks: **pandas will run out of memory (OOM)** trying to load everything at once, and **SQLite will choke on concurrent writes**. 

Here is how we scale it step-by-step:

* **Storage (Partition by Year)**: Move from SQLite to a production-grade database (like PostgreSQL). We split the big `quarterly_fte` table into yearly partitions. When an analyst asks for 2024 data, the database only scans the 2024 slice instead of sifting through decades of history.
* **ETL (Chunking & Streaming)**: Stop using `pd.read_excel()` to load whole files. Instead, use columnar formats like Parquet and process rows in batches (e.g., 50,000 rows at a time). We also push heavy math (like calculating quarterly averages) down into the database engine rather than doing it in Python memory.
* **Worker Queue (Parallel Ingestion)**: Separate file parsing from database writes. Similar to how Kafka partitions events, multiple background workers can clean and validate different departments in parallel.

---

## Question 2: Daily API Ingestion & Handling Historical Changes

This scenario is very common with government feeds: an upstream department updates last year's headcount, but analysts have already published reports based on the old numbers. You can't just overwrite the data.

* **1. Handling Updates & Keeping Data Clean**:
  * **Never use hard `UPDATE` or `DELETE`**: Use an append-only versioning model (`valid_from`, `is_current`). When a historical record changes, we insert the new number as the current active version, but keep the old record intact for audit trails.
  * **Reuse our Dead-Letter Queue (DLQ)**: If the daily feed sends unexpected department names or unconvertible raw headcounts, route them into quarantine, flag an alert, and let the rest of the clean data finish loading.
* **2. Helping Analysts Work Without Surprises**:
  * **Time-Travel Querying**: Add an optional `?as_of=2024-01-01` parameter to our API. Analysts who need to verify or reproduce an old report get the numbers as they were back then; new models get the latest corrected figures by default.
  * **Daily Diff Notifications**: Send analysts a daily summary email or Slack/Teams note highlighting what changed (e.g., *"DND 2023 Q2 FTE revised from 120 to 115"*).
* **3. Reviewing a Teammate's PR (Priority Order)**:
  * **P0 - Idempotency & Immutability**: If the sync script runs twice by mistake, does it corrupt the database? Does it accidentally overwrite old historical data?
  * **P1 - Network Failures & Retries**: External APIs go down constantly. Does the code have proper timeouts and exponential backoff, or will it freeze the worker?
  * **P2 - Data Validation & DLQ**: Does it reuse our cleaning pipeline, or does bad data break the whole sync job?
  * **P3 - Logging**: Are we logging exactly how many rows were added, updated, or skipped for easy debugging?

---

## Question 3: Making Analysts' Lives Easier (Power BI & Python)

Analysts shouldn't have to write messy boilerplate code or clean up nested JSON just to build a chart.

* **For Python Analysts**:
  * Ship a tiny, installable library (`pip install pbo-workforce`). Instead of dealing with API requests and JSON wrangling, they run `pbo.get_fte(dept="DND", year=2023)` and immediately get a clean pandas DataFrame ready for analysis.
* **For Power BI Users**:
  * Don't make them parse nested JSON hierarchies. Create a flat SQL reporting view (`vw_workforce_bi`) that they can connect to directly via DirectQuery or OData, making drag-and-drop dashboards effortless.
* **Clear Data Definitions**:
  * Provide a clear data dictionary endpoint so analysts don't have to guess what "indeterminate" includes or how military headcounts were converted to FTEs.