"""
Pydantic schemas and Data Transfer Objects (DTOs).

Defines serialization contracts and validation schemas for API responses,
ensuring strict compliance with official bilingual public service standards
and statutory employment tenure classifications.
"""

from typing import Any, Dict, List
from pydantic import BaseModel, ConfigDict


class BilingualText(BaseModel):
    """
    Dual-language atomic container.

    Enforces the presence of both English and French text to comply with
    the Official Languages Act requirements for federal services.
    """

    en: str
    fr: str


class DepartmentItem(BaseModel):
    """
    Representation of a single federal organization in API responses.

    Attributes:
        dept_id: Internal primary key identifier.
        dept_long: Official full name in both official languages.
        dept_short: Standardized acronym/abbreviation in both official languages.
    """

    dept_id: int
    dept_long: BilingualText
    dept_short: BilingualText

    # Pydantic V2 configuration supporting ORM attribute extraction
    model_config = ConfigDict(from_attributes=True)


class DepartmentListResponse(BaseModel):
    """
    Payload contract for the GET /api/departments endpoint.
    """

    departments: List[DepartmentItem]


class QuarterlyFteItem(BaseModel):
    """
    Analytical FTE record per department, calendar year, and quarter.

    Enforces strict typing across all five statutory tenure classifications.
    """

    year: int
    quarter: int
    indeterminate: float = 0.0
    term: float = 0.0
    casual: float = 0.0
    student: float = 0.0
    missing: float = 0.0

    model_config = ConfigDict(from_attributes=True)


class DepartmentFteResponse(BaseModel):
    """
    Payload contract for the GET /api/departments/{id}/fte endpoint.

    Uses a dynamic dictionary list to accommodate query-parameter-driven
    field projections (e.g., pruning non-requested tenures when ?tenure= is specified).
    """

    fte_per_quarter: List[Dict[str, Any]]