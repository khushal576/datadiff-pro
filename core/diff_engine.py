"""
core/diff_engine.py

The heart of DataDiff Pro.  Recursively compares two Python objects (dicts,
lists, or scalars) and produces a flat list of DiffRecord entries — one per
field that was examined.

Uses:
  - EquivalenceEngine  to decide if two different values should count as EQUIVALENT
  - ListResolver       to pair up items inside lists of objects

Statuses
--------
  MATCH       — values are identical (or numerically / rule-equivalent)
  MISMATCH    — values differ and no equivalence rule covers them
  EQUIVALENT  — values differ but an equivalence rule says they are the same
  EXTRA_LEFT  — key/item exists only on the left side
  EXTRA_RIGHT — key/item exists only on the right side

Public API
----------
DiffEngine(equivalence_engine, list_resolver)
    .compare(left, right) -> DiffResult

DiffResult
    .records        : list[DiffRecord]
    .summary        : dict   (counts per status)
    .list_strategies: list[str]  (one entry per list encountered)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.equivalence import EquivalenceEngine
from core.list_resolver import ListResolver
from core.deep_expander import deep_expand


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DiffRecord:
    """One compared field / position in the data tree."""
    path: str               # e.g. "nominees[nomineeName=John].percent"
    left_value: Any         # raw value from the left side  (None if EXTRA_RIGHT)
    right_value: Any        # raw value from the right side (None if EXTRA_LEFT)
    status: str             # MATCH | MISMATCH | EQUIVALENT | EXTRA_LEFT | EXTRA_RIGHT
    # Optional traceability metadata — None for simple cases.
    # Keys present depend on what caused the status:
    #   equivalence_rule : str — which rule made two different values EQUIVALENT
    #                            e.g. "numeric_tolerance" | "group:null-likes"
    #   type_mismatch    : str — human-readable type difference for MISMATCH
    #                            e.g. "dict vs str"
    #   list_strategy    : str — how the containing list was paired
    #                            e.g. "auto-detected key (id)"
    #   list_key_values  : dict — key field values used to pair this item
    #                            e.g. {"accountId": "ACC001"}
    trace: dict | None = None


@dataclass
class DiffResult:
    """Full output of a comparison run."""
    records: list[DiffRecord] = field(default_factory=list)
    list_strategies: list[str] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {
            "MATCH": 0,
            "MISMATCH": 0,
            "EQUIVALENT": 0,
            "EXTRA_LEFT": 0,
            "EXTRA_RIGHT": 0,
        }
        for r in self.records:
            counts[r.status] = counts.get(r.status, 0) + 1
        return counts


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class DiffEngine:
    """
    Recursively compares two Python objects and returns a DiffResult.

    Parameters
    ----------
    equivalence_engine : EquivalenceEngine
        Used to decide if two non-equal values should be EQUIVALENT.
    list_resolver : ListResolver
        Used to pair items inside lists of objects.
    deep_mode : bool
        When True enables two extra behaviours during comparison:
        1. String values are attempted to be parsed as JSON or XML on-the-fly
           before comparing (handles any depth of nested stringified data).
        2. A single-item list is automatically unwrapped and compared against
           a plain object/scalar on the other side, instead of recording an
           immediate MISMATCH.
    """

    def __init__(
        self,
        equivalence_engine: EquivalenceEngine,
        list_resolver: ListResolver,
        deep_mode: bool = False,
        null_missing_equivalent: bool = False,
    ) -> None:
        self._eq = equivalence_engine
        self._lr = list_resolver
        self._deep = deep_mode
        self._null_missing_eq = null_missing_equivalent

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def compare(self, left: Any, right: Any) -> DiffResult:
        """
        Compare *left* and *right* and return a DiffResult.

        Both should be Python dicts (or lists of dicts) produced by the
        normalizer after field mapping has been applied.
        """
        result = DiffResult()
        self._compare_values(left, right, path="", result=result)
        return result

    # ------------------------------------------------------------------
    # Core recursive logic
    # ------------------------------------------------------------------

    def _compare_values(
        self,
        left: Any,
        right: Any,
        path: str,
        result: DiffResult,
        _list_trace: dict | None = None,
    ) -> None:
        """
        Dispatch to the right comparison handler based on the types of
        *left* and *right*.

        In deep mode, two extra resolution steps fire before the normal type
        dispatch:

        Step D1 — inline string expansion
            If either side is a string that looks like JSON or XML it is parsed
            in-place before comparison.  This handles any depth of nested
            stringified data that was not caught by the pre-processing pass
            (e.g. a string produced by a list-item merge, or a field that was
            not a string at the top level but became one after an earlier
            normalisation step).

        Step D2 — single-item list ↔ object / scalar unwrapping
            If one side is a list containing exactly one element and the other
            side is NOT a list, the single element is unwrapped and the
            comparison recurses.  This handles the common case where an XML
            normaliser produces ``[{…}]`` for a tag that appears only once
            while the equivalent JSON has a plain ``{…}``.
        """
        # ── Deep mode pre-processing ──────────────────────────────────────
        if self._deep:
            # D1: expand any string values to JSON/XML in-place
            if isinstance(left, str):
                left = deep_expand(left)
            if isinstance(right, str):
                right = deep_expand(right)

            # D2: unwrap single-item list when comparing against non-list
            if isinstance(left, list) and len(left) == 1 and not isinstance(right, list):
                self._compare_values(left[0], right, path, result, _list_trace)
                return
            if isinstance(right, list) and len(right) == 1 and not isinstance(left, list):
                self._compare_values(left, right[0], path, result, _list_trace)
                return

        # ── Normal type dispatch ──────────────────────────────────────────

        # Both are dicts → recurse key by key
        if isinstance(left, dict) and isinstance(right, dict):
            self._compare_dicts(left, right, path, result, _list_trace)
            return

        # Both are lists → use ListResolver then recurse
        if isinstance(left, list) and isinstance(right, list):
            self._compare_lists(left, right, path, result)
            return

        # Type mismatch (one is dict/list, other is scalar) — treat as MISMATCH
        # but still record both values for transparency.
        if type(left) != type(right):
            # Special case: if both could be reasonably compared as scalars
            # (e.g. int vs float vs str-number) let the equivalence engine decide.
            if not isinstance(left, (dict, list)) and not isinstance(right, (dict, list)):
                self._compare_scalars(left, right, path, result, _list_trace)
            else:
                result.records.append(DiffRecord(
                    path=path or "(root)",
                    left_value=_serialisable(left),
                    right_value=_serialisable(right),
                    status="MISMATCH",
                    trace={
                        "type_mismatch": f"{type(left).__name__} vs {type(right).__name__}",
                        **({"list_strategy": _list_trace["list_strategy"],
                            "list_key_values": _list_trace.get("list_key_values")}
                           if _list_trace else {}),
                    },
                ))
            return

        # Both are scalars
        self._compare_scalars(left, right, path, result, _list_trace)

    def _compare_dicts(
        self,
        left: dict,
        right: dict,
        path: str,
        result: DiffResult,
        _list_trace: dict | None = None,
    ) -> None:
        """Compare two dicts key by key."""
        all_keys = _ordered_union(left.keys(), right.keys())

        for key in all_keys:
            child_path = f"{path}.{key}" if path else key
            in_left  = key in left
            in_right = key in right

            if in_left and in_right:
                # Key exists on both sides — recurse; pass list trace only to
                # the first level of children so it explains HOW the items were
                # paired, not every field within them.
                self._compare_values(left[key], right[key], child_path, result, _list_trace)

            elif in_left:
                # Only on the left
                left_val = left[key]
                if self._null_missing_eq and _is_null_or_empty(left_val):
                    _trace = {**((_list_trace or {})), "equivalence_rule": "null_or_empty_vs_missing"}
                    result.records.append(DiffRecord(
                        path=child_path,
                        left_value=_serialisable(left_val),
                        right_value=None,
                        status="EQUIVALENT",
                        trace=_trace,
                    ))
                else:
                    result.records.append(DiffRecord(
                        path=child_path,
                        left_value=_serialisable(left_val),
                        right_value=None,
                        status="EXTRA_LEFT",
                        trace=_list_trace,
                    ))

            else:
                # Only on the right
                right_val = right[key]
                if self._null_missing_eq and _is_null_or_empty(right_val):
                    _trace = {**((_list_trace or {})), "equivalence_rule": "null_or_empty_vs_missing"}
                    result.records.append(DiffRecord(
                        path=child_path,
                        left_value=None,
                        right_value=_serialisable(right_val),
                        status="EQUIVALENT",
                        trace=_trace,
                    ))
                else:
                    result.records.append(DiffRecord(
                        path=child_path,
                        left_value=None,
                        right_value=_serialisable(right_val),
                        status="EXTRA_RIGHT",
                        trace=_list_trace,
                    ))

    def _compare_lists(
        self,
        left: list,
        right: list,
        path: str,
        result: DiffResult,
    ) -> None:
        """
        Pair list items using ListResolver then recursively compare each pair.
        The list name used for resolver lookup is the last segment of *path*.
        """
        list_name = path.split(".")[-1] if path else "(root)"
        resolved = self._lr.resolve(list_name, left, right)

        # Log strategy for this list
        strategy_note = (
            f"List '{path or list_name}': {resolved.strategy_used}"
        )
        result.list_strategies.append(strategy_note)

        for left_item, right_item in resolved.pairs:
            # Build a human-readable index for the path
            item_label = _item_label(left_item, right_item, resolved.key_fields)
            item_path = f"{path}[{item_label}]"

            # Build trace data for this pair so child records know HOW the
            # items were paired (which strategy and which key values matched).
            item_trace: dict = {"list_strategy": resolved.strategy_used}
            if resolved.key_fields:
                ref_item = left_item if left_item is not None else right_item
                if isinstance(ref_item, dict):
                    item_trace["list_key_values"] = {
                        f: ref_item.get(f) for f in resolved.key_fields
                    }

            if left_item is None:
                # Item only exists on the right
                result.records.append(DiffRecord(
                    path=item_path,
                    left_value=None,
                    right_value=_serialisable(right_item),
                    status="EXTRA_RIGHT",
                    trace=item_trace,
                ))
            elif right_item is None:
                # Item only exists on the left
                result.records.append(DiffRecord(
                    path=item_path,
                    left_value=_serialisable(left_item),
                    right_value=None,
                    status="EXTRA_LEFT",
                    trace=item_trace,
                ))
            else:
                # Both present — recurse, threading the list trace so direct
                # children know which pairing strategy placed them together.
                self._compare_values(left_item, right_item, item_path, result, item_trace)

    def _compare_scalars(
        self,
        left: Any,
        right: Any,
        path: str,
        result: DiffResult,
        _list_trace: dict | None = None,
    ) -> None:
        """Compare two scalar values and record the appropriate status."""
        record_path = path or "(root)"

        # Strict equality first (handles identical strings, ints, bools, None)
        if left == right:
            result.records.append(DiffRecord(
                path=record_path,
                left_value=left,
                right_value=right,
                status="MATCH",
                trace=_list_trace,
            ))
            return

        # Equivalence check (null="", true=1, custom rules, numeric tolerance)
        rule = self._eq.explain_equivalence(left, right)
        if rule is not None:
            trace = {"equivalence_rule": rule}
            if _list_trace:
                trace.update(_list_trace)
            result.records.append(DiffRecord(
                path=record_path,
                left_value=left,
                right_value=right,
                status="EQUIVALENT",
                trace=trace,
            ))
            return

        # Genuine mismatch
        result.records.append(DiffRecord(
            path=record_path,
            left_value=left,
            right_value=right,
            status="MISMATCH",
            trace=_list_trace,
        ))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_null_or_empty(v: Any) -> bool:
    """Return True if *v* is None or an empty/whitespace-only string."""
    if v is None:
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    return False


def _ordered_union(keys_a: Any, keys_b: Any) -> list[str]:
    """
    Return all keys from both dicts in a stable order:
    keys from the left first (in their original order), then any keys that
    appear only in the right (in their original order).
    """
    seen: set[str] = set()
    result: list[str] = []
    for k in keys_a:
        if k not in seen:
            result.append(k)
            seen.add(k)
    for k in keys_b:
        if k not in seen:
            result.append(k)
            seen.add(k)
    return result


def _item_label(
    left_item: Any,
    right_item: Any,
    key_fields: list[str] | None,
) -> str:
    """
    Build a readable label for a list item's path segment.

    If key_fields are known: "nomineeName=John,percent=50"
    Otherwise: use the index implicitly supplied by the caller, or a
    short repr of the value.
    """
    item = left_item if left_item is not None else right_item
    if key_fields and isinstance(item, dict):
        parts = [f"{f}={item.get(f, '?')}" for f in key_fields]
        return ",".join(parts)
    # Fallback: short repr (truncated for readability)
    raw = str(item)
    if len(raw) > 40:
        raw = raw[:37] + "..."
    return raw


def _serialisable(value: Any) -> Any:
    """
    Ensure *value* is JSON-serialisable so DiffRecords can be sent over the
    API without extra conversion.  Dicts and lists are returned as-is;
    everything else is cast to str if it is not already a JSON primitive.
    """
    if value is None or isinstance(value, (bool, int, float, str, dict, list)):
        return value
    return str(value)
