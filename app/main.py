"""
Main application module for the PBO Workforce Data Service.

Provides RESTful API endpoints for retrieving federal departments' metadata
and quarterly full-time equivalent (FTE) workforce analytics, with production-grade
request logging and persistent audit tracking.
"""

import logging
import sys
import time
import traceback
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import asc, text
from app.database import get_db
from app.models import Department, QuarterlyFte
from app.schemas import (
    DepartmentListResponse,
    DepartmentItem,
    BilingualText,
    DepartmentFteResponse,
)

# ==============================================================================
# Persistent Logging Configuration (Dual: Console + File)
# ==============================================================================
LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

api_logger = logging.getLogger("API_Audit")
api_logger.setLevel(logging.INFO)

if not api_logger.handlers:
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    api_logger.addHandler(stream_handler)

    # 2. Local persistent
    file_handler = logging.FileHandler("api_access.log", mode="a", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    api_logger.addHandler(file_handler)


app = FastAPI(
    title="PBO Workforce Data Service",
    description="A robust REST API providing dual-language workforce data and quarterly FTE analytics.",
    version="1.0.0",
)


# ==============================================================================
# Request & Audit Logging Middleware
# ==============================================================================
@app.middleware("http")
async def audit_logging_middleware(request: Request, call_next):
    """
    Audit and trace every incoming HTTP request:
    Captures method, full URL, status code, latency, and flags client/server anomalies.
    """
    start_time = time.time()
    client_ip = request.client.host if request.client else "unknown"
    method = request.method
    full_url = str(request.url)

    try:
        response = await call_next(request)
        duration_ms = round((time.time() - start_time) * 1000, 2)
        status_code = response.status_code

        if status_code >= 500:
            api_logger.error(
                f"[SERVER ERROR] {client_ip} | {method} {full_url} -> Status {status_code} ({duration_ms}ms)"
            )
        elif status_code >= 400:
            api_logger.warning(
                f"[CLIENT ANOMALY] {client_ip} | {method} {full_url} -> Status {status_code} ({duration_ms}ms)"
            )
        else:
            api_logger.info(
                f"[OK] {client_ip} | {method} {full_url} -> Status {status_code} ({duration_ms}ms)"
            )

        return response

    except Exception as exc:
        duration_ms = round((time.time() - start_time) * 1000, 2)
        api_logger.critical(
            f"[UNHANDLED EXCEPTION] {client_ip} | {method} {full_url} ({duration_ms}ms): {str(exc)}\n"
            f"{traceback.format_exc()}"
        )
        raise exc


# ==============================================================================
# Endpoints
# ==============================================================================
@app.get("/", include_in_schema=False)
def root_redirect():
    """Redirect incoming root traffic directly to interactive OpenAPI documentation."""
    return RedirectResponse(url="/docs")


@app.get(
    "/api/departments",
    response_model=DepartmentListResponse,
    tags=["Departments"],
)
def get_departments(db: Session = Depends(get_db)):
    """
    Retrieve all federal departments with bilingual names and acronyms.

     Args:
         db (Session): Database session dependency.

     Returns:
         DepartmentListResponse: A list of all registered departments ordered by ID.
    """
    departments = db.query(Department).order_by(asc(Department.id)).all()
    result = [
        DepartmentItem(
            dept_id=d.id,
            dept_long=BilingualText(en=d.long_name_en, fr=d.long_name_fr),
            dept_short=BilingualText(
                en=d.short_name_en or "", fr=d.short_name_fr or ""
            ),
        )
        for d in departments
    ]
    return DepartmentListResponse(departments=result)


@app.get(
    "/api/departments/{id}/fte",
    response_model=DepartmentFteResponse,
    tags=["Workforce FTE"],
)
def get_department_fte(
    id: int,
    year: Optional[int] = Query(
        None, description="Filter records by specific calendar year (e.g., 2021)"
    ),
    tenure: Optional[str] = Query(
        None,
        description="Filter records by tenure type (indeterminate, term, casual, student, missing)",
    ),
    db: Session = Depends(get_db),
):
    """
    Retrieve quarterly FTE breakdown for a specific department.
    Supports optional filtering by calendar year and employment tenure category.

     Args:
     id (int): Department primary key ID.
     year (Optional[int]): Target calendar year for filtering.
     tenure (Optional[str]): Standard tenure category for projection filtering.
     db (Session): Database session dependency.

 Raises:
     HTTPException: 404 if the department ID does not exist.
     HTTPException: 400 if an invalid tenure category is specified.

 Returns:
     DepartmentFteResponse: Array of quarterly FTE metrics.
    """
    # Verify department existence
    dept = db.query(Department).filter(Department.id == id).first()
    if not dept:
        raise HTTPException(
            status_code=404,
            detail=f"Department with ID {id} not found.",
        )

    # Base query for department quarterly records
    query = db.query(QuarterlyFte).filter(QuarterlyFte.dept_id == id)

    # Apply optional year filter
    if year is not None:
        query = query.filter(QuarterlyFte.year == year)

    records = (
        query.order_by(asc(QuarterlyFte.year), asc(QuarterlyFte.quarter)).all()
    )

    # Validate and apply optional tenure filter
    valid_tenures = {"indeterminate", "term", "casual", "student", "missing"}
    target_tenure = tenure.strip().lower() if tenure else None

    if target_tenure and target_tenure not in valid_tenures:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tenure filter '{tenure}'. Valid options are: {', '.join(sorted(valid_tenures))}",
        )

    fte_list = []
    for r in records:
        if target_tenure:
            # Field projection: return only year, quarter, and the requested tenure
            entry = {
                "year": r.year,
                "quarter": r.quarter,
                target_tenure: getattr(r, target_tenure),
            }
        else:
            # Full contract: return all five statutory tenure categories
            entry = {
                "year": r.year,
                "quarter": r.quarter,
                "indeterminate": r.indeterminate,
                "term": r.term,
                "casual": r.casual,
                "student": r.student,
                "missing": r.missing,
            }
        fte_list.append(entry)

    return DepartmentFteResponse(fte_per_quarter=fte_list)


# ------------------------------------------------------------------------------
# Monitoring
# ------------------------------------------------------------------------------
@app.get("/health/live", tags=["Monitoring"])
def liveness_probe():
    """
    Kubernetes / Azure App Service Liveness Probe.
    Verifies that the application process is running and responsive.
    """
    return {"status": "alive"}


@app.get("/health/ready", tags=["Monitoring"])
def readiness_probe(db: Session = Depends(get_db)):
    """
    Kubernetes / Azure App Service Readiness Probe.
    Verifies active database connectivity before directing traffic to the instance.
    """
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}
    except Exception as exc:
        api_logger.error(f"Readiness probe DB check failed: {str(exc)}")
        raise HTTPException(
            status_code=503,
            detail=f"Database connectivity check failed: {str(exc)}",
        )

