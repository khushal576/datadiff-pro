"""
core/normalizer.py

Responsible for converting raw input strings (JSON, XML, or CSV) into
Python dicts/lists that the rest of the pipeline can work with uniformly.

Each format has its own parser. On any failure the parser returns a clear,
human-readable error message (with line number / position where possible)
instead of raising a bare exception.
"""

import json
import csv
import io
import re
from typing import Any

# Optional: xmltodict is the cleanest way to handle XML → dict.
# It is listed in requirements.txt.
try:
    import xmltodict
    _XML_AVAILABLE = True
except ImportError:
    _XML_AVAILABLE = False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def normalize(raw: str, fmt: str) -> tuple[Any, str | None]:
    """
    Parse *raw* text in the given *fmt* ("json", "xml", or "csv") and return
    a normalized Python object (dict or list of dicts).

    Returns
    -------
    (data, error)
        data  — parsed Python object, or None if parsing failed
        error — human-readable error string, or None if parsing succeeded
    """
    raw = raw.strip()
    if not raw:
        return None, "Input is empty. Please paste some data to compare."

    fmt = fmt.lower().strip()
    if fmt == "json":
        return _parse_json(raw)
    elif fmt == "xml":
        return _parse_xml(raw)
    elif fmt == "csv":
        return _parse_csv(raw)
    else:
        return None, (
            f"Unknown format '{fmt}'. Supported formats are: json, xml, csv."
        )


# ---------------------------------------------------------------------------
# JSON parser
# ---------------------------------------------------------------------------

def _parse_json(raw: str) -> tuple[Any, str | None]:
    """Parse a JSON string into a Python dict or list."""
    try:
        data = json.loads(raw)
        return data, None
    except json.JSONDecodeError as e:
        # e.lineno, e.colno, e.msg are all set by the stdlib decoder
        snippet = _get_snippet(raw, e.lineno)
        return None, (
            f"JSON parse error on line {e.lineno}, column {e.colno}: {e.msg}.\n"
            f"  Near: {snippet}\n"
            f"Hint: Check for missing commas, unmatched braces/brackets, or "
            f"unquoted keys."
        )


# ---------------------------------------------------------------------------
# XML parser
# ---------------------------------------------------------------------------

def _parse_xml(raw: str) -> tuple[Any, str | None]:
    """Parse an XML string into a nested Python dict using xmltodict."""
    if not _XML_AVAILABLE:
        return None, (
            "XML parsing is unavailable: the 'xmltodict' library is not installed. "
            "Add 'xmltodict' to requirements.txt and rebuild the image."
        )
    try:
        # Pre-process: inject any missing namespace declarations so expat
        # doesn't throw "unbound prefix" on e.g. xsi:nil.
        raw = _inject_missing_namespaces(raw)

        common_kwargs: dict = dict(
            attr_prefix="@",    # keep XML attributes prefixed with @
            cdata_key="#text",  # text content stored in #text key
        )

        # Pass 1 — parse with default settings to discover which tags
        # xmltodict naturally promotes to lists (i.e. tags with multiple
        # sibling occurrences in the document).
        first_pass = xmltodict.parse(raw, force_list=(), **common_kwargs)
        list_tags: set[str] = set()
        _collect_list_tag_names(first_pass, list_tags)

        # Pass 2 — re-parse forcing those tags to ALWAYS be lists.
        # This fixes the case where a tag has only ONE child element:
        # xmltodict would return a dict, but we want a list of one item
        # so the structure stays consistent with the JSON equivalent.
        parsed = xmltodict.parse(raw, force_list=tuple(list_tags), **common_kwargs)

        # Step 1 — convert OrderedDicts to plain dicts.
        data = _ordereddict_to_dict(parsed)
        # Step 2 — unwrap single-child list wrappers created by xmltodict.
        #   e.g. {"skills": {"skill": [...]}} → {"skills": [...]}
        #   This makes the XML structure match the equivalent JSON structure.
        data = _unwrap_xml_lists(data)
        # Step 3 — normalize XML attributes:
        #   • Strip the '@' prefix so @type → type (matches JSON field names)
        #   • Hoist mixed-content nodes: <amount currency="INR">2599.75</amount>
        #     becomes amount=2599.75 with currency="INR" as a sibling field
        #   • xsi:nil="true" elements become None
        data = _normalize_xml_attrs(data)
        # Step 4 — coerce numeric strings to int/float so they MATCH (not
        #   just EQUIVALENT) against JSON numeric values.
        data = _coerce_xml_numbers(data)
        return data, None
    except Exception as e:  # xmltodict raises ExpatError or similar
        line, col = _extract_xml_position(str(e))
        hint = ""
        if line:
            snippet = _get_snippet(raw, line)
            hint = f"\n  Near line {line}: {snippet}"
        return None, (
            f"XML parse error: {e}.{hint}\n"
            f"Hint: Make sure the document has a single root element, all tags "
            f"are properly closed, and special characters like & are escaped as "
            f"&amp;."
        )


