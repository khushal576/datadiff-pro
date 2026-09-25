"""
schema-map/introspection_postgres.py

Postgres-specific catalog queries for Schema Map's graph view — direct
ports of already-verified queries from sql-studio/ui/index.html's
SHOW_COMMANDS (Show Schemas, Show Tables, Show Table Sizes, Show Foreign
Keys), not written from scratch. Deliberately returns NO column data —
that's fetched separately, per table, only when a table is actually
clicked (a later build step, not here — see the plan this tool was
built from for why: a schema with hundreds of tables shouldn't pay for
every table's full column list just to render the graph).

A second database engine later means a new introspection_<engine>.py
module returning these same shapes ({schema_name, table_count} /
{schema_name, table_name, row_estimate, total_size} /
{from_schema, from_table, from_column, to_table, to_column}) — nothing
above this module (the graph endpoint, later the networkx computation,
the frontend) needs to know or care which engine produced the data.

Every function takes an already-checked-out psycopg connection first
(see db_engine.run()) and returns plain dicts, not SQL text — unlike
SQL Studio's SHOW_COMMANDS, which return SQL strings to be *run through
Run's own pipeline*, this tool runs these queries directly since it
never accepts free-form user SQL in the first place.
"""

from __future__ import annotations

from typing import Any, Optional

import psycopg

# Same filter as sql-studio/ui/index.html's SYS_SCHEMA_FILTER — "widely
# used, easy to see" means user objects, not Postgres's own internals.
_SYS_SCHEMA_FILTER = (
    "n.nspname NOT IN ('pg_catalog', 'information_schema') "
    "AND n.nspname NOT LIKE 'pg\\_toast%' AND n.nspname NOT LIKE 'pg\\_temp%'"
)

_SCHEMAS_SQL = f"""
    SELECT n.nspname AS schema_name,
      (SELECT count(*) FROM pg_class c WHERE c.relnamespace = n.oid AND c.relkind IN ('r', 'p')) AS table_count
    FROM pg_namespace n
    WHERE {_SYS_SCHEMA_FILTER}
    ORDER BY n.nspname
"""

_TABLES_SQL_ALL = f"""
    SELECT n.nspname AS schema_name, c.relname AS table_name,
      c.reltuples::bigint AS row_estimate, pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind IN ('r', 'p') AND {_SYS_SCHEMA_FILTER}
    ORDER BY n.nspname, c.relname
"""

_TABLES_SQL_ONE_SCHEMA = f"""
    SELECT n.nspname AS schema_name, c.relname AS table_name,
      c.reltuples::bigint AS row_estimate, pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind IN ('r', 'p') AND n.nspname = %s
    ORDER BY c.relname
"""

# Direct port of SQL Studio's "Show Foreign Keys", EXTENDED to also
# capture the target table's real schema (fn.nspname AS to_schema) —
# SQL Studio's own version never needed this (it only ever prints a flat
# table for a human to read), but this tool builds graph NODE IDS from
# this data (schema.table, see ui/index.html), and Postgres allows an FK
# to reference a table in a DIFFERENT schema than the referencing table.
# The original version here silently assumed to_schema == from_schema —
# harmless by accident while every test fixture's FKs happened to be
# same-schema, but a real latent bug: a genuine cross-schema FK would
# have built a target node id pointing at a same-named table in the
# WRONG schema (or a nonexistent one). Fixed and re-verified against a
# real cross-schema FK before the multi-hop traversal feature (which
# depends on this being correct) was built on top of it.
_FOREIGN_KEYS_SQL_ALL = f"""
    SELECT n.nspname AS from_schema, t.relname AS from_table, a.attname AS from_column,
      fn.nspname AS to_schema, ft.relname AS to_table, fa.attname AS to_column
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    JOIN pg_class ft ON ft.oid = c.confrelid
    JOIN pg_namespace fn ON fn.oid = ft.relnamespace
    JOIN unnest(c.conkey) WITH ORDINALITY AS ck(attnum, ord) ON true
    JOIN unnest(c.confkey) WITH ORDINALITY AS fck(attnum, ord) ON fck.ord = ck.ord
    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ck.attnum
    JOIN pg_attribute fa ON fa.attrelid = ft.oid AND fa.attnum = fck.attnum
    WHERE c.contype = 'f' AND {_SYS_SCHEMA_FILTER}
    ORDER BY t.relname
"""

