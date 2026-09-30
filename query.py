"""
Database inspection and schema validation utility.

Queries the generated SQLite database to verify record counts,
inspect canonical department dimensions, and validate quarterly
FTE fact aggregations.
"""

import sqlite3
import pandas as pd

# Configure Pandas display settings to prevent output truncation
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 1000)

# Connect to the local workforce database
conn = sqlite3.connect("workforce.db")

print("=" * 60)
print("1. Record Count Summary:")
print("=" * 60)
depts_count = pd.read_sql(
    "SELECT COUNT(*) AS total_departments FROM departments", conn
)
fte_count = pd.read_sql(
    "SELECT COUNT(*) AS total_fte_records FROM quarterly_fte", conn
)
print(depts_count)
print(fte_count)

print("\n" + "=" * 60)
print("2. Departments Dimension Table (Sample Records):")
print("=" * 60)
df_depts = pd.read_sql(
    "SELECT id, long_name_en, short_name_en FROM departments LIMIT 20", conn
)
print(df_depts)

print("\n" + "=" * 60)
print("3. Quarterly FTE Fact Table (Department 1 Sample):")
print("=" * 60)
df_fte = pd.read_sql(
    """
    SELECT q.dept_id, d.short_name_en, q.year, q.quarter, 
           q.indeterminate, q.term, q.casual, q.student, q.missing
    FROM quarterly_fte q
    JOIN departments d ON q.dept_id = d.id
    WHERE q.dept_id = 1
    ORDER BY q.year, q.quarter
    LIMIT 28
    """,
    conn,
)
print(df_fte)

conn.close()