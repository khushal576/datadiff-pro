"""
dns-lookup/server.py

Serves the DNS Lookup tool's single-page frontend. That's the entire job of
this file — the actual DNS queries run client-side in the browser, calling
a public DNS-over-HTTPS provider (Cloudflare or Google) directly via fetch().

Unlike Encode/Decode and Subnet Calculator, this tool genuinely needs
internet access to be useful — there's no offline substitute for "look up
a real domain's real records." That's an accepted, deliberate trade-off
for this one tool (see ../CLAUDE.md).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(
    title="DNS Lookup",
    description="Live DNS record lookup with plain-language explanations.",
)

_UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui() -> HTMLResponse:
    if not _UI_PATH.exists():
        return HTMLResponse(content="<h1>UI not found</h1>", status_code=404)
    return HTMLResponse(content=_UI_PATH.read_text(encoding="utf-8"))
