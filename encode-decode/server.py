"""
encode-decode/server.py

Serves the Encode/Decode tool's single-page frontend. That's the entire job
of this file — every actual operation (Base64, Hex, Gzip, AES-GCM,
RSA-OAEP, JWT, hashing) runs client-side in the browser via the Web Crypto
API and native compression streams. No input, key, passphrase, or secret is
ever sent to this server or logged anywhere.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(
    title="Encode/Decode",
    description="Client-side encoding, compression, and cryptography toolkit.",
)

_UI_PATH = Path(__file__).resolve().parent / "ui" / "index.html"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui() -> HTMLResponse:
    if not _UI_PATH.exists():
        return HTMLResponse(content="<h1>UI not found</h1>", status_code=404)
    return HTMLResponse(content=_UI_PATH.read_text(encoding="utf-8"))
