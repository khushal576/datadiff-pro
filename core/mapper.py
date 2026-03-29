"""
core/mapper.py

Renames / remaps fields in a normalised Python dict before diffing.

The user pastes a simple CSV-style mapping in the UI:
    source_path,target_path
    banks,BankData
    user.address.city,person.location.city

This module parses that text, validates it, and applies the renames.

Public API
----------
parse_mapping(mapping_csv: str) -> tuple[list[tuple[str,str]], str | None]
    Parse the raw CSV text into a list of (source_path, target_path) pairs.

apply_mapping(data, pairs, strict_mode=False, multi_match_rule="keep_list")
    -> tuple[Any, list[MapTrace]]
    Walk *data* and rename fields according to the pairs.
    Returns (transformed_data, traces).

--- How the rename works ---

Pairs are sorted deepest-first (longest path first).  A prefix-map records
every rename that has already been applied.  When a later pair references a
path whose parent was already renamed, the prefix-map translates it to the
current (renamed) location automatically.

Example:
    a.b.id   → c.d.identifier   (renames a→c and b→d as intermediates)
    a.b.name → c.d.fullName     (a.b is translated to c.d via prefix-map)

--- Special transform behaviours ---

Duplicate source (one source → multiple targets):
    When the same source path appears in more than one rule, the first
    occurrence MOVES the value (normal rename). Subsequent occurrences
    COPY the value to the new target without removing it from the first
    target.  MapTrace action="copied".

Value-hoist (src depth > tgt depth):
    When a source path is deeper than its target path (e.g. a.b.c → x.y),
    the whole value at the source is extracted and placed at the target.
    When two rules hoist to the same target, the results are collected into
    a list.  MapTrace action="renamed".

Child-conflict detection:
    When a source path is a strict child of another rule's source path
    (e.g. both "a.b" and "a.b.c" are source paths), the child rule is
    skipped — the parent rule handles the entire subtree.
    MapTrace action="conflict_skipped".

Cross-level extraction (unsupported):
    When a source path traverses through a list into nested fields AND
    the target root is different from the source root, this would require
    flattening across records — a structural transform the mapper cannot
    express.  The rule is skipped gracefully.
    MapTrace action="unsupported_transform".

--- List-item scoped renames ---

When a source path traverses into a list (at any depth), the rename is applied
to every matching item.  For example:

    orders.order_id → purchases.id

If `orders` is a list of objects, every item's `order_id` field is renamed to
`id`, and the container itself is renamed `orders → purchases`.

--- Traceability ---

Every applied rule produces a MapTrace entry recording what the rule did:
  "renamed"              — field was moved from src to tgt.
  "copied"               — duplicate source; value was copied to tgt (not moved).
  "merged"               — target already existed; source was placed alongside it.
  "skipped_missing"      — source path was not found in the data.
  "conflict_skipped"     — rule was skipped because a parent rule handles this subtree.
  "unsupported_transform"— rule requires cross-level list flattening (not supported).

--- Strict mode ---

When strict_mode=True, a missing source path raises ValueError instead of
logging a "skipped_missing" trace.
"""

from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from core.path_resolver import resolve_path, ResolutionResult, safe_insert, delete_at_concrete_path


# ---------------------------------------------------------------------------
# MapTrace
# ---------------------------------------------------------------------------

