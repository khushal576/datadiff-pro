"""
sql-studio/db_engine.py

Live Postgres connection state for SQL Studio's Run feature. See
sql-studio/CLAUDE.md for the full design writeup — the short version:

**One global connection, not a per-cookie session dict.** Every other
stateful tool in this repo (df-studio) keys its state per browser-tab
cookie because each tab legitimately owns independent data — Tab A's
uploaded CSV has nothing to do with Tab B's. SQL Studio's live connection
is different: the owner's own framing was "connect to a single database
at a time" with "a pool of 3 connections" — a global toggle, not N
independent per-tab resources. Keying this the df-studio way would let
every open tab silently open its own 3-connection pool (3 tabs = up to 9
live connections against the target database), which breaks the "pool of
3" requirement outright. One module-level STATE is also one thing to
bound and clean up instead of N independently-leakable ones. GET /status
naturally reports the same answer to every tab — that's the correct
behavior for "a single database at a time," not a bug.

Every psycopg call is synchronous (psycopg's sync API, not
AsyncConnectionPool) and run via asyncio.to_thread — same idiom
df-studio/server.py already uses (and documents) for the same reason: with
--workers 1, a blocking call made directly inside `async def` freezes the
whole process's event loop for its entire duration.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any, Optional

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg_pool import ConnectionPool

try:  # package import when mounted inside the toolbox (sql_studio.*)
    from sql_studio import query_guard
except ImportError:  # flat import when run standalone from within this folder
    import query_guard

IDLE_TIMEOUT_SECONDS = 20 * 60  # a forgotten tab: fully close the pool, drop the password from memory
REAPER_INTERVAL_SECONDS = 60
ROW_CAP = query_guard.ROW_CAP

_PASSWORD_RE = re.compile(r"password\s*=\s*\S+", re.IGNORECASE)


def _scrub(message: str) -> str:
    """Defense-in-depth: strip anything shaped like 'password=...' from an
    error message before it's logged or returned to the browser. Verified
    against a real wrong-password/wrong-database failure (see
    sql-studio/CLAUDE.md) that libpq/psycopg don't embed the cleartext
    password in their own exception text today — this stays in place for
    a future version or a differently-shaped error string, not because
    today's version was found to leak anything."""
    return _PASSWORD_RE.sub("password=***", message)


class ConnectError(Exception):
    pass


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]


@dataclass
class ConnectionState:
    host: str
    port: int
    database: str
    username: str
    pool: ConnectionPool
    connected_at: float
    last_used_at: float
    last_result: Optional[QueryResult] = None


STATE: Optional[ConnectionState] = None
_reaper_task: Optional[asyncio.Task] = None


def _touch() -> None:
    if STATE is not None:
        STATE.last_used_at = time.monotonic()


async def _reaper_loop() -> None:
    """Closes an idle pool so a forgotten browser tab doesn't hold live
    connections open against the target database indefinitely. Runs for
    the lifetime of the process once started — the loop itself outlives
    any one connection, since STATE gets replaced/cleared by connect() /
    disconnect(), not by this task ending."""
    while True:
        await asyncio.sleep(REAPER_INTERVAL_SECONDS)
        if STATE is not None and (time.monotonic() - STATE.last_used_at) > IDLE_TIMEOUT_SECONDS:
            disconnect()


def _ensure_reaper_started() -> None:
    # Started lazily on first successful connect, not via a FastAPI
    # lifespan hook — this tool's app is mounted into main.py's app via
    # app.mount(...), and Starlette does not forward lifespan startup/
    # shutdown events into mounted sub-apps, so a lifespan handler defined
    # here would silently never fire under the real toolbox process. This
    # way doesn't depend on that.
    global _reaper_task
    if _reaper_task is None or _reaper_task.done():
        _reaper_task = asyncio.get_event_loop().create_task(_reaper_loop())


def status() -> dict[str, Any]:
    if STATE is None:
        return {"connected": False}
    return {
        "connected": True,
        "host": STATE.host,
        "port": STATE.port,
        "database": STATE.database,
        "username": STATE.username,
        "connected_at": STATE.connected_at,
        "last_used_at": STATE.last_used_at,
    }


STATEMENT_TIMEOUT_MS = 15_000
# Every connection this pool ever opens gets this session-level default
# (libpq's "options" conninfo param passes "-c NAME=VALUE" flags to the
# backend at connection start) — closes the real gap the LIMIT-wrap alone
# leaves open: LIMIT 500 bounds ROWS RETURNED, not query COST. A GROUP BY/
# window query over a huge table can still take a long time computing the
# aggregation before the outer LIMIT ever trims the output (see
# sql-studio/CLAUDE.md's "500-row cap is a LIMIT-wrap, not a cost
# limiter"). Without this, that query just hangs the connection — with
# only 3 in the pool, three such queries exhausts it entirely. Applies to
# every statement on that physical connection for its lifetime, not just
# the first one; Postgres raises QueryCanceled ("canceling statement due
# to statement timeout") when it fires, surfaced to the UI like any other
# query error.


