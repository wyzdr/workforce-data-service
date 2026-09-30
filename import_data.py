"""
Data ingestion and ETL pipeline orchestration script.

Executes end-to-end data processing:
1. Schema initialization and reset for the Star Schema architecture.
2. Ingestion of the canonical Departments dimension table with deduplication.
3. Multi-sheet ingestion (FPS, RCMP, CAF) with automated cleaning and entity reconciliation.
4. Aggregation of monthly snapshots into quarterly arithmetic means.
5. Batch loading of dimension and fact records into the relational database.
"""

import os
from typing import Dict, List
import pandas as pd
from app.database import Base, SessionLocal, engine
from app.models import Department, QuarterlyFte
from app.pipeline import DataCleaningPipeline


def run_import(excel_path: str = "data.xlsx") -> None:
    """
    Execute the end-to-end ETL workflow to populate the workforce database.

    Args:
        excel_path (str): Relative or absolute path to the source Excel workbook.

    Raises:
        FileNotFoundError: If the source workbook cannot be located.
        Exception: Re-raises any database or ingestion error after rolling back.
    """
    # Adaptive path resolution: checks current working directory and data/ subfolder
    if not os.path.exists(excel_path):
        alt_path = os.path.join("data", excel_path)
        if os.path.exists(alt_path):
            excel_path = alt_path
        else:
            raise FileNotFoundError(
                f"Cannot find '{excel_path}'. Please ensure data.xlsx is in the root or data/ directory."
            )

    print("--> [1/4] Connecting to database and creating schema...")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        print(f"--> [2/4] Reading Excel workbook: {excel_path} ...")
        xls = pd.ExcelFile(excel_path)

        # 1. Ingest and deduplicate canonical Departments dimension
        dept_sheet = pd.read_excel(xls, sheet_name="Departments")
        dept_sheet["clean_long_name_en"] = dept_sheet["long_name_en"].apply(
            DataCleaningPipeline.normalize_text
        )

        # Eliminate dimension duplicate rows (e.g., duplicated CFIA entries in source data)
        dept_sheet = dept_sheet.drop_duplicates(
            subset=["clean_long_name_en"], keep="first"
        ).reset_index(drop=True)

        departments_to_insert: List[Department] = []
        dept_id_map: Dict[str, int] = {}

        for idx, row in dept_sheet.iterrows():
            clean_en = row["clean_long_name_en"]
            dept_id = idx + 1
            dept_obj = Department(
                id=dept_id,
                long_name_en=clean_en,
                long_name_fr=(
                    str(row["long_name_fr"]).strip()
                    if pd.notna(row["long_name_fr"])
                    else clean_en
                ),
                short_name_en=(
                    str(row["short_name_en"]).strip()
                    if pd.notna(row["short_name_en"])
                    else None
                ),
                short_name_fr=(
                    str(row["short_name_fr"]).strip()
                    if pd.notna(row["short_name_fr"])
                    else None
                ),
            )
            departments_to_insert.append(dept_obj)
            dept_id_map[clean_en] = dept_id

        db.bulk_save_objects(departments_to_insert)
        db.commit()
        print(
            f"    [OK] Successfully loaded {len(departments_to_insert)} canonical departments."
        )

        # 2. Initialize automated cleaning pipeline using canonical names as ground truth
        pipeline = DataCleaningPipeline(
            canonical_departments=list(dept_id_map.keys()),
            similarity_cutoff=0.85,
        )

        # 3. Read and unify workforce facts across FPS, RCMP, and CAF sheets
        print(
            "--> [3/4] Ingesting and unifying FPS, RCMP, and CAF fact sheets..."
        )
        fps_sheet = pd.read_excel(xls, sheet_name="Federal Public Service")
        fps_sheet["fte"] = (
            pd.to_numeric(fps_sheet["fte"], errors="coerce").fillna(0.0)
        )
        frames = [fps_sheet[["date", "tenure", "department", "fte"]]]

        # Incorporate RCMP and CAF workbooks (mapping active headcount 1:1 to FTE capacity)
        for sheet_name in ["RCMP", "CAF"]:
            if sheet_name in xls.sheet_names:
                extra_df = pd.read_excel(xls, sheet_name=sheet_name)
                extra_df["fte"] = (
                    pd.to_numeric(extra_df["headcount"], errors="coerce").fillna(0.0)
                )
                frames.append(extra_df[["date", "tenure", "department", "fte"]])

        unified_facts = pd.concat(frames, ignore_index=True)

        # Execute cleaning pipeline: fuzzy entity matching and tenure normalization
        unified_facts["clean_dept"] = unified_facts["department"].apply(
            pipeline.resolve_department
        )
        unified_facts["clean_tenure"] = unified_facts["tenure"].apply(
            pipeline.normalize_tenure
        )

        # Export dead-letter audit log if anomalies exist
        pipeline.export_quarantine_report("data_quarantine.csv")

        # Associate fact records with surrogate dimension foreign keys
        unified_facts["dept_id"] = unified_facts["clean_dept"].map(dept_id_map)
        valid_facts = unified_facts.dropna(subset=["dept_id"]).copy()
        valid_facts["dept_id"] = valid_facts["dept_id"].astype(int)

        # Temporal transformation: derive calendar year, month, and quarter
        date_str = valid_facts["date"].astype(str)
        valid_facts["year"] = date_str.str[:4].astype(int)
        valid_facts["month"] = date_str.str[4:6].astype(int)
        valid_facts["quarter"] = (valid_facts["month"] - 1) // 3 + 1

        # Aggregation: sum monthly FTE per tenure, then compute quarterly arithmetic mean
        monthly_tenure = (
            valid_facts.groupby(
                ["dept_id", "year", "quarter", "month", "clean_tenure"],
                as_index=False,
            )["fte"]
            .sum()
        )

        quarterly_agg = (
            monthly_tenure.groupby(
                ["dept_id", "year", "quarter", "clean_tenure"],
                as_index=False,
            )["fte"]
            .mean()
        )

        pivoted = quarterly_agg.pivot(
            index=["dept_id", "year", "quarter"],
            columns="clean_tenure",
            values="fte",
        ).reset_index()

        # Enforce presence of all five statutory tenure categories
        for col in ["indeterminate", "term", "casual", "student", "missing"]:
            if col not in pivoted.columns:
                pivoted[col] = 0.0
            else:
                pivoted[col] = pivoted[col].fillna(0.0)

        # 4. Batch persist quarterly aggregated records
        print(
            f"--> [4/4] Writing {len(pivoted)} quarterly aggregated rows to database..."
        )
        records = [
            QuarterlyFte(
                dept_id=int(r["dept_id"]),
                year=int(r["year"]),
                quarter=int(r["quarter"]),
                indeterminate=round(float(r["indeterminate"]), 2),
                term=round(float(r["term"]), 2),
                casual=round(float(r["casual"]), 2),
                student=round(float(r["student"]), 2),
                missing=round(float(r["missing"]), 2),
            )
            for _, r in pivoted.iterrows()
        ]
        db.bulk_save_objects(records)
        db.commit()
        print(
            "    [OK] All datasets (FPS + RCMP + CAF) processed and loaded into 'workforce.db'."
        )

    except Exception as exc:
        db.rollback()
        print(f"[Error] Pipeline execution failed: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_import()