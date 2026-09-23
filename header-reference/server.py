"""
header-reference/server.py

Serves the HTTP Header Reference tool's single-page frontend. That's the
entire job of this file — the header glossary itself is a static data set
baked into the page; there's nothing to look up on a server and nothing the
user types (search text) is ever sent anywhere.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(
    title="HTTP Header Reference",
    description="Browsable, categorized glossary of widely-used HTTP headers.",
)

_UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui() -> HTMLResponse:
    if not _UI_PATH.exists():
        return HTMLResponse(content="<h1>UI not found</h1>", status_code=404)
    return HTMLResponse(content=_UI_PATH.read_text(encoding="utf-8"))