def _connect_sync(host: str, port: int, database: str, username: str, password: str) -> ConnectionPool:
    conninfo = make_conninfo(
        host=host, port=port, dbname=database, user=username, password=password,
        options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
    )
    # Validate credentials with a direct, UNPOOLED connection first, not by
    # opening the pool and hoping a bad host/port/db/password surfaces on
    # its own. Two real bugs found by testing this against an actual
    # wrong-password case, not assumed from the docs: (1) with min_size=0,
    # pool.open() doesn't eagerly create any real connection — it only
    # starts the pool's background worker, so a bad password wasn't
    # caught until the first query; (2) even after forcing a checkout,
    # ConnectionPool retries failed connection attempts in the background
    # and a timed-out checkout raises a generic "couldn't get a connection
    # after N sec", not the real error — it also takes the full timeout to
    # fail instead of failing immediately. A plain, one-off psycopg.connect()
    # raises the actual OperationalError (e.g. "password authentication
    # failed for user ...") right away, so that's what validates here;
    # the pool is only constructed once this succeeds.
    with psycopg.connect(conninfo, connect_timeout=10) as conn:
        conn.execute("SELECT 1")
    pool = ConnectionPool(
        conninfo, min_size=0, max_size=3, max_idle=300, max_lifetime=1800, timeout=10, open=False,
    )
    pool.open(wait=True, timeout=10)
    return pool


async def connect(host: str, port: int, database: str, username: str, password: str) -> dict[str, Any]:
    global STATE
    disconnect()  # only one live connection at a time — replacing an existing one closes it first
    try:
        pool = await asyncio.to_thread(_connect_sync, host, port, database, username, password)
    except Exception as exc:  # noqa: BLE001 - psycopg/libpq raise several distinct exception types here
        raise ConnectError(_scrub(str(exc))) from exc
    now = time.monotonic()
    STATE = ConnectionState(
        host=host, port=port, database=database, username=username,
        pool=pool, connected_at=now, last_used_at=now,
    )
    _ensure_reaper_started()
    return status()


def disconnect() -> dict[str, Any]:
    global STATE
    if STATE is not None:
        try:
            STATE.pool.close(timeout=5)
        except Exception:  # noqa: BLE001 - best-effort close; must not block clearing STATE
            pass
        STATE = None
    return {"connected": False}


def _execute_sync(classification: "query_guard.Classification") -> dict[str, Any]:
    assert STATE is not None
    with STATE.pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(classification.executable_sql)
            if cur.description is not None:
                columns = [d.name for d in cur.description]
                rows = [list(r) for r in cur.fetchall()]
                conn.commit()
                STATE.last_result = QueryResult(columns=columns, rows=rows)
                return {
                    "kind": "rows",
                    "columns": columns,
                    "rows": rows,
                    "row_count_returned": len(rows),
                    # A heuristic, not an exact "more rows exist" signal: if
                    # Postgres handed back exactly ROW_CAP rows, the outer
                    # LIMIT most likely trimmed a larger result. The rare
                    # case where the true result is exactly ROW_CAP rows
                    # looks identical and is harmlessly mislabeled capped.
                    "capped": len(rows) >= ROW_CAP,
                }
            rowcount = cur.rowcount
            conn.commit()
            STATE.last_result = None
            if rowcount is not None and rowcount >= 0 and classification.keyword in ("INSERT", "UPDATE", "DELETE"):
                noun = "row" if rowcount == 1 else "rows"
                message = f"{classification.keyword} OK — {rowcount} {noun} affected."
            else:
                message = f"{classification.keyword} OK."
            return {"kind": "status", "message": message}


async def execute(classification: "query_guard.Classification") -> dict[str, Any]:
    if STATE is None:
        raise ConnectError("Not connected — connect to a database first.")
    start = time.monotonic()
    try:
        result = await asyncio.to_thread(_execute_sync, classification)
    except Exception as exc:  # noqa: BLE001 - surface the real Postgres error to the UI, scrubbed
        raise ConnectError(_scrub(str(exc))) from exc
    result["elapsed_ms"] = round((time.monotonic() - start) * 1000, 1)
    _touch()
    return result


def last_result() -> Optional[QueryResult]:
    return STATE.last_result if STATE is not None else None
