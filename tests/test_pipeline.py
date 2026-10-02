"""
Unit tests for data cleaning, normalization, and entity reconciliation pipeline.
Covers real-world whitespace defects, bilingual aliases, and DLQ quarantine flows.
"""

import os
import pytest
from app.pipeline import DataCleaningPipeline


@pytest.fixture
def sample_pipeline():
    """Initialize a pipeline instance with bilingual aliases, acronyms, and real-world entities."""
    canonical_dict = {
        "Department of Finance": "Department of Finance",
        "Ministère des Finances": "Department of Finance",
        "FIN": "Department of Finance",
        "Accessibility Standards Canada": "Accessibility Standards Canada",
        "Normes d'accessibilité Canada": "Accessibility Standards Canada",
        "ASC": "Accessibility Standards Canada",
        # Real-world target departments from dataset
        "Public Service Commission of Canada": "Public Service Commission of Canada",
        "Commission de la fonction publique du Canada": "Public Service Commission of Canada",
        "PSC": "Public Service Commission of Canada",
        "Office of the Commissioner for Federal Judicial Affairs Canada": "Office of the Commissioner for Federal Judicial Affairs Canada",
        "FJA": "Office of the Commissioner for Federal Judicial Affairs Canada",
        "Canadian Food Inspection Agency": "Canadian Food Inspection Agency",
        "Agence canadienne d’inspection des aliments": "Canadian Food Inspection Agency",
        "CFIA": "Canadian Food Inspection Agency",
        "Privy Council Office": "Privy Council Office",
        "Bureau du Conseil privé": "Privy Council Office",
        "PCO": "Privy Council Office",
    }
    return DataCleaningPipeline(canonical_departments=canonical_dict, similarity_cutoff=0.8)


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
# 2. Entity Resolution & Real-world Anomaly Tests
# ==============================================================================

def test_resolve_exact_match(sample_pipeline):
    """Verify Tier 1 exact resolution matches canonical entity directly."""
    result = sample_pipeline.resolve_department("Department of Finance")
    assert result == "Department of Finance"


def test_resolve_bilingual_and_acronym_aliases(sample_pipeline):
    """Verify resolution of French names and acronyms to canonical English entity."""
    # French entity name
    assert sample_pipeline.resolve_department("Normes d'accessibilité Canada") == "Accessibility Standards Canada"
    # Acronym
    assert sample_pipeline.resolve_department("ASC") == "Accessibility Standards Canada"
    assert sample_pipeline.resolve_department("FIN") == "Department of Finance"


def test_resolve_real_world_whitespace_anomalies(sample_pipeline):
    """
    Verify reconciliation of known defects from source dataset:
    1. 'Public Service  Commission of Canada' -> internal double whitespace
    2. ' Office of the Commissioner for Federal Judicial Affairs Canada' -> leading space
    """
    dirty_psc = "Public Service  Commission of Canada"
    assert sample_pipeline.resolve_department(dirty_psc) == "Public Service Commission of Canada"

    dirty_fja = " Office of the Commissioner for Federal Judicial Affairs Canada"
    assert sample_pipeline.resolve_department(dirty_fja) == "Office of the Commissioner for Federal Judicial Affairs Canada"


def test_resolve_cfia_acronym_and_bilingual(sample_pipeline):
    """Verify CFIA resolves accurately via acronym and French name."""
    assert sample_pipeline.resolve_department("CFIA") == "Canadian Food Inspection Agency"
    assert sample_pipeline.resolve_department("Agence canadienne d’inspection des aliments") == "Canadian Food Inspection Agency"


def test_resolve_fuzzy_match_and_memoization(sample_pipeline):
    """
    Verify Tier 3 fuzzy matching reconciles typos and verifies Tier 2 memoization cache.
    Includes real-world raw typo 'Privy Council Officee'.
    """
    # 1. Typo of 'Privy Council Officee'
    pco_typo = "Privy Council Officee"
    resolved_pco = sample_pipeline.resolve_department(pco_typo)
    assert resolved_pco == "Privy Council Office"
    assert "privy council officee" in sample_pipeline.match_cache

    # 2. Missing trailing letters
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

    assert result is None
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

def test_quarantine_unconverted_metric(sample_pipeline):
    """Verify non-combined headcount records are properly enqueued in DLQ."""
    sample_pipeline.quarantine_unconverted_metric(
        sheet_name="TestSheet",
        department="Department of Finance",
        tenure="casual",
        headcount=15.0,
    )
    assert len(sample_pipeline.quarantine_records) == 1
    record = sample_pipeline.quarantine_records[0]
    assert record["field"] == "headcount_unconverted"
    assert "headcount=15.0" in record["raw_value"]
    assert "casual" in record["raw_value"]


def test_export_quarantine_report(sample_pipeline, tmp_path):
    """Verify DLQ audit trail CSV export capability."""
    sample_pipeline.resolve_department("Fictional Ministry of Magic")
    
    export_file = tmp_path / "test_quarantine.csv"
    sample_pipeline.export_quarantine_report(filepath=str(export_file))

    assert os.path.exists(export_file)
    with open(export_file, "r", encoding="utf-8-sig") as f:
        content = f.read()
        assert "Fictional Ministry of Magic" in content