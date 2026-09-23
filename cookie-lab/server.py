"""
cookie-lab/server.py

Serves the Cookie Lab tool's single-page frontend. That's the entire job
of this file — same as every sibling tool. Unlike the other reference
tools though, this one's frontend performs REAL, persistent document.cookie
reads and writes (a live playground, not a generator) — those side effects
live entirely in the browser's own cookie jar for this origin. Nothing is
ever sent to this server; this endpoint's only job is to hand back the one
static page.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(
    title="Cookie Lab",
    description="A live document.cookie playground plus a full HTTP cookie reference and decision guide.",
)

_UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui() -> HTMLResponse:
    if not _UI_PATH.exists():
        return HTMLResponse(content="<h1>UI not found</h1>", status_code=404)
    return HTMLResponse(content=_UI_PATH.read_text(encoding="utf-8"))
