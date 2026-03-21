"""
api/app.py

FastAPI application for DataDiff Pro.

Endpoints
---------
GET  /          — serves the single-page UI (ui/index.html)
POST /compare   — runs the full comparison pipeline and returns a diff JSON

The /compare endpoint wires together all core modules:
  normalizer → mapper → diff_engine (equivalence + list_resolver)

All errors are returned as structured JSON with a human-readable message
so the UI can display them without any parsing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

# Core pipeline imports
from core.normalizer import normalize
from core.mapper import parse_mapping, apply_mapping
from core.equivalence import EquivalenceEngine
from core.list_resolver import ListResolver
from core.diff_engine import DiffEngine, DiffRecord, DiffResult

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="DataDiff Pro",
    description="Deep smart diff for JSON, XML, and CSV data.",
    version="1.0.0",
)

# Allow all origins for local dev (the UI is served from the same origin in
# production, but during development people may open the file directly).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Path to the single-file UI
_UI_PATH = Path(__file__).parent.parent / "ui" / "index.html"


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CompareRequest(BaseModel):
    """All fields the UI sends when the user clicks Compare."""

    left_data: str = Field(..., description="Raw text of the left-side input.")
    right_data: str = Field(..., description="Raw text of the right-side input.")
    left_format: str = Field(..., description="Format of the left input: json | xml | csv")
    right_format: str = Field(..., description="Format of the right input: json | xml | csv")
    mapper_csv: Optional[str] = Field(
        default=None,
        description=(
            "Optional field mapping in CSV format: source_path,target_path "
            "(one per line). Applied to the LEFT side before diffing."
        ),
    )
    environment_yaml: Optional[str] = Field(
        default=None,
        description="Optional YAML config with equivalence_rules and list_keys.",
    )


class ErrorResponse(BaseModel):
    ok: bool = False
    error: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_ui() -> HTMLResponse:
    """Serve the single-page frontend."""
    if not _UI_PATH.exists():
        return HTMLResponse(
            content="<h1>UI not found</h1><p>ui/index.html is missing.</p>",
            status_code=404,
        )
    return HTMLResponse(content=_UI_PATH.read_text(encoding="utf-8"))


@app.post("/compare")
async def compare(req: CompareRequest) -> JSONResponse:
    """
    Run the full diff pipeline.

    Steps
    -----
    1. Validate inputs are not empty.
    2. Parse left + right using the normalizer.
    3. Parse and apply field mapping (left side only, optional).
    4. Build EquivalenceEngine + ListResolver from the optional environment YAML.
    5. Run DiffEngine.compare().
    6. Return structured JSON.
    """

    # ------------------------------------------------------------------
    # Step 1 — Basic validation
    # ------------------------------------------------------------------
    if not req.left_data or not req.left_data.strip():
        return _error("Left input is empty. Please paste some data to compare.")
    if not req.right_data or not req.right_data.strip():
        return _error("Right input is empty. Please paste some data to compare.")

    valid_formats = {"json", "xml", "csv"}
    if req.left_format.lower() not in valid_formats:
        return _error(
            f"Invalid left format '{req.left_format}'. "
            f"Choose one of: json, xml, csv."
        )
    if req.right_format.lower() not in valid_formats:
        return _error(
            f"Invalid right format '{req.right_format}'. "
            f"Choose one of: json, xml, csv."
        )

    # ------------------------------------------------------------------
    # Step 2 — Normalize (parse) both sides
    # ------------------------------------------------------------------
    left_data, left_err = normalize(req.left_data, req.left_format)
    if left_err:
        return _error(f"Left side — {left_err}")

    right_data, right_err = normalize(req.right_data, req.right_format)
    if right_err:
        return _error(f"Right side — {right_err}")

    # ------------------------------------------------------------------
    # Step 3 — Apply field mapping to the LEFT side (optional)
    # ------------------------------------------------------------------
    if req.mapper_csv and req.mapper_csv.strip():
        mapping_pairs, map_err = parse_mapping(req.mapper_csv)
        if map_err:
            return _error(f"Field mapper — {map_err}")
        if mapping_pairs:
            left_data = apply_mapping(left_data, mapping_pairs)

    # ------------------------------------------------------------------
    # Step 4 — Build engines from environment YAML
    # ------------------------------------------------------------------
    yaml_text = req.environment_yaml or ""

    # Validate YAML syntax early so we give a clear error if it's broken
    if yaml_text.strip():
        yaml_err = _validate_yaml(yaml_text)
        if yaml_err:
            return _error(f"Environment YAML — {yaml_err}")

    eq_engine   = EquivalenceEngine(yaml_text)
    list_resolver = ListResolver(yaml_text)

    # ------------------------------------------------------------------
    # Step 5 — Run the diff
    # ------------------------------------------------------------------
    engine = DiffEngine(eq_engine, list_resolver)
    try:
        diff_result: DiffResult = engine.compare(left_data, right_data)
    except Exception as exc:
        return _error(
            f"Diff engine encountered an unexpected error: {exc}. "
            f"Please check your input data and try again."
        )

    # ------------------------------------------------------------------
    # Step 6 — Build and return the response
    # ------------------------------------------------------------------
    return JSONResponse(content={
        "ok": True,
        "summary": diff_result.summary,
        "records": [_record_to_dict(r) for r in diff_result.records],
        "list_strategies": diff_result.list_strategies,
        "meta": {
            "left_format":  req.left_format,
            "right_format": req.right_format,
            "mapping_applied": bool(req.mapper_csv and req.mapper_csv.strip()),
            "environment_applied": bool(yaml_text.strip()),
        },
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _error(message: str, status_code: int = 422) -> JSONResponse:
    """Return a consistent error envelope the UI can detect via `ok: false`."""
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "error": message},
    )


def _record_to_dict(record: DiffRecord) -> dict:
    """Convert a DiffRecord dataclass to a plain dict for JSON serialisation."""
    return {
        "path":        record.path,
        "left_value":  record.left_value,
        "right_value": record.right_value,
        "status":      record.status,
    }


def _validate_yaml(yaml_text: str) -> str | None:
    """
    Try to parse *yaml_text* and return a human-readable error string if it
    fails, or None if it is valid.
    """
    try:
        import yaml
        yaml.safe_load(yaml_text)
        return None
    except ImportError:
        return None  # yaml not installed — skip validation, engines will handle it
    except Exception as exc:
        return (
            f"Invalid YAML: {exc}. "
            f"Check indentation and ensure keys are followed by a colon and space."
        )


# ---------------------------------------------------------------------------
# Dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.app:app", host="0.0.0.0", port=8080, reload=True)
