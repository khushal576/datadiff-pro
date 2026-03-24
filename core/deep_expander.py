"""
core/deep_expander.py

Deep Mode expansion — recursively walks a normalised Python object and tries
to parse any string-valued field into a richer type (dict, list) when the
string content looks like JSON or XML.

This is useful when your data has fields that are *stored as strings* but
actually contain structured data:

    {"payload": '{"id": 1, "tags": ["a","b"]}'}   →  payload becomes a dict
    {"body": "<root><val>1</val></root>"}           →  body becomes a dict
    {"items": "[1, 2, 3]"}                          →  items becomes a list

The expansion is best-effort and non-destructive:
  - A string that cannot be parsed as JSON or XML is left as-is.
  - Scalars (int, float, bool, None) are never touched.
  - Dicts and lists are recursed into so nested string fields are expanded too.

Public API
----------
deep_expand(data: Any) -> Any
    Returns a new object with all string leaves expanded where possible.
"""

from __future__ import annotations

import json
from typing import Any

try:
    import xmltodict
    _XML_AVAILABLE = True
except ImportError:
    _XML_AVAILABLE = False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def deep_expand(data: Any) -> Any:
    """
    Recursively walk *data* and expand string values that are parseable as
    JSON or XML into their native Python equivalents (dict / list).

    Priority: JSON is tried first (faster, more common), then XML.
    If neither parses successfully the original string is kept.

    The input object is NOT mutated — new dicts/lists are constructed.
    """
    return _expand(data)


# ---------------------------------------------------------------------------
# Internal recursive worker
# ---------------------------------------------------------------------------

def _expand(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}

    if isinstance(value, list):
        return [_expand(item) for item in value]

    if isinstance(value, str):
        return _try_parse_string(value)

    # int, float, bool, None — leave untouched
    return value


def _try_parse_string(s: str) -> Any:
    """
    Attempt to parse *s* as JSON, then as XML.
    Returns the parsed object if successful, otherwise returns *s* unchanged.
    """
    stripped = s.strip()

    # ---- JSON ---------------------------------------------------------------
    # Quick pre-check: JSON objects start with { or [, JSON arrays with [.
    # Strings that start with a digit or quote are scalars in JSON — we only
    # want to expand compound types (objects / arrays), not bare scalars.
    if stripped.startswith(("{", "[")):
        parsed = _try_json(stripped)
        if parsed is not None and isinstance(parsed, (dict, list)):
            # Recursively expand the newly parsed object too
            return _expand(parsed)

    # ---- XML ----------------------------------------------------------------
    # XML documents start with < (element or declaration).
    if stripped.startswith("<") and _XML_AVAILABLE:
        parsed = _try_xml(stripped)
        if parsed is not None and isinstance(parsed, (dict, list)):
            return _expand(parsed)

    return s


# ---------------------------------------------------------------------------
# Format-specific parsers (silent — return None on failure)
# ---------------------------------------------------------------------------

def _try_json(s: str) -> Any:
    """Return parsed JSON object or None if parsing fails."""
    try:
        return json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return None


def _try_xml(s: str) -> Any:
    """Return parsed XML-as-dict or None if parsing fails."""
    try:
        result = xmltodict.parse(s)
        # xmltodict always returns an OrderedDict; convert for consistency
        return dict(result)
    except Exception:
        return None
