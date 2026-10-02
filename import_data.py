"""
Data ingestion and ETL pipeline orchestration script.

Executes end-to-end data processing:
1. Schema initialization (safe create_all, non-destructive).
2. Transactional ingestion of the canonical Departments dimension table with fallback.
3. Multi-sheet dynamic ingestion with automated cleaning and bilingual entity reconciliation.
4. Aggregation of monthly snapshots into quarterly arithmetic means.
5. Batch loading of dimension and fact records into the relational database.
"""

import argparse
import logging
import os
import sys
from typing import Dict, List
import pandas as pd
from app.database import Base, SessionLocal, engine
from app.models import Department, QuarterlyFte
from app.pipeline import DataCleaningPipeline

# Logging persistent (sys.stdout and pipeline.log)
LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

logger = logging.getLogger("ETL_Pipeline")
logger.setLevel(logging.INFO)

if not logger.handlers:
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler("pipeline.log", mode="a", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    logger.addHandler(file_handler)


def run_import(excel_path: str = "data.xlsx", reset_schema: bool = False) -> None:
    """
    Execute the end-to-end ETL workflow to populate the workforce database.

    Args:
        excel_path (str): Relative or absolute path to the source Excel workbook.
        reset_schema (bool): If True, explicitly drops tables before re-creating.
                             Strictly disabled by default for production safety.

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

    logger.info("--> [1/4] Connecting to database and verifying schema...")
    if reset_schema:
        logger.warning("[Notice] Explicit schema reset requested. Dropping all tables...")
        Base.metadata.drop_all(bind=engine)

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # Atomic clean in one transaction with rollback protection
        deleted_facts = db.query(QuarterlyFte).delete()
        deleted_depts = db.query(Department).delete()
        if deleted_facts > 0 or deleted_depts > 0:
            logger.info(
                "[Clean] Flushed existing records (%d facts, %d depts) for fresh ingestion.",
                deleted_facts,
                deleted_depts,
            )

        logger.info("--> [2/4] Reading Excel workbook: %s ...", excel_path)
        xls = pd.ExcelFile(excel_path)

        # 1. Ingest and deduplicate canonical Departments dimension
        dept_sheet = pd.read_excel(xls, sheet_name="Departments")

        # Fallback hierarchy: prioritize long_name_en; fallback to French name or acronym to prevent empty deduplication
        dept_sheet["clean_long_name_en"] = (
            dept_sheet["long_name_en"]
            .fillna(dept_sheet.get("long_name_fr", pd.Series(dtype=object)))
            .fillna(dept_sheet.get("short_name_en", pd.Series(dtype=object)))
            .apply(DataCleaningPipeline.normalize_text)
        )

        # Remove completely blank rows
        dept_sheet = dept_sheet[dept_sheet["clean_long_name_en"] != ""].copy()

        # Deduplicate dimension rows based on normalized canonical identifier
        dept_sheet = dept_sheet.drop_duplicates(
            subset=["clean_long_name_en"], keep="first"
        ).reset_index(drop=True)

        departments_to_insert: List[Department] = []
        dept_id_map: Dict[str, int] = {}
        alias_map: Dict[str, str] = {}

        for idx, row in dept_sheet.iterrows():
            clean_en = row["clean_long_name_en"]
            dept_id = idx + 1

            name_fr = (
                str(row["long_name_fr"]).strip()
                if pd.notna(row.get("long_name_fr")) and str(row["long_name_fr"]).strip()
                else clean_en
            )
            short_en = (
                str(row["short_name_en"]).strip()
                if pd.notna(row.get("short_name_en")) and str(row["short_name_en"]).strip()
                else None
            )
            short_fr = (
                str(row["short_name_fr"]).strip()
                if pd.notna(row.get("short_name_fr")) and str(row["short_name_fr"]).strip()
                else None
            )

            dept_obj = Department(
                id=dept_id,
                long_name_en=clean_en,
                long_name_fr=name_fr,
                short_name_en=short_en,
                short_name_fr=short_fr,
            )
            departments_to_insert.append(dept_obj)
            dept_id_map[clean_en] = dept_id

            # Register bilingual names and official acronyms to resolve to clean canonical key
            alias_map[clean_en] = clean_en
            if name_fr:
                alias_map[name_fr] = clean_en
            if short_en:
                alias_map[short_en] = clean_en
            if short_fr:
                alias_map[short_fr] = clean_en

        db.bulk_save_objects(departments_to_insert)
        logger.info(
            "[OK] Prepared %d canonical departments (%d bilingual alias entries indexed).",
            len(departments_to_insert),
            len(alias_map),
        )

        # 2. Initialize cleaning pipeline with comprehensive alias registry
        pipeline = DataCleaningPipeline(
            canonical_departments=alias_map,
            similarity_cutoff=0.85,
        )

        # 3. Dynamic fact sheet discovery and ingestion adhering to accounting discipline
        logger.info("--> [3/4] Scanning and ingesting fact sheets dynamically...")
        DIMENSION_SHEETS = {"departments"}
        REQUIRED_DIMS = ["date", "tenure", "department"]
        frames: List[pd.DataFrame] = []

        for sheet_name in xls.sheet_names:
            if sheet_name.strip().lower() in DIMENSION_SHEETS:
                continue

            df = pd.read_excel(xls, sheet_name=sheet_name)
            df.columns = [str(c).strip().lower() for c in df.columns]

            missing_dims = [col for col in REQUIRED_DIMS if col not in df.columns]
            if missing_dims:
                logger.warning(
                    "Skipping sheet '%s': missing required dimensions %s.",
                    sheet_name,
                    missing_dims,
                )
                continue

            # Metric extraction branch
            if "fte" in df.columns:
                sub_df = df[REQUIRED_DIMS + ["fte"]].copy()
                sub_df["fte"] = pd.to_numeric(sub_df["fte"], errors="coerce").fillna(0.0)
                metric_desc = "'fte'"

            elif "headcount" in df.columns:
                sub_df = df[REQUIRED_DIMS + ["headcount"]].copy()
                sub_df["headcount"] = pd.to_numeric(sub_df["headcount"], errors="coerce").fillna(0.0)

                # Restrict 1:1 headcount-to-FTE conversion strictly to regular military/police 'combined' status
                norm_tenure = sub_df["tenure"].astype(str).str.strip().str.lower()
                is_combined = norm_tenure == "combined"

                sub_df["fte"] = 0.0
                sub_df.loc[is_combined, "fte"] = sub_df.loc[is_combined, "headcount"]

                # Audit quarantine: capture non-combined headcount to prevent unverified FTE inflation
                unconverted_mask = (~is_combined) & (sub_df["headcount"] > 0)
                if unconverted_mask.any():
                    unconverted_rows = sub_df[unconverted_mask]
                    for _, bad_row in unconverted_rows.iterrows():
                        pipeline.quarantine_unconverted_metric(
                            sheet_name=sheet_name,
                            department=str(bad_row["department"]),
                            tenure=str(bad_row["tenure"]),
                            headcount=float(bad_row["headcount"]),
                        )
                    logger.warning(
                        "[Quarantine Enqueued] Sheet '%s': %d records with "
                        "non-combined headcount quarantined to prevent unverified FTE inflation.",
                        sheet_name,
                        len(unconverted_rows),
                    )

                sub_df = sub_df.drop(columns=["headcount"])
                metric_desc = "'headcount' (restricted to 'combined' tenure only)"

            else:
                logger.warning(
                    "Skipping sheet '%s': neither 'fte' nor 'headcount' detected.",
                    sheet_name,
                )
                continue

            frames.append(sub_df)
            logger.info("Sheet '%s' processed via metric %s.", sheet_name, metric_desc)

        if not frames:
            raise ValueError("No valid fact sheets found in the provided Excel workbook.")

        unified_facts = pd.concat(frames, ignore_index=True)

        unified_facts["clean_dept"] = unified_facts["department"].apply(
            pipeline.resolve_department
        )
        unified_facts["clean_tenure"] = unified_facts["tenure"].apply(
            pipeline.normalize_tenure
        )

        # Export Dead-Letter Queue quarantine log for audit review
        pipeline.export_quarantine_report("data_quarantine.csv")

        # Link surrogate foreign keys from canonical dimension table
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
        logger.info(
            "--> [4/4] Writing %d quarterly aggregated rows to database...",
            len(pivoted),
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
        logger.info(
            "[OK] Successfully ingested %d fact sheets into 'workforce.db'.",
            len(frames),
        )

    except Exception as exc:
        db.rollback()
        logger.error("Pipeline execution failed: %s", exc, exc_info=True)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run workforce ETL data pipeline.")
    parser.add_argument("--path", default="data.xlsx", help="Path to data.xlsx source")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Force drop and recreate database schema (destructive).",
    )
    args = parser.parse_args()
    run_import(excel_path=args.path, reset_schema=args.reset)