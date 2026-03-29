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
from core.mapper import parse_mapping, apply_mapping, MapTrace
from core.equivalence import EquivalenceEngine
from core.list_resolver import ListResolver
from core.diff_engine import DiffEngine, DiffRecord, DiffResult
from core.deep_expander import deep_expand
from core.validator import validate_transform, ValidationResult

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
            "(one per line). Applied to the side specified by mapper_direction."
        ),
    )
    mapper_direction: str = Field(
        default="left_to_right",
        description=(
            "Direction the mapper is applied: "
            "'left_to_right' renames LEFT fields to match RIGHT (default), "
            "'right_to_left' renames RIGHT fields to match LEFT."
        ),
    )
    strict_mode: bool = Field(
        default=False,
        description=(
            "When True, the mapper raises an error if a declared source path "
            "is not found in the data instead of silently skipping it."
        ),
    )
    multi_match_rule: str = Field(
        default="keep_list",
        description=(
            "What to do when a mapping path resolves to multiple values "
            "(e.g. a field inside a list): "
            "'keep_list' (default) | 'flatten' | 'pick_first'."
        ),
    )
    deep_mode: bool = Field(
        default=False,
        description=(
            "When True, recursively scan all string-valued fields on both sides "
            "and attempt to parse them as JSON or XML before diffing. "
            "Useful when structured data is stored as escaped strings."
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
    # Step 3 — Apply field mapping (optional)
    # Direction: left_to_right → rename LEFT fields to match RIGHT (default)
    #            right_to_left → rename RIGHT fields to match LEFT
    # ------------------------------------------------------------------
    direction = (req.mapper_direction or "left_to_right").strip().lower()
    if direction not in ("left_to_right", "right_to_left"):
        return _error(
            f"Invalid mapper_direction '{req.mapper_direction}'. "
            f"Use 'left_to_right' or 'right_to_left'."
        )

    # ------------------------------------------------------------------
    # Step 3a — Deep Mode: expand string-encoded JSON/XML values BEFORE
    # mapping so the mapper can navigate into expanded fields.
    # ------------------------------------------------------------------
    if req.deep_mode:
        left_data  = deep_expand(left_data)
        right_data = deep_expand(right_data)

    map_traces: list[MapTrace] = []
    validation: ValidationResult | None = None
    mapping_pairs: list = []

    if req.mapper_csv and req.mapper_csv.strip():
        mapping_pairs, map_err = parse_mapping(req.mapper_csv)
        if map_err:
            return _error(f"Field mapper — {map_err}")
        if mapping_pairs:
            try:
                if direction == "left_to_right":
                    original_snapshot = left_data
                    left_data, map_traces = apply_mapping(
                        left_data, mapping_pairs,
                        strict_mode=req.strict_mode,
                        multi_match_rule=req.multi_match_rule,
                    )
                    validation = validate_transform(
                        original_snapshot, left_data,
                        mapping_pairs, map_traces,
                        strict_mode=req.strict_mode,
                    )
                else:  # right_to_left
                    original_snapshot = right_data
                    right_data, map_traces = apply_mapping(
                        right_data, mapping_pairs,
                        strict_mode=req.strict_mode,
                        multi_match_rule=req.multi_match_rule,
                    )
                    validation = validate_transform(
                        original_snapshot, right_data,
                        mapping_pairs, map_traces,
                        strict_mode=req.strict_mode,
                    )
            except ValueError as exc:
                # Raised by apply_mapping when strict_mode=True and path missing
                return _error(f"Field mapper (strict mode) — {exc}")

            if validation and not validation.passed:
                return _error(
                    "Mapping validation failed:\n"
                    + "\n".join(f"  • {e}" for e in validation.errors)
                )

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
    engine = DiffEngine(eq_engine, list_resolver, deep_mode=req.deep_mode)
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
    warnings = validation.warnings if validation else []

    return JSONResponse(content={
        "ok": True,
        "summary": diff_result.summary,
        "records": [_record_to_dict(r) for r in diff_result.records],
        "list_strategies": diff_result.list_strategies,
        "map_traces": [_trace_to_dict(t) for t in map_traces],
        "validation": _validation_to_dict(validation) if validation else None,
        "warnings": warnings,
        "meta": {
            "left_format":  req.left_format,
            "right_format": req.right_format,
            "mapping_applied":   bool(req.mapper_csv and req.mapper_csv.strip()),
            "mapper_direction":  direction,
            "strict_mode":       req.strict_mode,
            "multi_match_rule":  req.multi_match_rule,
            "deep_mode":         req.deep_mode,
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
    d: dict = {
        "path":        record.path,
        "left_value":  record.left_value,
        "right_value": record.right_value,
        "status":      record.status,
    }
    if record.trace:
        d["trace"] = record.trace
    return d


def _trace_to_dict(trace: MapTrace) -> dict:
    """Convert a MapTrace dataclass to a plain dict for JSON serialisation."""
    return {
        "rule_index":          trace.rule_index,
        "src_path":            trace.src_path,
        "tgt_path":            trace.tgt_path,
        "resolved_src_paths":  trace.resolved_src_paths,
        "action":              trace.action,
        "detail":              trace.detail,
    }


def _validation_to_dict(v: ValidationResult) -> dict:
    """Convert a ValidationResult dataclass to a plain dict."""
    return {
        "passed":        v.passed,
        "warnings":      v.warnings,
        "errors":        v.errors,
        "dropped_paths": v.dropped_paths,
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