@dataclass
class MapTrace:
    """
    Records what happened when one mapping rule was applied.

    Fields
    ------
    rule_index : int
        Zero-based index of the (src_path, tgt_path) pair in the user's list.
    src_path : str
        Original source path as the user typed it.
    tgt_path : str
        Original target path as the user typed it.
    resolved_src_paths : list[list[str | int]]
        The concrete paths (with integer list indices) where values were found.
        Empty when action == "skipped_missing" / "conflict_skipped" /
        "unsupported_transform".
    action : str
        "renamed"              — field was moved from src to tgt.
        "copied"               — duplicate source; value copied (not moved).
        "merged"               — target already existed; values were merged.
        "skipped_missing"      — source path was not found in the data.
        "conflict_skipped"     — skipped; a parent rule handles this subtree.
        "unsupported_transform"— cross-level list flattening (not supported).
    detail : str
        Human-readable explanation.
    """
    rule_index: int
    src_path: str
    tgt_path: str
    resolved_src_paths: list[list[str | int]] = field(default_factory=list)
    action: str = "renamed"
    detail: str = ""


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
    strict_mode: bool = False,
    multi_match_rule: str = "keep_list",
) -> tuple[Any, list[MapTrace]]:
    """
    Apply field renames to *data* according to *pairs*.

    *data* is deep-copied first so the original is never mutated.

    Parameters
    ----------
    data : Any
        The data structure to transform.
    pairs : list[tuple[str, str]]
        (source_path, target_path) pairs in dot notation.
    strict_mode : bool
        When True, raises ValueError if a declared source path is not found
        in the data.  When False (default), logs a MapTrace with
        action="skipped_missing" and continues.
    multi_match_rule : str
        Controls what resolve_path uses when checking source path existence.
        "keep_list" | "pick_first" | "flatten".

    Returns
    -------
    (transformed_data, traces)
        transformed_data — a deep copy of *data* with all renames applied.
        traces — list of MapTrace (one per pair, in application order).
    """
    data = copy.deepcopy(data)
    traces: list[MapTrace] = []

    if not pairs:
        return data, traces

    # ── Top-level list: apply rules to each item individually ────────────
    # When data is a list of objects the caller is passing records, not a
    # single document.  Rules describe per-record field renames, so we map
    # each item and merge the traces.
    if isinstance(data, list):
        result: list[Any] = []
        for item in data:
            mapped_item, item_traces = apply_mapping(
                item, pairs,
                strict_mode=strict_mode,
                multi_match_rule=multi_match_rule,
            )
            result.append(mapped_item)
            traces.extend(item_traces)
        return result, traces

    # ── Pre-scan 1: find duplicate source paths ───────────────────────────
    # A source that appears in N rules will be MOVEd on the first occurrence
    # and COPYed (value retained) on all subsequent occurrences.
    src_counts = Counter(src for src, _ in pairs)
    multi_src: set[str] = {s for s, c in src_counts.items() if c > 1}
    first_seen_sources: set[str] = set()

    # ── Pre-scan 2: find child conflicts ─────────────────────────────────
    # A rule is a "child" conflict if another rule's source path is a strict
    # prefix of its own source path AND the parent source resolves to a
    # non-list value (dict / scalar).  When the parent source IS a list,
    # the parent renames the container and child rules rename fields inside
    # each list item — they are complementary, not conflicting.
    conflicting_indices: set[int] = _find_child_conflicts(pairs, data)

    # ── Pre-scan 3: build root-level container rename map ─────────────────
    # Maps src_root → tgt_root for single-segment source rules like
    # "orders → purchases".  Used by Bug 5 detection to distinguish
    # "field rename inside a renamed list" (orders.x → purchases.y — valid)
    # from "cross-level extraction into a new key" (nominees.x → other — invalid).
    # Only single-segment source paths count; deeper paths are not container renames.
    root_rename_map: dict[str, str] = {
        src.split(".")[0]: tgt.split(".")[0]
        for src, tgt in pairs
        if "." not in src
    }

    # Sort deepest-first so leaf renames happen before their parents are
    # renamed, letting the prefix_map correctly track path changes.
    indexed_pairs = sorted(
        enumerate(pairs),
        key=lambda ip: len(ip[1][0].split(".")),
        reverse=True,
    )

    # prefix_map: original-src-path → current-tgt-path  (dot strings)
    # Allows later pairs to auto-translate through already-applied renames.
    prefix_map: dict[str, str] = {}

    # leaf_to_current: original leaf name → current list path (segs)
    # Used to locate a list after it has been renamed for item-scope renames.
    leaf_to_current: dict[str, list[str]] = {}

    for rule_index, (src_path, tgt_path) in indexed_pairs:
        src_segs = src_path.split(".")
        tgt_segs = tgt_path.split(".")

        # ── Bug 3: skip child conflicts ───────────────────────────────────
        if rule_index in conflicting_indices:
            parent_src = _find_parent_rule_src(src_segs, pairs, rule_index)
            traces.append(MapTrace(
                rule_index=rule_index,
                src_path=src_path,
                tgt_path=tgt_path,
                resolved_src_paths=[],
                action="conflict_skipped",
                detail=(
                    f"Skipped: source path '{src_path}' is a child of another "
                    f"mapping rule's source ('{parent_src}'). "
                    f"The parent rule handles the entire subtree."
                ),
            ))
            # Do NOT update prefix_map — the parent rule's prefix entry is
            # authoritative and adding the child's intermediate paths would
            # corrupt it.
            continue

        # ── Translate source path using already-applied renames ──────────
        actual_src_segs = _translate_segs(src_segs, prefix_map)

        # ── Check source existence with path_resolver ────────────────────
        resolution: ResolutionResult = resolve_path(
            data, actual_src_segs, multi_match_rule
        )

        # Fall back to list-item scope lookup if top-key path not found
        # (handles the case where the container was already renamed)
        if not resolution.matches:
            orig_list_name = src_segs[0]
            if orig_list_name in leaf_to_current and len(src_segs) > 1:
                list_path = leaf_to_current[orig_list_name]
                check_res = resolve_path(data, list_path + src_segs[1:], multi_match_rule)
                if check_res.matches:
                    resolution = check_res

        if not resolution.matches:
            # Source path genuinely not found in data.
            if strict_mode:
                raise ValueError(
                    f"Mapping rule {rule_index + 1}: source path '{src_path}' "
                    f"was not found in the data. "
                    f"(Missing segments: {resolution.missing_segments})"
                )
            traces.append(MapTrace(
                rule_index=rule_index,
                src_path=src_path,
                tgt_path=tgt_path,
                resolved_src_paths=[],
                action="skipped_missing",
                detail=(
                    f"Source path '{src_path}' not found in data. "
                    f"Missing segments: {resolution.missing_segments}"
                ),
            ))
            _update_prefix_map(prefix_map, src_segs, tgt_segs)
            continue

        # ── Bug 2: duplicate source — copy instead of move ───────────────
        if src_path in multi_src and src_path in first_seen_sources:
            # This is the 2nd+ occurrence of the same source path.
            # The value already lives at the translated location from the
            # first rule.  Copy it to the new target without removing it.
            tgt_check = resolve_path(data, tgt_segs, "pick_first")
            dup_action = "merged" if tgt_check.matches else "copied"
            concrete_src_paths = [m.concrete_path for m in resolution.matches]

            for match in resolution.matches:
                data = safe_insert(data, list(tgt_segs), match.value)

            _update_prefix_map(prefix_map, src_segs, tgt_segs)
            traces.append(MapTrace(
                rule_index=rule_index,
                src_path=src_path,
                tgt_path=tgt_path,
                resolved_src_paths=concrete_src_paths,
                action=dup_action,
                detail=(
                    f"Copied '{src_path}' → '{tgt_path}' "
                    f"(source appears in multiple rules; "
                    f"value retained at its current location)."
                ),
            ))
            continue

        # Track that we've now seen this source for the first time.
        if src_path in multi_src:
            first_seen_sources.add(src_path)

        # ── Bug 5: cross-level extraction — unsupported transform ─────────
        # Detect: source path fans through a list AND the target root is a
        # completely different key (not just a renamed version of the source
        # root via a container-rename rule like "orders → purchases").
        #
        # Valid:   orders.order_id → purchases.id
        #          ↑ orders is a list, but "orders → purchases" exists as a
        #            container rename.  Field renames inside list items are fine.
        #
        # Invalid: nominees.addresses → nominee_addresses
        #          ↑ no rule renames the nominees container; this would require
        #            collecting & flattening data across multiple nominee items.
        has_list_traversal = any(
            any(isinstance(seg, int) for seg in m.concrete_path)
            for m in resolution.matches
        )
        expected_tgt_root = root_rename_map.get(actual_src_segs[0], actual_src_segs[0])
        if has_list_traversal and tgt_segs[0] != actual_src_segs[0] and tgt_segs[0] != expected_tgt_root:
            traces.append(MapTrace(
                rule_index=rule_index,
                src_path=src_path,
                tgt_path=tgt_path,
                resolved_src_paths=[],
                action="unsupported_transform",
                detail=(
                    f"Skipped: '{src_path}' traverses through a list to extract "
                    f"a field into a different top-level key ('{tgt_path}'). "
                    f"Cross-level list flattening is not supported by the field "
                    f"mapper. Consider restructuring your data manually or "
                    f"comparing the path directly without remapping."
                ),
            ))
            # Do NOT update prefix_map — this rule was not applied.
            continue

        # ── Detect potential target conflict (for trace logging) ─────────
        tgt_check = resolve_path(data, tgt_segs, "pick_first")
        action = "merged" if tgt_check.matches else "renamed"
        concrete_src_paths = [m.concrete_path for m in resolution.matches]

        # ── Bug 4: value-hoist for asymmetric depth (src > tgt) ──────────
        # E.g. "user.addresses.home" → "person.locations" (3-seg → 2-seg).
        # Extract the whole value and place it at the shallower target.
        # Multiple rules hoisting to the same target accumulate as a list.
        top_key = actual_src_segs[0]
        if len(actual_src_segs) > len(tgt_segs):
            for match in resolution.matches:
                data = delete_at_concrete_path(data, match.concrete_path)
                # Use list-accumulating insert so that two hoists to the same
                # target produce [val_a, val_b] rather than a dict merge.
                existing_at_tgt = resolve_path(data, list(tgt_segs), "pick_first")
                if existing_at_tgt.matches:
                    existing_val = existing_at_tgt.matches[0].value
                    if isinstance(existing_val, list):
                        existing_val.append(match.value)
                    else:
                        data = _set_at_path(data, list(tgt_segs), [existing_val, match.value])
                else:
                    data = safe_insert(data, list(tgt_segs), match.value)

            # For value-hoist rules, only record the FULL source path in
            # prefix_map (not intermediate prefixes).  Recording intermediates
            # would corrupt sibling paths that share those prefixes.
            full_src = ".".join(src_segs)
            full_tgt = ".".join(tgt_segs)
            if full_src not in prefix_map:
                prefix_map[full_src] = full_tgt
            leaf_to_current[src_segs[-1]] = tgt_segs

        elif _top_key_exists(data, top_key):
            # Case 1: normal absolute path rename
            data = _apply_single(data, actual_src_segs, tgt_segs)
            _update_prefix_map(prefix_map, src_segs, tgt_segs)
            leaf_to_current[src_segs[-1]] = tgt_segs

        else:
            # Case 2: list-item scoped rename
            orig_list_name = src_segs[0]
            if orig_list_name in leaf_to_current and len(src_segs) > 1:
                list_path = leaf_to_current[orig_list_name]
                the_list = _navigate_to(data, list_path)
                if isinstance(the_list, list) and len(tgt_segs) > 1:
                    inner_src = src_segs[1:]
                    inner_tgt = tgt_segs[1:]
                    new_list = [
                        _apply_single(item, inner_src, inner_tgt)
                        for item in the_list
                    ]
                    data = _set_at_path(data, list_path, new_list)
            _update_prefix_map(prefix_map, src_segs, tgt_segs)
            leaf_to_current[src_segs[-1]] = tgt_segs

        detail = (
            f"Renamed '{src_path}' → '{tgt_path}' "
            f"({len(concrete_src_paths)} match(es))."
        )
        if action == "merged":
            detail += " Target already existed; values were merged."

        traces.append(MapTrace(
            rule_index=rule_index,
            src_path=src_path,
            tgt_path=tgt_path,
            resolved_src_paths=concrete_src_paths,
            action=action,
            detail=detail,
        ))

    return data, traces


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_child_conflicts(pairs: list[tuple[str, str]], data: Any) -> set[int]:
    """
    Return the indices of pairs whose source path is a strict child of
    another pair's source path, where the PARENT source is a non-list value.

    A rule at index i is a child conflict when:
      1. Another rule j has a source path that is a strict prefix of i's source.
      2. The value at j's source path in *data* is NOT a list.

    When the parent source IS a list (e.g. "orders"), the parent rule
    renames the list container and child rules rename fields inside each
    item — they are complementary and should both run.

    When the parent source is a dict or scalar (e.g. "user.addresses.home"),
    the parent rule hoists or renames the entire value, making child rules
    redundant and potentially destructive.
    """
    conflicting: set[int] = set()
    src_list = [(i, src.split(".")) for i, (src, _) in enumerate(pairs)]
    for i, segs_i in src_list:
        for j, segs_j in src_list:
            if i == j or len(segs_i) <= len(segs_j):
                continue
            if segs_i[:len(segs_j)] == segs_j:  # j is a strict prefix of i
                # Only conflict if the parent source resolves to a non-list.
                parent_res = resolve_path(data, segs_j, "pick_first")
                if parent_res.matches and isinstance(parent_res.matches[0].value, list):
                    continue  # parent is a list container — child rules are fine
                conflicting.add(i)
    return conflicting


