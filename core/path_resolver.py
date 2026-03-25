"""
core/path_resolver.py

Universal path resolution for arbitrarily nested dicts and lists.

This module is the foundation for the ETL-based mapper.  It replaces the
ad-hoc private helpers (_navigate_to, _top_key_exists, _set_at_path) that
lived in mapper.py with a composable, well-tested API.

Public API
----------
resolve_path(data, path_segs, multi_match_rule="keep_list") -> ResolutionResult
    Find every value at *path_segs* inside *data*, traversing lists at any
    depth.  Returns all matches together with the exact concrete path used to
    reach each one.

set_at_concrete_path(data, concrete_path, value) -> Any
    Write *value* at the given concrete path (list of str keys and int indices).
    Raises PathConflictError if the terminal node already exists.
    Use safe_insert when you want merge semantics.

safe_insert(data, concrete_path, new_value) -> Any
    Write *new_value* at *concrete_path* using merge semantics:
      scalar + scalar  → [existing, new_value]
      list   + value   → existing list with new_value appended
      dict   + dict    → shallow merge {**existing, **new_value}
    Never raises.  Returns the (modified) data.

collect_leaf_paths(data) -> set[str]
    Return a flat set of dot-notation paths for every scalar leaf in *data*.
    List items use integer indices: "orders.0.id", "orders.1.id".
    Used by validator.py to detect dropped fields.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PathConflictError(Exception):
    """Raised by set_at_concrete_path when the target already has a value."""


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class ResolvedMatch:
    """One successful match from resolve_path."""
    value: Any
    # Exact sequence of keys (str) and list indices (int) that were traversed.
    # e.g. ["orders", 0, "items", 2, "code"]
    concrete_path: list[str | int]


@dataclass
class ResolutionResult:
    """Return value of resolve_path."""
    matches: list[ResolvedMatch] = field(default_factory=list)
    # Dot-notation segments that were NOT found anywhere in the data.
    missing_segments: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# resolve_path
# ---------------------------------------------------------------------------

def resolve_path(
    data: Any,
    path_segs: list[str],
    multi_match_rule: str = "keep_list",
) -> ResolutionResult:
    """
    Traverse *data* along *path_segs* and return every matching value.

    The traversal fans out through lists: if a node is a list, we descend
    into every item that contains the next segment.  This means a single
    dot-notation path can match multiple values when lists are involved.

    Parameters
    ----------
    data : Any
        The data structure to search.
    path_segs : list[str]
        Dot-split path segments, e.g. ["orders", "items", "code"].
    multi_match_rule : str
        Controls what happens when multiple matches are found:
        - "keep_list" (default): return all matches as-is.
        - "pick_first": return only the first match.
        - "flatten": if any match's value is itself a list, expand it into
          individual ResolvedMatch entries (one per element).

    Returns
    -------
    ResolutionResult
        .matches       — all found values with their concrete paths
        .missing_segments — any segment that was not found in the data
    """
    result = ResolutionResult()
    if not path_segs:
        result.matches.append(ResolvedMatch(value=data, concrete_path=[]))
        return result

    _resolve_recursive(
        node=data,
        remaining=list(path_segs),
        walked=[],
        result=result,
    )

    # Apply multi_match_rule
    if multi_match_rule == "pick_first":
        result.matches = result.matches[:1]
    elif multi_match_rule == "flatten":
        expanded: list[ResolvedMatch] = []
        for m in result.matches:
            if isinstance(m.value, list):
                for i, item in enumerate(m.value):
                    expanded.append(ResolvedMatch(
                        value=item,
                        concrete_path=m.concrete_path + [i],
                    ))
            else:
                expanded.append(m)
        result.matches = expanded
    # "keep_list": return as-is

    return result


def _resolve_recursive(
    node: Any,
    remaining: list[str],
    walked: list[str | int],
    result: ResolutionResult,
) -> None:
    """
    Recursive worker for resolve_path.

    *walked* is modified in-place during recursion (append/pop) for
    efficiency; each successful terminal match gets a *copy*.
    """
    if not remaining:
        # Reached the end of the path — record this match.
        result.matches.append(ResolvedMatch(
            value=node,
            concrete_path=list(walked),  # snapshot
        ))
        return

    seg = remaining[0]
    rest = remaining[1:]

    if isinstance(node, dict):
        if seg in node:
            walked.append(seg)
            _resolve_recursive(node[seg], rest, walked, result)
            walked.pop()
        else:
            # Segment not present — record as missing only once per unique seg.
            if seg not in result.missing_segments:
                result.missing_segments.append(seg)

    elif isinstance(node, list):
        # Fan out: try every dict item that contains the segment.
        found_in_any = False
        for i, item in enumerate(node):
            if isinstance(item, dict) and seg in item:
                found_in_any = True
                walked.append(i)
                walked.append(seg)
                _resolve_recursive(item[seg], rest, walked, result)
                walked.pop()  # seg
                walked.pop()  # i
        if not found_in_any:
            if seg not in result.missing_segments:
                result.missing_segments.append(seg)

    else:
        # Scalar node — cannot descend further.
        if seg not in result.missing_segments:
            result.missing_segments.append(seg)


# ---------------------------------------------------------------------------
# set_at_concrete_path
# ---------------------------------------------------------------------------

def set_at_concrete_path(
    data: Any,
    concrete_path: list[str | int],
    value: Any,
) -> Any:
    """
    Write *value* at the location described by *concrete_path*.

    *data* is modified in-place (it is expected to already be a deep copy).

    Raises PathConflictError if the terminal location already contains a
    value.  Use safe_insert for merge semantics.

    Intermediate dict keys that are missing are created automatically.
    Intermediate list indices must already exist (lists are not auto-extended).
    """
    if not concrete_path:
        return value

    _set_recursive(data, concrete_path, value, strict=True)
    return data


def _set_recursive(
    node: Any,
    path: list[str | int],
    value: Any,
    strict: bool,
) -> None:
    """In-place recursive setter."""
    key = path[0]
    rest = path[1:]

    if isinstance(node, dict):
        if not rest:
            # Terminal: write the value.
            if strict and key in node:
                raise PathConflictError(
                    f"Target key '{key}' already exists. "
                    "Use safe_insert to merge instead of set_at_concrete_path."
                )
            node[key] = value
        else:
            # Intermediate: ensure the key exists, then recurse.
            if key not in node:
                # Create a new dict as placeholder; list indices further down
                # would need special handling but in practice mapper paths end
                # in string keys.
                node[key] = {}
            _set_recursive(node[key], rest, value, strict)

    elif isinstance(node, list):
        if not isinstance(key, int):
            raise PathConflictError(
                f"Expected int index for list node but got '{key}'."
            )
        if key >= len(node):
            raise PathConflictError(
                f"List index {key} is out of range (length {len(node)})."
            )
        if not rest:
            if strict and node[key] is not None:
                raise PathConflictError(
                    f"List[{key}] already has a value. "
                    "Use safe_insert to merge."
                )
            node[key] = value
        else:
            _set_recursive(node[key], rest, value, strict)

    else:
        raise PathConflictError(
            f"Cannot descend into scalar node '{node!r}' with key '{key}'."
        )


# ---------------------------------------------------------------------------
# safe_insert
# ---------------------------------------------------------------------------

def safe_insert(
    data: Any,
    concrete_path: list[str | int],
    new_value: Any,
) -> Any:
    """
    Write *new_value* at *concrete_path* using merge semantics.

    Merge rules when the target already exists:
      scalar + scalar  → [existing, new_value]
      list   + value   → existing list with new_value appended
      dict   + dict    → {**existing, **new_value}  (shallow merge)
      dict   + scalar  → [existing_dict, new_value]

    If the target does NOT exist, behaves identically to set_at_concrete_path.
    Never raises.  Returns the (modified) data.
    """
    if not concrete_path:
        # Root replacement — merge at top level if both are dicts.
        if isinstance(data, dict) and isinstance(new_value, dict):
            data.update(new_value)
            return data
        return new_value

    _safe_insert_recursive(data, concrete_path, new_value)
    return data


def _safe_insert_recursive(
    node: Any,
    path: list[str | int],
    value: Any,
) -> None:
    """In-place recursive safe insert."""
    key = path[0]
    rest = path[1:]

    if isinstance(node, dict):
        if not rest:
            # Terminal
            if key not in node:
                node[key] = value
            else:
                existing = node[key]
                node[key] = _merge(existing, value)
        else:
            if key not in node:
                node[key] = {}
            _safe_insert_recursive(node[key], rest, value)

    elif isinstance(node, list):
        if not isinstance(key, int):
            return  # cannot index list with non-int; skip silently
        if key >= len(node):
            return  # index out of range; skip
        if not rest:
            existing = node[key]
            node[key] = _merge(existing, value)
        else:
            _safe_insert_recursive(node[key], rest, value)


def _merge(existing: Any, new_value: Any) -> Any:
    """Merge *new_value* into *existing* non-destructively."""
    if isinstance(existing, list):
        result = list(existing)
        result.append(new_value)
        return result
    if isinstance(existing, dict) and isinstance(new_value, dict):
        return {**existing, **new_value}
    # Scalar + anything → list
    return [existing, new_value]


# ---------------------------------------------------------------------------
# collect_leaf_paths
# ---------------------------------------------------------------------------

def collect_leaf_paths(data: Any, _prefix: str = "") -> set[str]:
    """
    Return a flat set of dot-notation paths for every scalar leaf in *data*.

    List items are indexed numerically:
        {"orders": [{"id": 1}, {"id": 2}]}
        → {"orders.0.id", "orders.1.id"}

    This is used by validator.py to detect fields that were silently dropped
    during the mapping transformation.
    """
    result: set[str] = set()
    _collect_recursive(data, _prefix, result)
    return result


def _collect_recursive(node: Any, prefix: str, result: set[str]) -> None:
    if isinstance(node, dict):
        for key, child in node.items():
            child_prefix = f"{prefix}.{key}" if prefix else key
            _collect_recursive(child, child_prefix, result)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            child_prefix = f"{prefix}.{i}" if prefix else str(i)
            _collect_recursive(item, child_prefix, result)
    else:
        # Scalar leaf (including None)
        if prefix:
            result.add(prefix)


# ---------------------------------------------------------------------------
# Internal utility used by mapper.py
# ---------------------------------------------------------------------------

def delete_at_concrete_path(data: Any, concrete_path: list[str | int]) -> Any:
    """
    Remove the key/index at *concrete_path* from *data*.

    Used by the ETL mapper to delete source fields after extracting them.
    No-op if the path doesn't exist.  Returns (modified) data.
    """
    if not concrete_path:
        return data
    _delete_recursive(data, concrete_path)
    return data


def _delete_recursive(node: Any, path: list[str | int]) -> None:
    key = path[0]
    rest = path[1:]

    if isinstance(node, dict):
        if key not in node:
            return
        if not rest:
            del node[key]
        else:
            _delete_recursive(node[key], rest)

    elif isinstance(node, list):
        if not isinstance(key, int) or key >= len(node):
            return
        if not rest:
            # Mark as None rather than shrinking the list (preserves indices
            # for sibling fields that haven't been processed yet).
            node[key] = None
        else:
            _delete_recursive(node[key], rest)
