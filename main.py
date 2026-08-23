"""
main.py

Single entrypoint for the whole toolbox website — one process, one
container, one Dockerfile. Serves the home page at "/" and mounts every
tool's own FastAPI app under /tools/<name>/ in the same process (no network
hop, no reverse proxy — just an in-process ASGI mount).

Adding a tool
-------------
1. Import its FastAPI `app` object below.
2. Add one `app.mount("/tools/<name>", that_app)` call.
3. Add one entry to registry.yaml so it gets a card on the home page.
That's it — no Dockerfile, no docker-compose, no network changes needed;
it's all baked into this one image.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from api.app import app as datadiff_pro_app
from encode_decode.server import app as encode_decode_app
from subnet_calc.server import app as subnet_calc_app

app = FastAPI(title="Toolbox", description="One-stop access to internal tools.")

_REGISTRY_PATH = Path(__file__).resolve().parent / "registry.yaml"


# ---------------------------------------------------------------------------
# Home page
# ---------------------------------------------------------------------------

def _load_registry() -> list[dict[str, Any]]:
    if not _REGISTRY_PATH.exists():
        return []
    data = yaml.safe_load(_REGISTRY_PATH.read_text()) or {}
    return data.get("tools", []) or []


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _render_card(tool: dict[str, Any]) -> str:
    icon = tool.get("icon", "🧰")
    title = _esc(tool.get("title", tool.get("name", "")))
    desc = _esc(tool.get("description", ""))
    href = f"/tools/{tool.get('name')}/"
    return f"""
    <a class="card" href="{href}" target="_blank" rel="noopener noreferrer">
      <div class="icon">{icon}</div>
      <div class="title">{title}</div>
      <div class="desc">{desc}</div>
    </a>"""


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    tools = _load_registry()
    cards = "".join(_render_card(t) for t in tools) or (
        '<p class="empty">No tools registered yet — add one to registry.yaml.</p>'
    )
    return HTMLResponse(_HOME_TEMPLATE.replace("{{CARDS}}", cards))


_HOME_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Toolbox</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg: #f4f6fb; --surface: #ffffff; --border: #dde1ef;
      --text: #1c2035; --muted: #6b7180; --accent: #4f5ef0;
    }
    body {
      font-family: 'Segoe UI', system-ui, sans-serif;
      background: var(--bg); color: var(--text);
      min-height: 100vh; padding: 40px 20px;
    }
    header { max-width: 900px; margin: 0 auto 32px; }
    header h1 { font-size: 1.8rem; font-weight: 700; letter-spacing: -0.5px; }
    header h1 span { color: var(--accent); }
    header p { color: var(--muted); font-size: 0.9rem; margin-top: 4px; }
    .grid {
      max-width: 900px; margin: 0 auto;
      display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 16px;
    }
    .card {
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 12px; padding: 20px; text-decoration: none; color: inherit;
      display: flex; flex-direction: column; gap: 6px;
      transition: border-color 0.15s, transform 0.1s;
    }
    .card:hover { border-color: var(--accent); transform: translateY(-2px); }
    .card .icon { font-size: 1.8rem; }
    .card .title { font-weight: 700; font-size: 1.05rem; }
    .card .desc { font-size: 0.82rem; color: var(--muted); line-height: 1.5; }
    .empty { color: var(--muted); font-size: 0.9rem; max-width: 900px; margin: 0 auto; }
  </style>
</head>
<body>
  <header>
    <h1>Tool<span>box</span></h1>
    <p>One-stop access to internal tools</p>
  </header>
  <div class="grid">{{CARDS}}</div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Mount every tool's own app under /tools/<name>
# ---------------------------------------------------------------------------

app.mount("/tools/datadiff-pro", datadiff_pro_app)
app.mount("/tools/encode-decode", encode_decode_app)
app.mount("/tools/subnet-calc", subnet_calc_app)