# One-schema variant matches the selected schema on EITHER side
# (n.nspname = %s OR fn.nspname = %s) — a table in the selected schema
# that references OUT to a different schema, AND a table in a different
# schema that references IN to the selected schema, both need to show up
# (to_schema/from_schema on the returned row tell the frontend which
# schema each end is really in, even when one end is outside the current
# filter). An earlier version only matched the FROM side, which silently
# dropped every incoming cross-schema FK when one schema was selected —
# a real bug: viewing just `public` while `analytics.orders` references
# `public.customers` meant that edge, and the fact `customers` has an
# incoming dependency at all, never appeared. Found from the owner
# reporting the Filter feature only showed one direction of a
# relationship, not the other way round.
_FOREIGN_KEYS_SQL_ONE_SCHEMA = """
    SELECT n.nspname AS from_schema, t.relname AS from_table, a.attname AS from_column,
      fn.nspname AS to_schema, ft.relname AS to_table, fa.attname AS to_column
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    JOIN pg_class ft ON ft.oid = c.confrelid
    JOIN pg_namespace fn ON fn.oid = ft.relnamespace
    JOIN unnest(c.conkey) WITH ORDINALITY AS ck(attnum, ord) ON true
    JOIN unnest(c.confkey) WITH ORDINALITY AS fck(attnum, ord) ON fck.ord = ck.ord
    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ck.attnum
    JOIN pg_attribute fa ON fa.attrelid = ft.oid AND fa.attnum = fck.attnum
    WHERE c.contype = 'f' AND (n.nspname = %s OR fn.nspname = %s)
    ORDER BY t.relname
"""


# Direct port of SQL Studio's "Show Table Columns" (sql-studio/ui/index.html) —
# fetched ONLY when one specific table is clicked, never bundled into the
# bulk get_tables() query. See schema-map/CLAUDE.md's "never fetches
# column data..." note for why that split matters at real scale.
_COLUMNS_SQL = """
    SELECT a.attname AS column_name, format_type(a.atttypid, a.atttypmod) AS data_type,
      NOT a.attnotnull AS is_nullable, pg_get_expr(d.adbin, d.adrelid) AS default_value,
      a.attnum AS ordinal_position
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
    WHERE c.relname = %s AND n.nspname = %s AND a.attnum > 0 AND NOT a.attisdropped
    ORDER BY a.attnum
"""


def _rows_as_dicts(cur: psycopg.Cursor) -> list[dict[str, Any]]:
    columns = [d.name for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_schemas(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(_SCHEMAS_SQL)
        return _rows_as_dicts(cur)


def get_tables(conn: psycopg.Connection, schema: Optional[str]) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        if schema is None:
            cur.execute(_TABLES_SQL_ALL)
        else:
            cur.execute(_TABLES_SQL_ONE_SCHEMA, (schema,))
        return _rows_as_dicts(cur)


def get_foreign_keys(conn: psycopg.Connection, schema: Optional[str]) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        if schema is None:
            cur.execute(_FOREIGN_KEYS_SQL_ALL)
        else:
            cur.execute(_FOREIGN_KEYS_SQL_ONE_SCHEMA, (schema, schema))
        return _rows_as_dicts(cur)


def get_graph(conn: psycopg.Connection, schema: Optional[str]) -> dict[str, Any]:
    """The one function schema-map/server.py's /graph endpoint calls —
    tables and foreign_keys only, deliberately no column data (see this
    module's own docstring)."""
    return {
        "tables": get_tables(conn, schema),
        "foreign_keys": get_foreign_keys(conn, schema),
    }


def get_table_columns(conn: psycopg.Connection, schema: str, table: str) -> list[dict[str, Any]]:
    """Fetched only when a single table is clicked — never bundled into
    get_tables()'s bulk response."""
    with conn.cursor() as cur:
        cur.execute(_COLUMNS_SQL, (table, schema))
        return _rows_as_dicts(cur)
