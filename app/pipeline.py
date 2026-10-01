"""
Data cleaning and reconciliation pipeline module.

Provides resilient ETL preprocessing mechanisms:
1. Dynamic canonical reference loading without hardcoded aliases.
2. Multi-tier department reconciliation (exact, memoized, fuzzy matching via Levenshtein distance).
3. Dead-Letter Queue (DLQ) quarantine tracking for low-confidence or unmapped records.
4. Domain-driven tenure category normalization conforming to PBO API data contracts.
"""

import difflib
import os
import re
from typing import Any, Dict, List, Optional, Union
import pandas as pd


class DataCleaningPipeline:
    """
    Automated data cleaning and entity resolution pipeline.

    Attributes:
        canonical_map (Dict[str, str]): Normalized search key to canonical name mapping.
        canonical_keys (List[str]): List of normalized canonical keys used for similarity search.
        cutoff (float): Minimum similarity ratio required to accept a fuzzy match.
        match_cache (Dict[str, Optional[str]]): Memoization table caching previous resolutions.
        quarantine_records (List[Dict]): Dead-Letter Queue preserving unresolvable inputs.
    """

    def __init__(
        self,
        canonical_departments: Union[List[str], Dict[str, str]],
        similarity_cutoff: float = 0.85,
    ) -> None:
        """
        Initialize the cleaning pipeline with ground-truth department references.

        Args:
            canonical_departments (Union[List[str], Dict[str, str]]): 
                Either a list of canonical names, or a dictionary mapping aliases
                (e.g., French names, acronyms) directly to the canonical English entity name.
            similarity_cutoff (float): Fuzzy matching threshold between 0.0 and 1.0 (default 0.85).
        """
        self.cutoff = similarity_cutoff
        self.canonical_map: Dict[str, str] = {}

        if isinstance(canonical_departments, dict):
            for alias, canonical_name in canonical_departments.items():
                norm_alias = self.normalize_text(alias)
                if norm_alias:
                    self.canonical_map[norm_alias] = canonical_name
        else:
            for name in canonical_departments:
                norm_name = self.normalize_text(name)
                if norm_name:
                    self.canonical_map[norm_name] = name

        self.canonical_keys = list(self.canonical_map.keys())

        # In-memory resolution cache preventing redundant Levenshtein distance calculations
        self.match_cache: Dict[str, Optional[str]] = {}

        # Quarantine log (Dead-Letter Queue) for human-in-the-loop review
        self.quarantine_records: List[Dict[str, Any]] = []

    @staticmethod
    def normalize_text(text: Any) -> str:
        """
        Standardize raw text inputs.

        Collapses multiple contiguous whitespaces, trims leading/trailing spaces,
        and safely handles null or non-string representations.

        Args:
            text (Any): Input object or string.

        Returns:
            str: Cleaned, single-spaced string.
        """
        if pd.isna(text):
            return ""
        return re.sub(r"\s+", " ", str(text)).strip()

    def resolve_department(self, raw_name: Any) -> Optional[str]:
        """
        Resolve an incoming organization string against canonical department entities.

        Resolution Strategy:
        1. Exact Match: Immediate lookup against canonical key set (supports aliases).
        2. Cache Lookup: Check memoized resolutions for repetitive dirty inputs.
        3. Fuzzy Match: Compute token similarity using difflib with threshold cutoff.
        4. Quarantine (DLQ): Log unresolved anomalies for auditor review and return None.

        Args:
            raw_name (Any): Raw organization name from input fact record.

        Returns:
            Optional[str]: Canonical department long name, or None if quarantined.
        """
        norm_name = self.normalize_text(raw_name)
        if not norm_name:
            return None

        # Tier 1: Exact match against normalized alias/name dictionary
        if norm_name in self.canonical_map:
            return self.canonical_map[norm_name]

        # Tier 2: Cache lookup (covers previously resolved matches or previous failures)
        if norm_name in self.match_cache:
            return self.match_cache[norm_name]

        # Tier 3: Fuzzy matching (Levenshtein distance heuristic)
        matches = difflib.get_close_matches(
            norm_name, self.canonical_keys, n=1, cutoff=self.cutoff
        )
        if matches:
            best_match_key = matches[0]
            resolved = self.canonical_map[best_match_key]
            self.match_cache[norm_name] = resolved
            return resolved

        # Tier 4: Dead-Letter Queue quarantine registration
        self.match_cache[norm_name] = None
        self.quarantine_records.append(
            {
                "field": "department",
                "raw_value": raw_name,
                "normalized_value": norm_name,
                "reason": "Low similarity / Unknown entity",
            }
        )
        return None

    def quarantine_unconverted_metric(
        self,
        sheet_name: str,
        department: str,
        tenure: str,
        headcount: float,
    ) -> None:
        """
        Log unconverted headcount records to the Dead-Letter Queue.

        Enforces public sector accounting discipline: non-permanent headcounts
        (term, casual, student) cannot be converted 1:1 to FTE without statutory ratios.

        Args:
            sheet_name (str): Originating Excel worksheet.
            department (str): Raw department name.
            tenure (str): Unconverted tenure category.
            headcount (float): Non-zero headcount value blocked from FTE mapping.
        """
        self.quarantine_records.append(
            {
                "field": "headcount_unconverted",
                "raw_value": f"headcount={headcount}, tenure={tenure}",
                "normalized_value": self.normalize_text(department),
                "reason": (
                    f"Sheet '{sheet_name}': Non-combined headcount cannot be mapped "
                    "to FTE without statutory conversion ratio"
                ),
            }
        )

    @staticmethod
    def normalize_tenure(tenure: Any) -> str:
        """
        Map incoming employment status into the five statutory API tenure categories.

        Enforces strict schema compliance:
        - Maps military/police 'Combined' status to permanent 'indeterminate'.
        - Maps nulls or unrecognized values to 'missing'.

        Args:
            tenure (Any): Raw employment tenure label from dataset.

        Returns:
            str: One of {'indeterminate', 'term', 'casual', 'student', 'missing'}.
        """
        if pd.isna(tenure):
            return "missing"

        val = str(tenure).strip().lower()

        # Business decision: regular military & RCMP service members carry permanent career tenure
        if val == "combined":
            return "indeterminate"

        valid_set = {"indeterminate", "term", "casual", "student", "missing"}
        return val if val in valid_set else "missing"

    def export_quarantine_report(
        self, filepath: str = "data_quarantine.csv"
    ) -> None:
        """
        Export quarantined dead-letter records to CSV for human-in-the-loop review.
        If no quarantine records exist, remove legacy quarantine file if present.

        Args:
            filepath (str): Destination file path for quarantine audit log.
        """
        if self.quarantine_records:
            df = pd.DataFrame(self.quarantine_records).drop_duplicates()
            df.to_csv(filepath, index=False, encoding="utf-8-sig")
            print(
                f"    [Quarantine Alert] {len(df)} unmatched or unconverted records preserved in '{filepath}' for audit review."
            )
        else:
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError:
                    pass
            print(
                "    [Pipeline Clean] 100% records successfully matched against canonical dimension."
            )