def _unwrap_root(parsed: dict) -> Any:
    """
    xmltodict always returns a single-key dict whose key is the XML root tag.
    If that's the case, return the value so the caller works with the content.
    """
    if isinstance(parsed, dict) and len(parsed) == 1:
        return next(iter(parsed.values()))
    return parsed


def _extract_xml_position(msg: str) -> tuple[int | None, int | None]:
    """Try to pull line/column numbers out of an XML error message string."""
    m = re.search(r"line (\d+), column (\d+)", msg, re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def _ordereddict_to_dict(obj: Any) -> Any:
    """Recursively convert OrderedDict (and any Mapping) to plain dict."""
    if isinstance(obj, dict):
        return {k: _ordereddict_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_ordereddict_to_dict(item) for item in obj]
    return obj


def _collect_list_tag_names(obj: Any, result: set) -> None:
    """
    Walk *obj* (output of the first xmltodict pass) and collect tag names
    that should always be forced to lists in the second parse.

    Two cases are detected:
    a) A key whose value is already a list — multiple sibling occurrences in
       the document; xmltodict already made it a list.
    b) A single-key wrapper dict whose sole child value is a dict (not a
       scalar).  E.g. ``{"users": {"user": {…}}}`` → add ``"user"`` to
       force_list so it becomes ``[{…}]`` instead of a bare dict.  This
       handles the case where only one item exists in a repeating collection.
       Safety guard: the child value must be a dict (dicts are records/objects);
       if the child value were a string/number it would be a plain field, not
       a list-item container.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, list):
                result.add(k)
            elif (
                isinstance(v, dict)
                and len(v) == 1
                and not k.startswith("@")
                and k != "#text"
            ):
                # Single-child wrapper: inspect the child
                child_key = next(iter(v))
                child_val = v[child_key]
                if (
                    not child_key.startswith("@")
                    and child_key != "#text"
                    and isinstance(child_val, dict)
                ):
                    # child is an object (record) — treat parent as container
                    result.add(child_key)
            _collect_list_tag_names(v, result)
    elif isinstance(obj, list):
        for item in obj:
            _collect_list_tag_names(item, result)


def _unwrap_xml_lists(obj: Any, _depth: int = 0) -> Any:
    """
    Recursively unwrap single-child list-wrapper dicts produced by xmltodict.

    xmltodict converts repeated XML sibling tags into a list under their tag
    name, but keeps that list wrapped in a parent dict:
        <skills><skill>A</skill><skill>B</skill></skills>
        → {"skills": {"skill": ["A", "B"]}}   ← xmltodict output
        → {"skills": ["A", "B"]}              ← after this function

    Rule: if a dict has exactly ONE key and its value is a list, replace the
    dict with just the list.  Applied at depth > 0 only — the top-level root
    dict is never unwrapped so that the root tag name (e.g. "employees") is
    preserved and can be matched against the equivalent JSON key.

    Safe cases that are NOT touched:
        {"address": {"city": "X", "state": "Y"}}  — 2 keys, not a wrapper
        {"name": "Alice"}                          — value is str, not a list
    """
    if isinstance(obj, dict):
        # Recurse into every value first (incrementing depth).
        unwrapped = {k: _unwrap_xml_lists(v, _depth + 1) for k, v in obj.items()}
        # Unwrap only at depth > 0 so the root key (e.g. "employees") stays.
        if _depth > 0 and len(unwrapped) == 1:
            sole_value = next(iter(unwrapped.values()))
            if isinstance(sole_value, list):
                return sole_value
        return unwrapped
    if isinstance(obj, list):
        # List items stay at the same depth as the list itself.
        return [_unwrap_xml_lists(item, _depth) for item in obj]
    return obj


# Well-known namespace URIs injected when a prefix is used but not declared.
_KNOWN_NS: dict[str, str] = {
    "xsi":  "http://www.w3.org/2001/XMLSchema-instance",
    "xs":   "http://www.w3.org/2001/XMLSchema",
    "xsd":  "http://www.w3.org/2001/XMLSchema",
    "xlink":"http://www.w3.org/1999/xlink",
}


def _inject_missing_namespaces(raw: str) -> str:
    """
    Scan for namespace prefixes used in the XML (e.g. ``xsi:nil``) and inject
    any missing ``xmlns:`` declarations into the root element so the expat
    parser doesn't throw an 'unbound prefix' error.
    """
    # Collect all namespace prefixes actually used (e.g. "xsi" from "xsi:nil")
    used: set[str] = set(re.findall(r'\b([a-zA-Z][a-zA-Z0-9_]*):[a-zA-Z]', raw))
    # Collect already-declared prefixes
    declared: set[str] = set(re.findall(r'xmlns:([a-zA-Z][a-zA-Z0-9_]*)\s*=', raw))
    missing = used - declared
    if not missing:
        return raw

    injections = " ".join(
        f'xmlns:{p}="{_KNOWN_NS.get(p, "urn:" + p)}"'
        for p in sorted(missing)
    )

    # Inject into the first opening tag (the root element).
    def _add(m: re.Match) -> str:
        return f"<{m.group(1)} {injections}{m.group(2)}"

    return re.sub(r"<([a-zA-Z][^>]*?)(\s*/?>)", _add, raw, count=1)


def _normalize_xml_attrs(obj: Any) -> Any:
    """
    Recursively post-process the xmltodict output to make XML attributes
    look like ordinary JSON fields:

    1. Strip the ``@`` prefix from every attribute key.
    2. Strip namespace prefixes (``xsi:nil`` → ``nil``).
    3. Elements with ``nil="true"`` / ``xsi:nil="true"`` become ``None``.
    4. Mixed-content elements — a tag that carries both text content
       (``#text``) and attributes — are "hoisted":
       ``{"amount": {"@currency": "INR", "#text": "2599.75"}}``
       becomes ``{"amount": "2599.75", "currency": "INR"}``.
    5. Pure-text elements (``{"#text": "hello"}``) collapse to the string.
    """
    if isinstance(obj, list):
        return [_normalize_xml_attrs(item) for item in obj]
    if not isinstance(obj, dict):
        return obj

    # ---- nil check: if THIS dict represents a nil element, return None ----
    for k, v in obj.items():
        if k.startswith("@"):
            local = k[1:]
            if ":" in local:
                local = local.split(":", 1)[1]
            if local.lower() == "nil" and str(v).lower() in ("true", "1"):
                return None

    result: dict = {}
    for k, v in obj.items():
        if k.startswith("@"):
            # Strip '@' prefix
            local = k[1:]
            # Skip namespace declarations (xmlns, xmlns:foo) — these are
            # parser artefacts, not data fields.
            if local == "xmlns" or local.startswith("xmlns:"):
                continue
            # Strip any remaining namespace prefix (e.g. xsi:nil → nil)
            if ":" in local:
                local = local.split(":", 1)[1]
            if local.lower() == "nil":
                continue
            result[local] = _normalize_xml_attrs(v)
        elif k == "#text":
            # Retain temporarily; resolved in mixed-content step below.
            result["#text"] = _normalize_xml_attrs(v)
        else:
            child = _normalize_xml_attrs(v)
            # Mixed-content: child dict has a '#text' key alongside attrs.
            if isinstance(child, dict) and "#text" in child:
                text_val = child.pop("#text")
                result[k] = text_val
                # Hoist the attribute-derived fields as siblings of k.
                for attr_k, attr_v in child.items():
                    result[attr_k] = attr_v
            else:
                result[k] = child

    # Collapse pure-text dict to its value.
    if "#text" in result and len(result) == 1:
        return result["#text"]

    return result


def _coerce_xml_numbers(obj: Any) -> Any:
    """
    Recursively convert numeric strings to Python int or float.

    XML has no type system — every leaf value comes out of xmltodict as a
    string.  This makes "101" → 101 and "85000.5" → 85000.5 so that numeric
    fields MATCH their JSON counterparts instead of being marked EQUIVALENT.

    Booleans are intentionally left alone (they are not strings here).
    """
    if isinstance(obj, dict):
        return {k: _coerce_xml_numbers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_coerce_xml_numbers(item) for item in obj]
    if isinstance(obj, str):
        # Try integer first (avoids turning "6" into 6.0)
        try:
            return int(obj)
        except ValueError:
            pass
        try:
            return float(obj)
        except ValueError:
            pass
    return obj


# ---------------------------------------------------------------------------
# CSV value coercion
# ---------------------------------------------------------------------------

def _coerce_csv_value(v: str) -> Any:
    """
    Attempt to parse a raw CSV string value into its natural Python type.

    CSV has no type system — every cell is a string.  When CSV data was
    originally exported from JSON (or stored with JSON-encoded columns),
    complex values like arrays and objects are serialised as JSON strings.
    This function reverses that:

    - JSON arrays / objects: ``'["a","b"]'`` → ``["a", "b"]``
    - Integers:  ``"42"``   → ``42``
    - Floats:    ``"3.14"`` → ``3.14``
    - Booleans:  ``"true"`` / ``"false"`` → ``True`` / ``False``
    - Null-like: ``""`` / ``"null"`` / ``"none"`` → ``None``
    - Everything else: returned as-is (plain string)
    """
    if v == "" or v.lower() in ("null", "none", "na", "n/a", "nil"):
        return None

    # JSON array or object — try full JSON parse
    if v.startswith(("{", "[")):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            pass

    # Boolean literals
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False

    # Numeric — integer first to avoid turning "6" into 6.0
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass

    return v


# ---------------------------------------------------------------------------
# CSV parser
# ---------------------------------------------------------------------------

def _parse_csv(raw: str) -> tuple[list[dict], str | None]:
    """
    Parse a CSV string into a list of dicts (one dict per data row).
    The first row is treated as the header / column names.

    Handles:
    - comma-delimited (default)
    - automatic delimiter sniffing (tab, semicolon, pipe)
    - quoted fields containing commas or newlines
    - trailing whitespace in values and headers
    """
    try:
        # Sniff the delimiter from the first 2 KB of the input.
        sample = raw[:2048]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        except csv.Error:
            # Default to comma if sniffer cannot decide.
            dialect = csv.excel  # type: ignore[assignment]

        reader = csv.DictReader(
            io.StringIO(raw),
            dialect=dialect,
            skipinitialspace=True,
        )

        rows: list[dict] = []
        for line_num, row in enumerate(reader, start=2):  # header is line 1
            # Strip whitespace from keys and values, then coerce complex values.
            clean_row = {
                k.strip(): _coerce_csv_value(v.strip() if v is not None else "")
                for k, v in row.items()
                if k is not None  # DictReader adds None key for overflow cols
            }
            rows.append(clean_row)

        if not rows:
            return None, (
                "CSV parsed successfully but contains no data rows. "
                "Make sure there is at least one row below the header."
            )

        # Validate that headers were detected (non-empty).
        if reader.fieldnames is None or all(
            f is None or f.strip() == "" for f in reader.fieldnames
        ):
            return None, (
                "CSV header row appears to be empty or unreadable. "
                "The first row must contain column names."
            )

        return rows, None

    except csv.Error as e:
        return None, (
            f"CSV parse error: {e}.\n"
            f"Hint: Make sure the file uses consistent delimiters (comma, tab, "
            f"semicolon, or pipe) and that quoted fields are properly closed."
        )
    except Exception as e:
        return None, (
            f"Unexpected error while parsing CSV: {e}.\n"
            f"Please check your input and try again."
        )


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def _get_snippet(raw: str, line_num: int, context: int = 60) -> str:
    """
    Return a short snippet of *raw* centred on *line_num* (1-based).
    Useful for error messages so the user can see exactly where things broke.
    """
    lines = raw.splitlines()
    idx = line_num - 1
    if 0 <= idx < len(lines):
        snippet = lines[idx].strip()
        if len(snippet) > context:
            snippet = snippet[:context] + "…"
        return repr(snippet)
    return "(line not available)"
