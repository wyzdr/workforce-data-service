"""
Database models defining the Star Schema for federal workforce data.

Includes:
- Department: Dimension entity storing official bilingual names and acronyms.
- QuarterlyFte: Fact entity storing quarterly averaged FTE metrics across
  the five statutory tenure categories.
"""

from sqlalchemy import Column, Integer, String, Float, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.database import Base


class Department(Base):
    """
    Department dimension model representing a federal government organization.

    Conforms to the Official Languages Act by persisting both English and
    French long names and abbreviations.
    """

    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    long_name_en = Column(String, unique=True, nullable=False, index=True)
    long_name_fr = Column(String, nullable=False)
    short_name_en = Column(String, nullable=True)
    short_name_fr = Column(String, nullable=True)

    # 1-to-many relationship linking department to quarterly FTE facts
    quarterly_records = relationship(
        "QuarterlyFte",
        back_populates="department",
        cascade="all, delete-orphan",
    )


class QuarterlyFte(Base):
    """
    Quarterly FTE fact model representing historical workforce capacity.

    Stores the arithmetic mean of reported monthly FTE values across
    five standardized tenure categories per quarter.
    """

    __tablename__ = "quarterly_fte"

    id = Column(Integer, primary_key=True, index=True)
    dept_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    year = Column(Integer, nullable=False)
    quarter = Column(Integer, nullable=False)  # Calendar quarters 1 through 4

    # Statutory tenure categories (FTE monthly arithmetic mean)
    indeterminate = Column(Float, default=0.0, nullable=False)
    term = Column(Float, default=0.0, nullable=False)
    casual = Column(Float, default=0.0, nullable=False)
    student = Column(Float, default=0.0, nullable=False)
    missing = Column(Float, default=0.0, nullable=False)

    department = relationship("Department", back_populates="quarterly_records")

    # Composite index optimizing range scans for department-specific temporal queries
    __table_args__ = (
        Index("idx_dept_year_quarter", "dept_id", "year", "quarter"),
    )