"""
core/equivalence.py

Decides whether two values that are *not* strictly equal should still be
treated as equivalent for diffing purposes.

Built-in defaults cover the most common "empty / unknown" representations
and boolean-like strings.  Additional rules can be loaded from an environment
YAML file so teams can extend them without touching code.

Public API
----------
EquivalenceEngine(yaml_text: str | None)
    .are_equivalent(a, b) -> bool
"""

from __future__ import annotations

import re
from typing import Any

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


# ---------------------------------------------------------------------------
# Built-in equivalence groups
# Each inner set is one "equivalence class": any two values from the same
# set are considered equivalent to each other.
# ---------------------------------------------------------------------------

_BUILTIN_GROUPS: list[set[str]] = [
    # Empty / null / missing
    {"", "null", "none", "na", "n/a", "nil", "undefined"},
    # Boolean true-likes
    {"true", "1", "yes", "y", "on"},
    # Boolean false-likes
    {"false", "0", "no", "n", "off"},
]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class EquivalenceEngine:
    """
    Compares two values and decides if they are equivalent under a set of
    configurable rules.

    Parameters
    ----------
    yaml_text : str | None
        Raw YAML content of an environment config file (optional).
        If provided, any ``equivalence_rules`` section is merged with the
        built-in groups.
    """

    def __init__(self, yaml_text: str | None = None) -> None:
        # Start with a deep copy of the built-in groups.
        self._groups: list[set[str]] = [set(g) for g in _BUILTIN_GROUPS]
        self._load_yaml_rules(yaml_text)

        # Pre-build a lookup: normalised string value → group index
        # so are_equivalent() is O(1) per call.
        self._lookup: dict[str, int] = {}
        for idx, group in enumerate(self._groups):
            for member in group:
                self._lookup[member] = idx

    # ------------------------------------------------------------------
    # Public method
    # ------------------------------------------------------------------

    def explain_equivalence(self, a: Any, b: Any) -> str | None:
        """
        Return a short human-readable string explaining WHY *a* and *b* are
        equivalent, or None if they are not equivalent.

        Used by diff_engine.py to populate the ``trace`` field on EQUIVALENT
        DiffRecord entries.

        Examples
        --------
        "numeric_tolerance"
        "group:null-likes"
        "group:bool-true"
        "group:bool-false"
        "group:custom-0"   (first custom equivalence group)
        """
        if self._numeric_equivalent(a, b):
            return "numeric_tolerance"

        norm_a = self._normalise(a)
        norm_b = self._normalise(b)
        if norm_a is None or norm_b is None:
            return None
        idx_a = self._lookup.get(norm_a)
        idx_b = self._lookup.get(norm_b)
        if idx_a is None or idx_b is None or idx_a != idx_b:
            return None

        # Name the group
        builtin_names = ["null-likes", "bool-true", "bool-false"]
        if idx_a < len(builtin_names):
            return f"group:{builtin_names[idx_a]}"
        return f"group:custom-{idx_a - len(builtin_names)}"

    def are_equivalent(self, a: Any, b: Any) -> bool:
        """
        Return True if *a* and *b* are equivalent (but not strictly equal).

        Strict equality is NOT checked here — the diff engine does that first.
        This method is only called when a != b, and answers: "should we still
        call this a match?"

        Rules applied in order:
        1. Numeric near-equality: both parse as numbers and are within a tiny
           tolerance (handles "1.0" vs 1, "1.00" vs "1").
        2. Case-insensitive string equivalence groups (built-in + custom).
        """
        # Rule 1 — numeric tolerance
        if self._numeric_equivalent(a, b):
            return True

        # Rule 2 — string group membership
        norm_a = self._normalise(a)
        norm_b = self._normalise(b)
        if norm_a is None or norm_b is None:
            return False  # at least one value is not string-like
        idx_a = self._lookup.get(norm_a)
        idx_b = self._lookup.get(norm_b)
        if idx_a is None or idx_b is None:
            return False  # at least one value has no group
        return idx_a == idx_b

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_yaml_rules(self, yaml_text: str | None) -> None:
        """
        Parse the YAML environment config and extend self._groups with any
        custom equivalence_rules found there.

        Expected YAML shape:
            equivalence_rules:
              - ["pending", "in_progress"]   # new group
              - ["USD", "usd", "US Dollar"]  # another group
        """
        if not yaml_text or not yaml_text.strip():
            return
        if not _YAML_AVAILABLE:
            # Can't parse YAML; silently skip custom rules
            return
        try:
            config = yaml.safe_load(yaml_text)
        except yaml.YAMLError:
            # Bad YAML — skip custom rules; the API layer will surface the
            # error separately before we even get here.
            return

        if not isinstance(config, dict):
            return

        custom_groups = config.get("equivalence_rules", [])
        if not isinstance(custom_groups, list):
            return

        for raw_group in custom_groups:
            if not isinstance(raw_group, list) or len(raw_group) < 2:
                continue  # ignore malformed entries
            # Normalise every member to lowercase string
            new_group: set[str] = {
                self._normalise(v)
                for v in raw_group
                if self._normalise(v) is not None
            }  # type: ignore[misc]
            if len(new_group) < 2:
                continue

            # Check if any member already belongs to an existing group.
            # If so, merge into that group rather than creating a duplicate.
            matched_idx: int | None = None
            for member in new_group:
                if member in self._lookup:
                    matched_idx = self._lookup[member]
                    break

            if matched_idx is not None:
                self._groups[matched_idx].update(new_group)
            else:
                self._groups.append(new_group)

    @staticmethod
    def _normalise(value: Any) -> str | None:
        """
        Convert *value* to a lowercase stripped string for group lookup.
        Returns None if the value cannot be meaningfully represented as a
        short string (e.g. a dict or list).
        """
        if isinstance(value, (dict, list)):
            return None
        if isinstance(value, bool):
            # bool must be checked before int because bool is a subclass of int
            return str(value).lower()  # "true" / "false"
        if isinstance(value, (int, float)):
            return str(value)
        if value is None:
            return "null"
        s = str(value).strip().lower()
        return s

    @staticmethod
    def _numeric_equivalent(a: Any, b: Any) -> bool:
        """
        Return True if both *a* and *b* represent the same number.
        Handles mixed types like int 1 vs string "1.0", or float 1.0 vs "1".
        Uses a relative + absolute tolerance similar to math.isclose().
        """
        if isinstance(a, bool) or isinstance(b, bool):
            # Booleans look like 0/1 numerically but should not be silently
            # treated as numbers here; let the group rules handle them.
            return False
        fa = _try_float(a)
        fb = _try_float(b)
        if fa is None or fb is None:
            return False
        # math.isclose defaults: rel_tol=1e-9, abs_tol=0
        # We add a small abs_tol to handle 0.0 vs 0
        rel_tol = 1e-9
        abs_tol = 1e-12
        diff = abs(fa - fb)
        return diff <= max(rel_tol * max(abs(fa), abs(fb)), abs_tol)


# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------

def _try_float(value: Any) -> float | None:
    """Try to convert *value* to float; return None if not possible."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None
