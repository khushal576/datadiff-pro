"""
schema-map/server.py

Serves Schema Map's single-page frontend and its backend: connect to a
Postgres database, then fetch its table/foreign-key structure for the
progressive-disclosure graph view. See the plan this tool was built from
(schema-map/CLAUDE.md has the durable version) for the full design — the
short version: a read-only explorer for large, poorly-documented schemas,
built around "never render more than what's currently expanded" instead
of one big unreadable graph of every table at once.

Endpoints
---------
GET  /              — the single-page UI
POST /connect        — open a pool against one Postgres database (host/port/database/username/password)
POST /disconnect      — close the pool, idempotent
GET  /status          — current connection state (never the password)
GET  /schemas          — every non-system schema, with its table count
GET  /graph             — tables + foreign keys for one schema (or all) — no column data, see introspection_postgres.py
GET  /table/{schema}/{table} — one table's columns, fetched only when that table is clicked
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

try:  # package import when mounted inside the toolbox (schema_map.*)
    from schema_map import db_engine, introspection_postgres
except ImportError:  # flat import when run standalone from within this folder
    import db_engine
    import introspection_postgres

app = FastAPI(
    title="Schema Map",
    description="Visual, progressive-disclosure table/relationship explorer for Postgres.",
)

_UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"


class ConnectRequest(BaseModel):
    host: str
    port: int = 5432
    database: str
    username: str
    password: str


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui() -> HTMLResponse:
    if not _UI_PATH.exists():
        return HTMLResponse(content="<h1>UI not found</h1>", status_code=404)
    return HTMLResponse(content=_UI_PATH.read_text(encoding="utf-8"))


@app.post("/connect")
async def connect(body: ConnectRequest):
    try:
        return await db_engine.connect(body.host, body.port, body.database, body.username, body.password)
    except db_engine.ConnectError as exc:
        return _error(str(exc))


@app.post("/disconnect")
async def disconnect():
    return db_engine.disconnect()


@app.get("/status")
async def status():
    return db_engine.status()


@app.get("/schemas")
async def schemas():
    try:
        return {"schemas": await db_engine.run(introspection_postgres.get_schemas)}
    except db_engine.ConnectError as exc:
        return _error(str(exc))


@app.get("/graph")
async def graph(schema: Optional[str] = None):
    # schema=None (the query param omitted) means "all schemas" —
    # introspection_postgres.get_graph() already treats None that way.
    try:
        return await db_engine.run(introspection_postgres.get_graph, schema)
    except db_engine.ConnectError as exc:
        return _error(str(exc))


@app.get("/table/{schema}/{table}")
async def table_columns(schema: str, table: str):
    try:
        columns = await db_engine.run(introspection_postgres.get_table_columns, schema, table)
        return {"schema": schema, "table": table, "columns": columns}
    except db_engine.ConnectError as exc:
        return _error(str(exc))
