"""
sql-studio/query_guard.py

Server-side statement splitting + classification for SQL Studio's Run
feature — the actual security/safety boundary, not a UX nicety. The
client has its own copy of the same tokenizer/splitting logic
(tokenizePlpgsqlBody in ui/index.html) so the destructive-statement
confirmation dialog can appear instantly, with zero network round-trip,
but that copy is UX only. This module is what actually decides whether a
query runs — a client that claims `confirmed: true` for a DELETE it never
actually showed the user still gets re-classified here before anything
touches the database (see server.py's /query handler).

Keep this in sync with tokenizePlpgsqlBody() in ui/index.html by hand if
you ever change either one — same string/comment/dollar-quote splitting
rules, deliberately two independent implementations (JS in the browser,
Python here) because the server can never trust anything computed
client-side for a decision this consequential.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ROW_CAP = 500

DESTRUCTIVE_KEYWORDS = {"DROP", "TRUNCATE", "DELETE", "ALTER"}
ROW_RETURNING_KEYWORDS = {"SELECT", "WITH", "VALUES", "TABLE"}
DML_KEYWORDS = {"INSERT", "UPDATE", "DELETE"}

_DOLLAR_TAG_RE = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)?\$")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_RETURNING_RE = re.compile(r"\bRETURNING\b", re.IGNORECASE)


class GuardError(ValueError):
    pass


@dataclass
class Segment:
    type: str  # "code" | "string" | "linecomment" | "blockcomment"
    text: str


def tokenize(text: str) -> list[Segment]:
    """Python port of tokenizePlpgsqlBody() in ui/index.html — splits
    `text` into code / string / comment segments so a ';' or a keyword
    sitting inside a string, a comment, or a $$...$$ dollar-quoted body is
    never mistaken for a statement boundary or the statement's leading
    keyword. Must stay behaviorally identical to the JS version."""
    segments: list[Segment] = []
    i = 0
    n = len(text)
    buf: list[str] = []

    def flush_code() -> None:
        if buf:
            segments.append(Segment("code", "".join(buf)))
            buf.clear()

    while i < n:
        ch = text[i]
        two = text[i:i + 2]
        if ch == "'":
            flush_code()
            j = i + 1
            chars = ["'"]
            while j < n:
                if text[j] == "'" and j + 1 < n and text[j + 1] == "'":
                    chars.append("''")
                    j += 2
                    continue
                if text[j] == "'":
                    chars.append("'")
                    j += 1
                    break
                chars.append(text[j])
                j += 1
            segments.append(Segment("string", "".join(chars)))
            i = j
            continue
        if two == "--":
            flush_code()
            j = i
            while j < n and text[j] != "\n":
                j += 1
            segments.append(Segment("linecomment", text[i:j]))
            i = j
            continue
        if two == "/*":
            flush_code()
            end = text.find("*/", i + 2)
            j = n if end == -1 else end + 2
            segments.append(Segment("blockcomment", text[i:j]))
            i = j
            continue
        if ch == "$":
            m = _DOLLAR_TAG_RE.match(text[i:])
            if m:
                tag = m.group(0)
                end = text.find(tag, i + len(tag))
                if end != -1:
                    flush_code()
                    segments.append(Segment("string", text[i:end + len(tag)]))
                    i = end + len(tag)
                    continue
        buf.append(ch)
        i += 1
    flush_code()
    return segments


def _is_only_comments_or_whitespace(statement: str) -> bool:
    """True for a chunk that's just a trailing/leading comment with no real
    SQL in it — e.g. the "-- trailing comment" left over after splitting
    "SELECT 1; -- trailing comment" on its ';'. Such a chunk isn't a second
    statement and shouldn't count against the one-statement-per-Run limit."""
    for seg in tokenize(statement):
        if seg.type == "code" and seg.text.strip():
            return False
        if seg.type == "string":
            return False
    return True


def split_statements(text: str) -> list[str]:
    """Split on top-level ';' characters only — those found inside
    'code'-typed segments. A ';' inside a string, a comment, or a
    dollar-quoted procedure body is never a statement boundary. Returns
    non-empty, trimmed statement texts (comment-only chunks dropped, see
    _is_only_comments_or_whitespace), each segment slice rejoined verbatim
    (not reformatted)."""
    segments = tokenize(text)
    statements: list[str] = []
    current: list[str] = []
    for seg in segments:
        if seg.type == "code":
            parts = seg.text.split(";")
            for idx, part in enumerate(parts):
                current.append(part)
                if idx < len(parts) - 1:
                    statements.append("".join(current))
                    current = []
        else:
            current.append(seg.text)
    if current:
        statements.append("".join(current))
    trimmed = (s.strip() for s in statements)
    return [s for s in trimmed if s and not _is_only_comments_or_whitespace(s)]


def _first_keyword(statement: str) -> str:
    for seg in tokenize(statement):
        if seg.type == "code":
            m = _IDENT_RE.search(seg.text)
            if m:
                return m.group(0).upper()
        elif seg.type in ("linecomment", "blockcomment"):
            continue
        # A string/dollar-quoted segment appearing before any code is
        # unusual for a real statement's leading keyword — keep scanning
        # rather than stopping here.
    return ""


def _has_returning(statement: str) -> bool:
    return any(
        seg.type == "code" and _RETURNING_RE.search(seg.text)
        for seg in tokenize(statement)
    )


@dataclass
class Classification:
    keyword: str
    is_destructive: bool
    returns_rows: bool
    executable_sql: str  # what actually gets sent to Postgres (LIMIT-wrapped where applicable)


def classify(statement: str) -> Classification:
    keyword = _first_keyword(statement)
    is_destructive = keyword in DESTRUCTIVE_KEYWORDS
    returning = keyword in DML_KEYWORDS and _has_returning(statement)

    if keyword in ROW_RETURNING_KEYWORDS:
        return Classification(keyword, is_destructive, True, f"SELECT * FROM ({statement}) AS _sq LIMIT {ROW_CAP}")
    if keyword in DML_KEYWORDS and returning:
        return Classification(keyword, is_destructive, True, f"WITH _dml AS ({statement}) SELECT * FROM _dml LIMIT {ROW_CAP}")
    return Classification(keyword, is_destructive, False, statement)


def prepare(sql_text: str) -> Classification:
    """The one entry point server.py calls. Raises GuardError (caller turns
    this into a clean 400) for anything that can't go through Run at all —
    empty input, more than one statement, or COPY (file/stream semantics
    don't fit a single query-string executor)."""
    statements = split_statements(sql_text)
    if not statements:
        raise GuardError("Nothing to run — the query is empty.")
    if len(statements) > 1:
        raise GuardError(
            f"Run works on exactly one statement at a time (found {len(statements)}). "
            "Split into separate Run clicks — Format still handles whole scripts/procedures."
        )
    statement = statements[0]
    keyword = _first_keyword(statement)
    if keyword == "COPY":
        raise GuardError("COPY is not supported through Run — use psql.")
    return classify(statement)
