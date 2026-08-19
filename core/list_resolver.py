"""
core/list_resolver.py

Determines how to pair up items in two lists of objects before diffing.

When the diff engine encounters two lists of dicts, it needs to know WHICH
item on the left corresponds to WHICH item on the right.  Three strategies
are tried in order:

  Strategy 1 — Environment key (explicit)
      The environment YAML names the key field(s) for a given list path.
      E.g.  list_keys: { nominees: [nomineeName, percent] }
      Most reliable — use this whenever you know the data's natural key.

  Strategy 2 — Auto-detect (heuristic)
      Scan the first several items and find field(s) whose combined values
      are unique across the list.  Candidate fields tried (in order):
        single fields : id, key, code, name, *_id, *_code, *_name, *_key
        then pairs    : all 2-combinations of the above candidates

  Strategy 3 — Index fallback
      Pair items by position (left[0]↔right[0], left[1]↔right[1], …).
      Used when no unique key is found.  Unmatched tail items are reported
      as EXTRA_LEFT or EXTRA_RIGHT.

Public API
----------
ListResolver(yaml_text: str | None)
    .resolve(list_name, left_items, right_items)
        -> ResolvedPairs

ResolvedPairs
    .pairs         : list of (left_item | None, right_item | None)
    .strategy_used : str  — human-readable description logged in the report
    .key_fields    : list[str] | None
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class ResolvedPairs:
    """Holds the paired items and metadata about how pairing was done."""
    pairs: list[tuple[Any, Any]]          # (left | None, right | None)
    strategy_used: str = ""               # shown in the diff report
    key_fields: list[str] | None = None   # fields used as the composite key


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

class ListResolver:
    """
    Pairs items from two lists of dicts using the best available strategy.

    Parameters
    ----------
    yaml_text : str | None
        Raw YAML environment config.  If it contains a ``list_keys`` section
        those keys are used for Strategy 1.
    """

    # Candidate field names tried during auto-detection (Strategy 2).
    # Checked as exact matches first, then suffix matches (*_id, *_name, etc.)
    _CANDIDATE_EXACT = ["id", "key", "code", "name", "uuid", "ref", "no", "num"]
    _CANDIDATE_SUFFIXES = ["_id", "_code", "_name", "_key", "_no", "_ref", "_uuid"]

    def __init__(self, yaml_text: str | None = None) -> None:
        # dict[list_name_lower -> list[field_name]]
        self._env_keys: dict[str, list[str]] = {}
        self._load_yaml_keys(yaml_text)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def resolve(
        self,
        list_name: str,
        left_items: list[Any],
        right_items: list[Any],
    ) -> ResolvedPairs:
        """
        Pair items from *left_items* and *right_items*.

        *list_name* is the dot-notation path of the list (e.g. "nominees")
        used to look up environment keys.
        """
        # Filter to only dict items; non-dict items are paired separately by
        # index below so a mixed list never silently drops them.
        left_dicts  = [i for i in left_items  if isinstance(i, dict)]
        right_dicts = [i for i in right_items if isinstance(i, dict)]
        left_scalars  = [i for i in left_items  if not isinstance(i, dict)]
        right_scalars = [i for i in right_items if not isinstance(i, dict)]

        if not left_dicts and not right_dicts:
            # Both are scalar lists — pair by index
            return self._index_pair(left_items, right_items, "index (scalar list)")

        dict_result = self._resolve_dict_items(list_name, left_dicts, right_dicts)

        if not left_scalars and not right_scalars:
            return dict_result

        # Mixed list: pair the non-dict items by index too, so they always
        # show up in the diff (MATCH / MISMATCH / EXTRA) instead of vanishing.
        scalar_result = self._index_pair(left_scalars, right_scalars, "index (scalar items)")
        strategy = dict_result.strategy_used
        if scalar_result.pairs:
            strategy = f"{strategy} + index (scalar items)" if strategy else "index (scalar items)"
        return ResolvedPairs(
            pairs=dict_result.pairs + scalar_result.pairs,
            strategy_used=strategy,
            key_fields=dict_result.key_fields,
        )

    def _resolve_dict_items(
        self,
        list_name: str,
        left_dicts: list[dict],
        right_dicts: list[dict],
    ) -> ResolvedPairs:
        """Pair dict-only items using the environment key / auto-detect / index strategies."""
        # Strategy 1 — environment-specified key
        env_key = self._env_keys.get(list_name.lower())
        if env_key:
            result = self._key_pair(left_dicts, right_dicts, env_key)
            if result is not None:
                result.strategy_used = (
                    f"environment key ({', '.join(env_key)})"
                )
                return result

        # Strategy 2 — auto-detect unique key
        detected = self._auto_detect_key(left_dicts, right_dicts)
        if detected:
            result = self._key_pair(left_dicts, right_dicts, detected)
            if result is not None:
                result.strategy_used = (
                    f"auto-detected key ({', '.join(detected)})"
                )
                return result

        # Strategy 3 — index fallback
        return self._index_pair(left_dicts, right_dicts, "index (no unique key found)")

    # ------------------------------------------------------------------
    # Strategy 1 helpers
    # ------------------------------------------------------------------

    def _key_pair(
        self,
        left: list[dict],
        right: list[dict],
        key_fields: list[str],
    ) -> ResolvedPairs | None:
        """
        Build a composite key from *key_fields* for every item and pair them.
        Returns None if duplicate keys are found on either side (key is not
        unique — fall through to next strategy).
        """
        def make_key(item: dict) -> tuple:
            return tuple(str(item.get(f, "")) for f in key_fields)

        left_map:  dict[tuple, dict] = {}
        right_map: dict[tuple, dict] = {}

        for item in left:
            k = make_key(item)
            if k in left_map:
                return None  # duplicate key on left — strategy invalid
            left_map[k] = item

        for item in right:
            k = make_key(item)
            if k in right_map:
                return None  # duplicate key on right — strategy invalid
            right_map[k] = item

        all_keys = sorted(set(left_map) | set(right_map))
        pairs: list[tuple[Any, Any]] = [
            (left_map.get(k), right_map.get(k))
            for k in all_keys
        ]
        return ResolvedPairs(pairs=pairs, key_fields=key_fields)

    # ------------------------------------------------------------------
    # Strategy 2 helpers
    # ------------------------------------------------------------------

    def _auto_detect_key(
        self,
        left: list[dict],
        right: list[dict],
    ) -> list[str] | None:
        """
        Find field(s) whose values are unique WITHIN each list separately.

        The key must uniquely identify every item on the left AND every item
        on the right independently — not across both combined.  Checking
        combined uniqueness would reject valid keys like "emp_id" because the
        same value (e.g. 101) appears on both sides.

        Tries single fields first (cheaper), then pairs.
        Returns the first combination that qualifies, or None.
        """
        if not left and not right:
            return None

        all_items = left + right
        if not all_items:
            return None

        candidates = self._candidate_fields(all_items)

        # Try single fields
        for f in candidates:
            if self._is_unique_key(left, [f]) and self._is_unique_key(right, [f]):
                return [f]

        # Try pairs of candidates (up to first 8 to keep it fast)
        top = candidates[:8]
        for pair in itertools.combinations(top, 2):
            if (self._is_unique_key(left, list(pair))
                    and self._is_unique_key(right, list(pair))):
                return list(pair)

        return None

    def _candidate_fields(self, items: list[dict]) -> list[str]:
        """
        Return an ordered list of field names from *items* that are worth
        trying as key candidates.

        Priority:
          1. Exact matches to _CANDIDATE_EXACT (in that order)
          2. Fields whose name ends with a _CANDIDATE_SUFFIX
          3. All remaining string/number fields (as a last resort pool)
        """
        # Collect all field names that appear in any item
        all_fields: list[str] = []
        seen: set[str] = set()
        for item in items:
            for k in item:
                if k not in seen:
                    all_fields.append(k)
                    seen.add(k)

        exact: list[str] = []
        suffix: list[str] = []
        rest:   list[str] = []

        for f in all_fields:
            fl = f.lower()
            if fl in self._CANDIDATE_EXACT:
                exact.append(f)
            elif any(fl.endswith(s) for s in self._CANDIDATE_SUFFIXES):
                suffix.append(f)
            else:
                rest.append(f)

        # Sort exact by the canonical order in _CANDIDATE_EXACT
        exact.sort(key=lambda x: self._CANDIDATE_EXACT.index(x.lower()))

        return exact + suffix + rest

    @staticmethod
    def _is_unique_key(items: list[dict], fields: list[str]) -> bool:
        """Return True if the composite key from *fields* is unique across all *items*."""
        seen: set[tuple] = set()
        for item in items:
            k = tuple(str(item.get(f, "")) for f in fields)
            if k in seen:
                return False
            seen.add(k)
        return True

    # ------------------------------------------------------------------
    # Strategy 3 helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _index_pair(
        left: list[Any],
        right: list[Any],
        reason: str,
    ) -> ResolvedPairs:
        """Pair items by position; pad the shorter side with None."""
        length = max(len(left), len(right))
        pairs: list[tuple[Any, Any]] = []
        for i in range(length):
            l_item = left[i]  if i < len(left)  else None
            r_item = right[i] if i < len(right) else None
            pairs.append((l_item, r_item))
        return ResolvedPairs(pairs=pairs, strategy_used=reason, key_fields=None)

    # ------------------------------------------------------------------
    # YAML loader
    # ------------------------------------------------------------------

    def _load_yaml_keys(self, yaml_text: str | None) -> None:
        """
        Parse the environment YAML and extract the list_keys section.

        Expected shape:
            list_keys:
              nominees: [nomineeName, percent]   # composite key
              accounts: [accountId]              # single key
        """
        if not yaml_text or not yaml_text.strip():
            return
        if not _YAML_AVAILABLE:
            return
        try:
            config = yaml.safe_load(yaml_text)
        except yaml.YAMLError:
            return
        if not isinstance(config, dict):
            return

        list_keys = config.get("list_keys", {})
        if not isinstance(list_keys, dict):
            return

        for list_name, key_val in list_keys.items():
            if isinstance(key_val, str):
                self._env_keys[list_name.lower()] = [key_val]
            elif isinstance(key_val, list):
                self._env_keys[list_name.lower()] = [str(k) for k in key_val]