def _find_parent_rule_src(
    src_segs: list[str],
    pairs: list[tuple[str, str]],
    skip_index: int,
) -> str:
    """Return the source path of the parent rule that conflicts with src_segs."""
    for i, (src, _) in enumerate(pairs):
        if i == skip_index:
            continue
        parent_segs = src.split(".")
        if (
            len(parent_segs) < len(src_segs)
            and src_segs[:len(parent_segs)] == parent_segs
        ):
            return src
    return "unknown"


def _translate_segs(src_segs: list[str], prefix_map: dict[str, str]) -> list[str]:
    """
    Translate source path segments using the prefix-map.

    Checks from longest prefix to shortest; substitutes the first match.
    Returns the original list if no prefix is found.
    """
    for length in range(len(src_segs), 0, -1):
        prefix = ".".join(src_segs[:length])
        if prefix in prefix_map:
            new_prefix = prefix_map[prefix].split(".")
            return new_prefix + list(src_segs[length:])
    return list(src_segs)


def _update_prefix_map(
    prefix_map: dict[str, str],
    src_segs: list[str],
    tgt_segs: list[str],
) -> None:
    """Record all prefix renames for this pair in prefix_map."""
    for i in range(1, len(src_segs) + 1):
        key = ".".join(src_segs[:i])
        if key not in prefix_map:
            prefix_map[key] = ".".join(tgt_segs[:i])


