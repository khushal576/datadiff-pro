"""
core/mapper.py

Renames / remaps fields in a normalised Python dict before diffing.

The user pastes a simple CSV-style mapping in the UI:
    source_path,target_path
    banks,BankData
    user.address.city,person.location.city

This module parses that text, validates it, and applies the renames to a
dict so that the diff engine always sees matching field names on both sides.

Public API
----------
parse_mapping(mapping_csv: str) -> tuple[list[tuple[str,str]], str | None]
    Parse the raw CSV text into a list of (source_path, target_path) pairs.

apply_mapping(data, pairs) -> any
    Walk *data* and rename fields according to the pairs.
"""

from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def parse_mapping(mapping_csv: str) -> tuple[list[tuple[str, str]], str | None]:
    """
    Parse the user-supplied CSV mapping text.

    Expected format (one mapping per line, blank lines and # comments ignored):
        source_path,target_path

    Returns
    -------
    (pairs, error)
        pairs — list of (source_path, target_path) strings, or [] on failure
        error — human-readable error string, or None on success
    """
    if not mapping_csv or not mapping_csv.strip():
        return [], None  # empty mapping is fine — nothing to remap

    pairs: list[tuple[str, str]] = []
    errors: list[str] = []

    for line_num, raw_line in enumerate(mapping_csv.splitlines(), start=1):
        line = raw_line.strip()

        # Skip blank lines and comments
        if not line or line.startswith("#"):
            continue

        parts = line.split(",")
        if len(parts) < 2:
            errors.append(
                f"Line {line_num}: missing target path — "
                f"expected 'source,target' but got: {repr(line)}"
            )
            continue
        if len(parts) > 2:
            errors.append(
                f"Line {line_num}: too many commas — "
                f"each line must have exactly one comma separating source and "
                f"target. Got: {repr(line)}"
            )
            continue

        source = parts[0].strip()
        target = parts[1].strip()

        if not source:
            errors.append(f"Line {line_num}: source path is empty.")
            continue
        if not target:
            errors.append(f"Line {line_num}: target path is empty.")
            continue

        # Validate that each segment of the dot-notation path is non-empty
        src_err = _validate_path(source, "source", line_num)
        tgt_err = _validate_path(target, "target", line_num)
        if src_err:
            errors.append(src_err)
            continue
        if tgt_err:
            errors.append(tgt_err)
            continue

        pairs.append((source, target))

    if errors:
        return [], (
            "Field mapping has the following errors:\n"
            + "\n".join(f"  • {e}" for e in errors)
        )

    return pairs, None


def _validate_path(path: str, role: str, line_num: int) -> str | None:
    """Return an error string if *path* contains invalid dot-notation segments."""
    segments = path.split(".")
    for seg in segments:
        if not seg:
            return (
                f"Line {line_num}: {role} path '{path}' has an empty segment "
                f"(double dot or leading/trailing dot)."
            )
    return None


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def apply_mapping(
    data: Any,
    pairs: list[tuple[str, str]],
) -> Any:
    """
    Apply field renames to *data* according to *pairs*.

    *data* is deep-copied first so the original is never mutated.

    Each pair is (source_path, target_path) using dot notation.
    Example: ("user.address.city", "person.location.city")

    How it works:
    - Navigate to the parent of the leaf key using the source path.
    - Remove the old key, insert the new key with the same value.
    - If a path segment points to a list of dicts, the rename is applied to
      every item in the list.

    If a source path does not exist in *data* the pair is silently skipped
    (the data may legitimately be missing that field).
    """
    data = copy.deepcopy(data)
    for source_path, target_path in pairs:
        src_segments = source_path.split(".")
        tgt_segments = target_path.split(".")
        data = _apply_single(data, src_segments, tgt_segments)
    return data


def _apply_single(
    data: Any,
    src_segs: list[str],
    tgt_segs: list[str],
) -> Any:
    """
    Recursively walk *data* and rename one field path.

    src_segs and tgt_segs are the dot-split segments of the source and
    target paths respectively.
    """
    # If data is a list, apply the rename to every element.
    if isinstance(data, list):
        return [_apply_single(item, src_segs, tgt_segs) for item in data]

    if not isinstance(data, dict):
        return data  # scalar — nothing to rename

    if not src_segs:
        return data  # nothing left to process

    head_src = src_segs[0]
    head_tgt = tgt_segs[0]

    # ---- Leaf rename (last segment) ----------------------------------------
    if len(src_segs) == 1:
        if head_src not in data:
            return data  # path not present — skip silently
        value = data.pop(head_src)
        data[head_tgt] = value
        return data

    # ---- Intermediate segment rename + recurse ------------------------------
    # First rename the intermediate key if source and target differ at this
    # level, then recurse into the (now renamed) child.
    if head_src != head_tgt:
        if head_src in data:
            data[head_tgt] = data.pop(head_src)
        # If the key doesn't exist, skip — don't create phantom keys.
        if head_tgt not in data:
            return data
    else:
        if head_src not in data:
            return data  # path not present — skip silently

    # Recurse into the child value
    data[head_tgt] = _apply_single(
        data[head_tgt],
        src_segs[1:],
        tgt_segs[1:],
    )
    return data
