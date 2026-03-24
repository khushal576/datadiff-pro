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

--- How cascading renames work ---

Pairs are sorted deepest-first (longest path first).  A prefix-map records
every rename that has already been applied.  When a later pair references a
path whose parent was already renamed, the prefix-map translates it to the
current (renamed) location automatically.

Example:
    a.b.id   → c.d.identifier   (renames a→c and b→d as intermediates)
    a.b.name → c.d.fullName     (a.b is translated to c.d via prefix-map)

--- How list-item scoped renames work ---

Some pairs target fields *inside* list items rather than top-level fields.
The format is: list_name.field → container_name.new_field

    orders.order_id → purchase.id

This means: "inside the list that was called 'orders', rename each item's
'order_id' field to 'id'."  The first segment on each side ('orders' /
'purchase') is the list-container hint; it is stripped and the inner rename
is applied to every item in that list.

The mapper detects this case by checking whether the translated source path
resolves to a list in the data.
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

    Cascading renames
    -----------------
    Pairs are processed deepest-first and a prefix-map is maintained so that
    later pairs can reference paths that have already been renamed by earlier
    pairs.  This lets a user supply a full cross-structure mapping without
    worrying about order:

        a.b.id,   c.d.identifier   ← renames a→c, b→d implicitly
        a.b.name, c.d.fullName     ← a.b is auto-translated to c.d

    List-item scoped renames
    ------------------------
    When the first segment of a source path resolves to a list in the data,
    the pair is treated as a list-item rename:

        orders.order_id, purchase.id
        ↑ list name      ↑ item field rename (strip container hints from both)

    This applies `order_id → id` to every item object inside the `orders` list.
    """
    data = copy.deepcopy(data)
    if not pairs:
        return data

    # Sort deepest-first so leaf renames happen before their parents are renamed,
    # letting the prefix-map correctly track already-applied path changes.
    sorted_pairs = sorted(pairs, key=lambda p: len(p[0].split(".")), reverse=True)

    # prefix_map: original-src-path → current-tgt-path  (dot strings)
    # e.g.  "a.b.orders" → "c.d.purchases"
    prefix_map: dict[str, str] = {}

    # leaf_to_current_path: original leaf name → current list path in data (as segs)
    # e.g.  "orders" → ["c", "d", "purchases"]
    # Used to locate a list after it has been renamed, for item-scope renames.
    leaf_to_current: dict[str, list[str]] = {}

    for src_path, tgt_path in sorted_pairs:
        src_segs = src_path.split(".")
        tgt_segs = tgt_path.split(".")

        # ── Translate source path using already-applied renames ────────────
        actual_src_segs = _translate_segs(src_segs, prefix_map)

        # ── Check what sits at the translated source path ──────────────────
        top_key = actual_src_segs[0]

        if _top_key_exists(data, top_key):
            # ── Case 1: normal absolute path rename ─────────────────────
            data = _apply_single(data, actual_src_segs, tgt_segs)
        else:
            # ── Case 2: list-item scoped rename ─────────────────────────
            # The first (original) segment may be a list that was already
            # renamed.  Look it up in leaf_to_current.
            orig_list_name = src_segs[0]
            if orig_list_name in leaf_to_current and len(src_segs) > 1:
                list_path = leaf_to_current[orig_list_name]
                the_list = _navigate_to(data, list_path)
                if isinstance(the_list, list) and len(tgt_segs) > 1:
                    # Strip the container-name hints from both sides:
                    #   orders.order_id → purchase.id
                    #      ^strip             ^strip
                    # leaving: order_id → id  (applied to each list item)
                    inner_src = src_segs[1:]
                    inner_tgt = tgt_segs[1:]
                    new_list = [
                        _apply_single(item, inner_src, inner_tgt)
                        for item in the_list
                    ]
                    data = _set_at_path(data, list_path, new_list)
            # else: silently skip — source path not found anywhere

        # ── Update prefix_map with all prefix renames from this pair ──────
        # Record even if the apply was a no-op so subsequent pairs can still
        # use the declared mapping intent for prefix translation.
        for i in range(1, len(src_segs) + 1):
            key = ".".join(src_segs[:i])
            if key not in prefix_map:
                prefix_map[key] = ".".join(tgt_segs[:i])

        # ── Record leaf name → current path for list-scope lookup ─────────
        # Use the TARGET segs (current path after rename) so we know where
        # the list lives now.
        leaf_to_current[src_segs[-1]] = tgt_segs

    return data


# ---------------------------------------------------------------------------
# Internal helpers for apply
# ---------------------------------------------------------------------------

def _translate_segs(src_segs: list[str], prefix_map: dict[str, str]) -> list[str]:
    """
    Translate source path segments using the prefix-map.

    Checks from longest prefix to shortest; substitutes the first match found.
    Returns the original list if no prefix is found.
    """
    for length in range(len(src_segs), 0, -1):
        prefix = ".".join(src_segs[:length])
        if prefix in prefix_map:
            new_prefix = prefix_map[prefix].split(".")
            return new_prefix + list(src_segs[length:])
    return list(src_segs)


def _top_key_exists(data: Any, key: str) -> bool:
    """
    Return True if *key* is reachable at the outermost level of *data*.
    Handles both dict (key directly) and list (key in any item).
    """
    if isinstance(data, dict):
        return key in data
    if isinstance(data, list):
        return any(isinstance(item, dict) and key in item for item in data)
    return False


def _navigate_to(data: Any, path_segs: list[str]) -> Any:
    """
    Navigate *data* along *path_segs* and return the value found, or None.
    Does NOT recurse into lists — used for locating list containers.
    """
    current = data
    for seg in path_segs:
        if not isinstance(current, dict) or seg not in current:
            return None
        current = current[seg]
    return current


def _set_at_path(data: Any, path_segs: list[str], value: Any) -> Any:
    """
    Set the value at *path_segs* inside *data* and return (modified) *data*.
    All intermediate nodes must already exist.
    """
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
# Core recursive rename
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
        # Use the *last* target segment, not the first.  When a target path has
        # extra container-hint segments (e.g. "purchase.products.product.code"
        # paired with source "item_id"), the intermediate hint segments will
        # already have been consumed as list-entry wrappers; the actual field
        # name is always the final segment.
        data[tgt_segs[-1]] = value
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
