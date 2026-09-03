"""
vlan-designer/server.py

Serves the VLAN Designer tool's single-page frontend. That's the entire
job of this file — every calculation (subnet math, VLAN/port planning,
reachability logic) runs client-side. No network calls, no secrets, no
backend logic at all — same reasoning as Subnet Calculator: it's pure
arithmetic/logic, kept client-side for consistency and instant feedback.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(
    title="VLAN Designer",
    description="Design VLANs, switch ports, and inter-VLAN routing — see exactly why two devices can or can't reach each other.",
)

_UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui() -> HTMLResponse:
    if not _UI_PATH.exists():
        return HTMLResponse(content="<h1>UI not found</h1>", status_code=404)
    return HTMLResponse(content=_UI_PATH.read_text(encoding="utf-8"))
