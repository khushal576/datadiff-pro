"""
df-studio/steps.py

Every pipeline step type in one place: a handler that takes the current
DataFrame + user params and returns (new_df, generated_pandas_code_line).
The generated code is what the UI shows in the pipeline panel — it's the
whole point of this tool (see real pandas next to every click).

Adding a new step type: write a handler with this signature, register it
in STEP_HANDLERS, and add its UI form in ui/index.html.
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd

StepHandler = Callable[[pd.DataFrame, dict[str, Any]], tuple[pd.DataFrame, str]]


def _require_columns(df: pd.DataFrame, columns: list[str]) -> None:
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(f"Column(s) not found: {', '.join(missing)}")


def rename_column(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    old = str(params.get("old", "")).strip()
    new = str(params.get("new", "")).strip()
    if not old or not new:
        raise ValueError("Both the current and new column name are required.")
    _require_columns(df, [old])
    if new in df.columns and new != old:
        raise ValueError(f"Column '{new}' already exists.")
    new_df = df.rename(columns={old: new})
    return new_df, f"df = df.rename(columns={{{old!r}: {new!r}}})"


def drop_columns(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    columns = params.get("columns") or []
    if not columns:
        raise ValueError("Pick at least one column to drop.")
    _require_columns(df, columns)
    new_df = df.drop(columns=columns)
    cols_repr = ", ".join(repr(c) for c in columns)
    return new_df, f"df = df.drop(columns=[{cols_repr}])"


def add_column(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    name = str(params.get("name", "")).strip()
    expr = str(params.get("expr", "")).strip()
    if not name or not expr:
        raise ValueError("Both a column name and an expression are required.")
    if name in df.columns:
        raise ValueError(f"Column '{name}' already exists — drop or rename it first.")
    try:
        new_df = df.eval(f"{name} = {expr}", engine="python")
    except Exception as exc:  # noqa: BLE001 - surface pandas/eval errors to the UI verbatim
        raise ValueError(f"Couldn't evaluate expression: {exc}") from exc
    return new_df, f"df = df.eval({f'{name} = {expr}'!r})"


def filter_rows(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    expr = str(params.get("expr", "")).strip()
    if not expr:
        raise ValueError("A filter expression is required.")
    try:
        new_df = df.query(expr, engine="python")
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Couldn't evaluate filter: {exc}") from exc
    return new_df, f"df = df.query({expr!r})"


def sort_rows(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    columns = params.get("columns") or []
    ascending = bool(params.get("ascending", True))
    if not columns:
        raise ValueError("Pick at least one column to sort by.")
    _require_columns(df, columns)
    new_df = df.sort_values(by=columns, ascending=ascending)
    cols_repr = ", ".join(repr(c) for c in columns)
    return new_df, f"df = df.sort_values(by=[{cols_repr}], ascending={ascending})"


def custom_code(df: pd.DataFrame, params: dict[str, Any]) -> tuple[pd.DataFrame, str]:
    code = str(params.get("code", "")).strip()
    if not code:
        raise ValueError("Code is required.")
    if "def transform" not in code:
        raise ValueError("Define a function named transform(df) that returns a DataFrame.")

    namespace: dict[str, Any] = {"pd": pd, "np": np}
    try:
        exec(code, namespace)  # noqa: S102 - trusted single-user local tool, by design (see CLAUDE.md)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Error in code: {exc}") from exc

    transform_fn = namespace.get("transform")
    if not callable(transform_fn):
        raise ValueError("Define a function named transform(df).")

    try:
        result = transform_fn(df.copy())
    except KeyError as exc:
        # pandas' own KeyError just dumps the missing labels (e.g.
        # "Index(['HR'], dtype='object')") with no hint of what that means —
        # almost always a column name typo'd or confused with a cell value.
        raise ValueError(
            f"Column not found: {exc}. Check that every column name in your "
            "code matches a real column — this often means a value (like a "
            "department name) was used where a column name was expected."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Error running transform(): {exc}") from exc
    if not isinstance(result, pd.DataFrame):
        raise ValueError("transform(df) must return a DataFrame.")

    generated = code.rstrip() + "\n\ndf = transform(df)"
    return result, generated


STEP_HANDLERS: dict[str, StepHandler] = {
    "rename_column": rename_column,
    "drop_columns": drop_columns,
    "add_column": add_column,
    "filter_rows": filter_rows,
    "sort_rows": sort_rows,
    "custom_code": custom_code,
}

STEP_LABELS: dict[str, str] = {
    "rename_column": "Rename column",
    "drop_columns": "Drop column(s)",
    "add_column": "Add column",
    "filter_rows": "Filter rows",
    "sort_rows": "Sort",
    "custom_code": "Custom Python",
}