def _top_key_exists(data: Any, key: str) -> bool:
    """Return True if *key* is reachable at the outermost level of *data*."""
    if isinstance(data, dict):
        return key in data
    if isinstance(data, list):
        return any(isinstance(item, dict) and key in item for item in data)
    return False


def _navigate_to(data: Any, path_segs: list[str]) -> Any:
    """Navigate *data* along *path_segs* and return the value, or None."""
    current = data
    for seg in path_segs:
        if not isinstance(current, dict) or seg not in current:
            return None
        current = current[seg]
    return current


def _set_at_path(data: Any, path_segs: list[str], value: Any) -> Any:
    """Set the value at *path_segs* inside *data* and return data."""
    if not path_segs:
        return value
    if len(path_segs) == 1:
        if isinstance(data, dict):
            data[path_segs[0]] = value
        return data
    key = path_segs[0]
    if isinstance(data, dict) and key in data:
        data[key] = _set_at_path(data[key], path_segs[1:], value)
    return data


# ---------------------------------------------------------------------------
# Core recursive rename (in-place)
# ---------------------------------------------------------------------------

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
    # Bug 1 fix: guard against exhausted target path segments.
    if not tgt_segs:
        return data

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
        # Bug 1 fix: guard against empty tgt_segs at leaf level.
        if not tgt_segs:
            return data
        value = data.pop(head_src)
        # Use the *last* target segment so container-hint segments that have
        # already been consumed as list-entry wrappers don't clobber the name.
        data[tgt_segs[-1]] = value
        return data

    # ---- Intermediate segment rename + recurse ------------------------------
    if head_src != head_tgt:
        if head_src in data:
            src_val = data.pop(head_src)
            # Bug 4 fix: when target key already exists as a dict and the
            # incoming value is also a dict, merge rather than overwrite.
            # This allows value-hoisted keys (e.g. person.locations from an
            # earlier rule) to coexist with later renames of the same
            # intermediate key (e.g. user → person carrying id, name, etc.).
            if (
                head_tgt in data
                and isinstance(data[head_tgt], dict)
                and isinstance(src_val, dict)
            ):
                merged = {**src_val, **data[head_tgt]}  # tgt wins on conflict
                data[head_tgt] = merged
            else:
                data[head_tgt] = src_val
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
