"""
df-studio/templates_store.py

Saved, reusable transformation pipelines ("templates"): a named list of
{type, params} steps that can be replayed against any future upload — the
point is "clean this kind of file the same way every time" without
re-building the pipeline by hand. Stored as one JSON file on disk
(data/templates.json, created on first save). Single-user local tool, so
no locking/concurrency handling — last write wins, same as everything
else in this tool.

Only {type, params} are persisted, never the generated code string —
code is always regenerated fresh from the current STEP_HANDLERS when a
template is applied, so an edit to a step handler's codegen is reflected
in old templates automatically.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_STORE_PATH = Path(__file__).resolve().parent / "data" / "templates.json"


def _load() -> dict[str, list[dict[str, Any]]]:
    if not _STORE_PATH.exists():
        return {}
    return json.loads(_STORE_PATH.read_text(encoding="utf-8"))


def _save(data: dict[str, list[dict[str, Any]]]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def save_template(name: str, steps: list[dict[str, Any]]) -> None:
    name = name.strip()
    if not name:
        raise ValueError("Template name is required.")
    data = _load()
    data[name] = [{"type": s["type"], "params": s["params"]} for s in steps]
    _save(data)


def list_templates() -> list[dict[str, Any]]:
    data = _load()
    return [{"name": name, "step_count": len(steps)} for name, steps in sorted(data.items())]


def get_template(name: str) -> list[dict[str, Any]]:
    data = _load()
    if name not in data:
        raise ValueError(f"Template '{name}' not found.")
    return data[name]


def delete_template(name: str) -> None:
    data = _load()
    if name in data:
        del data[name]
        _save(data)
