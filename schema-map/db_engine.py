"""
schema-map/db_engine.py

Live Postgres connection for Schema Map — same idiom as
sql-studio/db_engine.py (global STATE, psycopg_pool, credential
pre-validation before opening the pool, idle reaper, password never
persisted), but a genuinely separate module-level global, not shared
with SQL Studio's own connection. Schema Map and SQL Studio might
reasonably be pointed at two different databases at the same time — see
the plan this was built from for the full reasoning.

Pool is smaller (max_size=2) than SQL Studio's (3): this tool only ever
runs a handful of introspection queries per fetch, never sustained query
traffic.

Unlike sql-studio/db_engine.py, there's no query_guard here and no
concept of running arbitrary user-typed SQL — Schema Map only ever runs
its own fixed introspection queries (schema-map/introspection_postgres.py),
so the one thing this module needs beyond connect/disconnect/status is
`run()`, a generic "execute this plain function against a pooled
connection" helper.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg_pool import ConnectionPool

IDLE_TIMEOUT_SECONDS = 20 * 60  # a forgotten tab: fully close the pool, drop the password from memory
REAPER_INTERVAL_SECONDS = 60

_PASSWORD_RE = re.compile(r"password\s*=\s*\S+", re.IGNORECASE)


def _scrub(message: str) -> str:
    """Defense-in-depth: strip anything shaped like 'password=...' from an
    error message before it's logged or returned to the browser. See
    sql-studio/CLAUDE.md for the verification trail on why this is
    believed-safe-by-design, not just assumed."""
    return _PASSWORD_RE.sub("password=***", message)


class ConnectError(Exception):
    pass


@dataclass
class ConnectionState:
    host: str
    port: int
    database: str
    username: str
    pool: ConnectionPool
    connected_at: float
    last_used_at: float


STATE: Optional[ConnectionState] = None
_reaper_task: Optional[asyncio.Task] = None


def _touch() -> None:
    if STATE is not None:
        STATE.last_used_at = time.monotonic()


async def _reaper_loop() -> None:
    """Closes an idle pool so a forgotten browser tab doesn't hold live
    connections open against the target database indefinitely — same
    reasoning and threshold as sql-studio/db_engine.py's reaper."""
    while True:
        await asyncio.sleep(REAPER_INTERVAL_SECONDS)
        if STATE is not None and (time.monotonic() - STATE.last_used_at) > IDLE_TIMEOUT_SECONDS:
            disconnect()


def _ensure_reaper_started() -> None:
    # Started lazily on first successful connect, not via a FastAPI
    # lifespan hook — main.py mounts this tool's app via app.mount(...),
    # and Starlette does not forward lifespan events into mounted
    # sub-apps (see sql-studio/CLAUDE.md for the same gotcha there).
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


def _connect_sync(host: str, port: int, database: str, username: str, password: str) -> ConnectionPool:
    conninfo = make_conninfo(host=host, port=port, dbname=database, user=username, password=password)
    # Validate credentials with a direct, UNPOOLED connection first — NOT
    # by opening the pool and hoping a bad host/port/db/password surfaces
    # on its own. A real bug, already found and fixed once in
    # sql-studio/db_engine.py, don't reintroduce it here: with
    # min_size=0, pool.open() doesn't eagerly create any real connection
    # (it only starts the pool's background worker), so a bad password
    # wouldn't be caught until the first real query ran.
    with psycopg.connect(conninfo, connect_timeout=10) as conn:
        conn.execute("SELECT 1")
    pool = ConnectionPool(
        conninfo, min_size=0, max_size=2, max_idle=300, max_lifetime=1800, timeout=10, open=False,
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


async def run(fn: Callable[..., Any], *args: Any) -> Any:
    """Runs `fn(conn, *args)` against a pooled connection in a worker
    thread — the one integration point introspection_postgres.py uses to
    actually query Postgres. `fn` is a plain sync function taking a
    psycopg connection first; this handles the pool checkout, the
    to_thread wrapping (blocking psycopg calls directly inside `async
    def` would freeze the whole process under --workers 1 — see
    sql-studio/CLAUDE.md), and turning any failure into a scrubbed
    ConnectError."""
    if STATE is None:
        raise ConnectError("Not connected — connect to a database first.")

    def _sync() -> Any:
        with STATE.pool.connection() as conn:
            return fn(conn, *args)

    try:
        result = await asyncio.to_thread(_sync)
    except Exception as exc:  # noqa: BLE001
        raise ConnectError(_scrub(str(exc))) from exc
    _touch()
    return result
