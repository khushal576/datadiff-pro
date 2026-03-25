"""
core/validator.py

Post-transform validation: verifies that no source fields were silently
dropped during the mapping transformation.

After apply_mapping() runs, call validate_transform() to confirm that:
  * Every source field that was mapped was successfully found and moved.
  * Every source field that was NOT in any mapping rule still exists unchanged
    in the transformed data.
  * Any target-path collision that caused a merge is surfaced as a warning.

Public API
----------
validate_transform(
    original_data, transformed_data,
    mapping_pairs, map_traces,
    strict_mode=False,
) -> ValidationResult
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.path_resolver import collect_leaf_paths
from core.mapper import MapTrace


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """
    Result of validate_transform().

    Fields
    ------
    passed : bool
        True when no fatal errors were found.
    warnings : list[str]
        Non-fatal issues (e.g. merged collisions, missing-in-lenient-mode).
    errors : list[str]
        Fatal issues (e.g. dropped fields in strict mode).
    dropped_paths : list[str]
        Leaf paths that existed in original_data but are absent from
        transformed_data and were not part of any mapping rule.
    """
    passed: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dropped_paths: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def validate_transform(
    original_data: Any,
    transformed_data: Any,
    mapping_pairs: list[tuple[str, str]],
    map_traces: list[MapTrace],
    strict_mode: bool = False,
) -> ValidationResult:
    """
    Verify that no source fields were silently lost during mapping.

    Parameters
    ----------
    original_data : Any
        The data BEFORE apply_mapping was called (should be the deep-copy
        that apply_mapping received, or an equivalent snapshot).
    transformed_data : Any
        The data AFTER apply_mapping returned.
    mapping_pairs : list[tuple[str, str]]
        The (src_path, tgt_path) pairs that were passed to apply_mapping.
    map_traces : list[MapTrace]
        The traces returned by apply_mapping.
    strict_mode : bool
        When True, dropped unmapped fields are reported as errors (causing
        passed=False).  When False, they are reported as warnings only.

    Returns
    -------
    ValidationResult
    """
    result = ValidationResult()

    # ── Step 1: Collect all leaf paths in both snapshots ─────────────────
    original_leaves: set[str] = collect_leaf_paths(original_data)
    transformed_leaves: set[str] = collect_leaf_paths(transformed_data)

    # ── Step 2: Identify successfully mapped src paths ────────────────────
    # These were extracted from original_data and placed at new locations.
    # We should NOT check for their presence in transformed_data under the
    # original key — they moved.
    mapped_src_prefixes: set[str] = set()
    for trace in map_traces:
        if trace.action in ("renamed", "merged"):
            # Mark the declared source path as "accounted for".
            # We match leaf paths by prefix so "orders.id" covers
            # "orders.0.id", "orders.1.id", etc.
            mapped_src_prefixes.add(trace.src_path)

    # ── Step 3: Check for skipped_missing traces ──────────────────────────
    for trace in map_traces:
        if trace.action == "skipped_missing":
            msg = (
                f"Mapping rule {trace.rule_index + 1} — source path "
                f"'{trace.src_path}' was declared but not found in the data. "
                f"({trace.detail})"
            )
            if strict_mode:
                result.errors.append(msg)
            else:
                result.warnings.append(msg)

    # ── Step 4: Check merged collisions ──────────────────────────────────
    for trace in map_traces:
        if trace.action == "merged":
            result.warnings.append(
                f"Mapping rule {trace.rule_index + 1} — target path "
                f"'{trace.tgt_path}' already existed when "
                f"'{trace.src_path}' was mapped to it. "
                f"Values were merged (safe_insert). Verify this is intended."
            )

    # ── Step 5: Check for dropped unmapped fields ─────────────────────────
    # Any leaf in original_data that:
    #   a) is NOT covered by a mapped src_path prefix, AND
    #   b) is NOT present in transformed_data
    # has been silently dropped.
    for leaf in sorted(original_leaves):
        if _is_covered_by_mapping(leaf, mapped_src_prefixes):
            continue  # field was intentionally moved
        if leaf not in transformed_leaves:
            result.dropped_paths.append(leaf)
            msg = (
                f"Field '{leaf}' existed in the original data but is missing "
                f"from the transformed data and was not part of any mapping rule. "
                f"It may have been accidentally dropped."
            )
            if strict_mode:
                result.errors.append(msg)
            else:
                result.warnings.append(msg)

    result.passed = len(result.errors) == 0
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_covered_by_mapping(leaf_path: str, mapped_src_prefixes: set[str]) -> bool:
    """
    Return True if *leaf_path* is covered by any of the mapped source paths.

    A leaf path like "orders.0.id" is covered by the mapping prefix "orders.id"
    (the numeric index is stripped for comparison).

    We also check direct equality and prefix containment for non-indexed paths.
    """
    # Normalise: remove numeric segments (list indices) to get a pattern path.
    normalised_leaf = _strip_indices(leaf_path)

    for src_prefix in mapped_src_prefixes:
        # Direct match after normalisation
        if normalised_leaf == src_prefix:
            return True
        # The leaf is a child of the mapped prefix
        if normalised_leaf.startswith(src_prefix + "."):
            return True
        # The mapped prefix is a child of the leaf (the leaf is a parent container)
        if src_prefix.startswith(normalised_leaf + "."):
            return True

    return False


def _strip_indices(path: str) -> str:
    """
    Remove numeric index segments from a leaf path.

    "orders.0.id"   → "orders.id"
    "banks.2.nominees.1.name" → "banks.nominees.name"
    """
    parts = path.split(".")
    return ".".join(p for p in parts if not p.isdigit())
