"""
packet-journey/server.py

Serves the Packet Journey tool's single-page frontend. That's the entire
job of this file — every bit of content is static, no network calls, no
backend logic. Same reasoning as the other reference-style tools here.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(
    title="Packet Journey",
    description="Watch one real request travel through every network layer — what gets added, what it's called, and what it actually looks like.",
)

_UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui() -> HTMLResponse:
    if not _UI_PATH.exists():
        return HTMLResponse(content="<h1>UI not found</h1>", status_code=404)
    return HTMLResponse(content=_UI_PATH.read_text(encoding="utf-8"))
