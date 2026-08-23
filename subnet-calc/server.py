"""
subnet-calc/server.py

Serves the Subnet Calculator tool's single-page frontend. Like Encode/Decode,
this file's only job is serving the static page — every calculation (binary
conversion, mask/CIDR conversion, network/broadcast/host-range math, same-
subnet check) runs client-side in the browser. There's no secret data
involved here (unlike Encode/Decode's keys/passphrases), but keeping the
same client-side pattern means this tool works instantly with zero network
round-trip and stays consistent with the rest of the Toolbox.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(
    title="Subnet Calculator",
    description="Interactive IPv4 subnetting calculator with binary visualization.",
)

_UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui() -> HTMLResponse:
    if not _UI_PATH.exists():
        return HTMLResponse(content="<h1>UI not found</h1>", status_code=404)
    return HTMLResponse(content=_UI_PATH.read_text(encoding="utf-8"))
