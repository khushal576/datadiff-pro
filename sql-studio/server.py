"""
sql-studio/server.py

Serves the SQL Studio tool's single-page frontend, plus a real backend for
the Run feature: connect to a Postgres database, run one statement at a
time against it, and export the result as CSV/JSON.

Format, Templates, and Schema autocomplete are UNCHANGED — still entirely
client-side, nothing involved in those features is ever sent here. Only
Run/Connect/Export go over the network, and only to the database the user
explicitly connected to. See sql-studio/CLAUDE.md for the full design
writeup (why a single global connection instead of df-studio's per-cookie
session pattern, the row-cap mechanism, the destructive-statement double
check, why export reads a cached result instead of re-running SQL).

Endpoints
---------
GET  /              — the single-page UI
POST /connect        — open a pool against one Postgres database (host/port/database/username/password)
POST /disconnect      — close the pool, idempotent
GET  /status          — current connection state, polled by every open tab (never includes the password)
POST /query            — run exactly one statement; destructive statements need confirmed: true
GET  /export/csv        — download the last successful query's result as CSV
GET  /export/json        — download the same result as JSON
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

try:  # package import when mounted inside the toolbox (sql_studio.*)
    from sql_studio import db_engine, query_guard
except ImportError:  # flat import when run standalone from within this folder
    import db_engine
    import query_guard

app = FastAPI(
    title="SQL Studio",
    description="Postgres SQL editor, formatter, schema-aware autocomplete, and live query runner.",
)

_UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"


class ConnectRequest(BaseModel):
    host: str
    port: int = 5432
    database: str
    username: str
    password: str


class QueryRequest(BaseModel):
    sql: str
    confirmed: bool = False


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


@app.post("/query")
async def run_query(body: QueryRequest):
    try:
        classification = query_guard.prepare(body.sql)
    except query_guard.GuardError as exc:
        return _error(str(exc))

    if classification.is_destructive and not body.confirmed:
        return JSONResponse(
            status_code=409,
            content={
                "requires_confirmation": True,
                "kind": classification.keyword,
                "message": f"This is a {classification.keyword} statement. Confirm to run it.",
            },
        )

    try:
        return await db_engine.execute(classification)
    except db_engine.ConnectError as exc:
        return _error(str(exc))


def _require_last_result():
    result = db_engine.last_result()
    if result is None:
        return None
    return result


@app.get("/export/csv")
async def export_csv():
    result = _require_last_result()
    if result is None:
        return _error("Nothing to export — run a query that returns rows first.")
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(result.columns)
    writer.writerows(result.rows)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="query_result.csv"'},
    )


@app.get("/export/json")
async def export_json():
    result = _require_last_result()
    if result is None:
        return _error("Nothing to export — run a query that returns rows first.")
    records = [dict(zip(result.columns, row)) for row in result.rows]
    return Response(
        content=json.dumps(records, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="query_result.json"'},
    )
