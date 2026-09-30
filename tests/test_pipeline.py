import os
import pytest
from app.pipeline import DataCleaningPipeline


@pytest.fixture
def sample_pipeline():
    """Initialize a pipeline instance with canonical government departments."""
    canonical_depts = [
        "Department of Finance",
        "Treasury Board of Canada Secretariat",
        "Accessibility Standards Canada",
    ]
    return DataCleaningPipeline(canonical_departments=canonical_depts, similarity_cutoff=0.8)


# ==============================================================================
# 1. Text Normalization Tests
# ==============================================================================

def test_normalize_text_whitespace():
    """Verify that multiple whitespace characters and trailing spaces are collapsed."""
    assert DataCleaningPipeline.normalize_text("  Department   of    Finance  ") == "Department of Finance"


def test_normalize_text_none_and_nan():
    """Verify safe handling of null, NaN, and non-string inputs."""
    assert DataCleaningPipeline.normalize_text(None) == ""
    assert DataCleaningPipeline.normalize_text(float("nan")) == ""
    assert DataCleaningPipeline.normalize_text(12345) == "12345"


# ==============================================================================
# 2. Entity Resolution & Fuzzy Matching Tests
# ==============================================================================

def test_resolve_exact_match(sample_pipeline):
    """Verify Tier 1 exact resolution matches canonical entity directly."""
    result = sample_pipeline.resolve_department("Department of Finance")
    assert result == "Department of Finance"


def test_resolve_fuzzy_match_and_memoization(sample_pipeline):
    """Verify Tier 3 fuzzy matching reconciles typos and verifies Tier 2 memoization cache."""
    typo_name = "Department of Financ"  # Slight typo
    
    # First invocation: fuzzy matching via difflib
    resolved = sample_pipeline.resolve_department(typo_name)
    assert resolved == "Department of Finance"
    assert typo_name in sample_pipeline.match_cache

    # Second invocation: hits memoization cache
    cached_result = sample_pipeline.resolve_department(typo_name)
    assert cached_result == "Department of Finance"


def test_resolve_unmatched_and_dead_letter_queue(sample_pipeline):
    """Verify Tier 4 unresolvable entities are routed to the Dead-Letter Queue."""
    unknown_dept = "Unknown Ghost Agency 999"
    result = sample_pipeline.resolve_department(unknown_dept)

    # Resolution should safely yield None
    assert result is None

    # DLQ quarantine records must track the anomaly
    assert len(sample_pipeline.quarantine_records) == 1
    quarantined = sample_pipeline.quarantine_records[0]
    assert quarantined["field"] == "department"
    assert quarantined["raw_value"] == unknown_dept


def test_resolve_empty_string(sample_pipeline):
    """Verify empty input strings immediately return None without quarantine error."""
    assert sample_pipeline.resolve_department("") is None
    assert sample_pipeline.resolve_department("   ") is None


# ==============================================================================
# 3. Employment Tenure Normalization Tests
# ==============================================================================

@pytest.mark.parametrize(
    "raw_input, expected",
    [
        ("indeterminate", "indeterminate"),
        ("TERM", "term"),
        ("casual", "casual"),
        ("student", "student"),
        ("missing", "missing"),
        ("combined", "indeterminate"),  # Domain rule: military/police combined tenure
        (None, "missing"),
        ("invalid_status_xyz", "missing"),
    ],
)
def test_normalize_tenure_categories(raw_input, expected):
    """Verify statutory employment tenure standardization conforming to PBO contracts."""
    assert DataCleaningPipeline.normalize_tenure(raw_input) == expected


# ==============================================================================
# 4. Audit & Quarantine Reporting Tests
# ==============================================================================

def test_export_quarantine_report(sample_pipeline, tmp_path):
    """Verify DLQ audit trail CSV export capability."""
    # Populate quarantine records
    sample_pipeline.resolve_department("Fictional Ministry of Magic")
    
    export_file = tmp_path / "test_quarantine.csv"
    sample_pipeline.export_quarantine_report(filepath=str(export_file))

    assert os.path.exists(export_file)
    with open(export_file, "r", encoding="utf-8-sig") as f:
        content = f.read()
        assert "Fictional Ministry of Magic" in content