"""
curl-builder/server.py

Serves the cURL Builder tool's single-page frontend. That's the entire job
of this file — every actual operation (building and escaping the curl
command for bash/zsh, cmd.exe, and PowerShell) runs client-side in the
browser. No URL, header, credential, or body the user enters is ever sent
to this server or logged anywhere. This tool only ever *generates a string*
for the user to run themselves — it never sends the request itself.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(
    title="cURL Builder",
    description="Client-side curl command generator — form in, copy-pasteable curl command out.",
)

_UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui() -> HTMLResponse:
    if not _UI_PATH.exists():
        return HTMLResponse(content="<h1>UI not found</h1>", status_code=404)
    return HTMLResponse(content=_UI_PATH.read_text(encoding="utf-8"))
