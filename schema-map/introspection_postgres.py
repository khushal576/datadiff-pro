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
# is_primary_key/is_unique added for the DDL export feature (schema-map/
# CLAUDE.md's "v2 design, Phase E") — without them, PRIMARY KEY/UNIQUE
# constraints on a live-fetched or paste-imported table would silently
# vanish from generated DDL (they were never fetched at all before this;
# see ensureColumnsLoadedFor()'s comment in ui/index.html for the earlier,
# cosmetic-only version of this gap). is_unique checks pg_index
# (indisunique), not pg_constraint — a real, common pattern is
# `CREATE UNIQUE INDEX` run directly rather than declared as a table
# constraint (found on this exact fixture: customers.email is enforced by
# a plain unique index, invisible in pg_constraint entirely). indpred/
# indexprs IS NULL excludes partial and expression unique indexes — those
# don't mean the column itself is unique across all rows (e.g. a partial
# index for a soft-delete pattern), so treating them as a plain column
# UNIQUE would be wrong. Only the SOLE key column of a single-column
# unique index is reported — a composite UNIQUE(a, b) is NOT
# representable by this per-column model (same restriction Editor's own
# single-checkbox-per-column UI already has), so composite unique
# constraints are correctly left out of DDL export rather than
# incorrectly split into two separate single-column UNIQUE constraints.
_COLUMNS_SQL = """
    SELECT a.attname AS column_name, format_type(a.atttypid, a.atttypmod) AS data_type,
      NOT a.attnotnull AS is_nullable, pg_get_expr(d.adbin, d.adrelid) AS default_value,
      a.attnum AS ordinal_position,
      EXISTS (
        SELECT 1 FROM pg_constraint pk
        WHERE pk.conrelid = c.oid AND pk.contype = 'p' AND a.attnum = ANY(pk.conkey)
      ) AS is_primary_key,
      EXISTS (
        SELECT 1 FROM pg_index ix
        WHERE ix.indrelid = c.oid AND ix.indisunique
          AND ix.indpred IS NULL AND ix.indexprs IS NULL
          AND array_length(ix.indkey::int[], 1) = 1 AND ix.indkey[0] = a.attnum
      ) AS is_unique
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
    WHERE c.relname = %s AND n.nspname = %s AND a.attnum > 0 AND NOT a.attisdropped
    ORDER BY a.attnum
"""


# Two separate, self-contained queries for the paste-and-load Project
# origin (schema-map/CLAUDE.md's "v2 design, Phase B") — for when the
# owner doesn't have direct access to run this tool against a database
# (private network, no credentials to share) but CAN run queries
# themselves in whatever client they do have (psql, pgAdmin, DBeaver...)
# and paste each JSON result back into the app.
#
# Originally this was ONE combined query (CTEs + json_build_object
# producing the full {tables, foreign_keys} object in one shot) — split
# into two after the owner asked for a simpler, staged flow: run one
# query, paste its result, run the other, paste that too. Two plain
# json_agg(row_to_json(...)) queries are less SQL surface for an
# unfamiliar client to choke on than one query combining two aggregates
# inside a json_build_object, and a wrong/truncated paste in one step
# gives a specific error about THAT step, not an ambiguous one about the
# whole thing.
#
# Each wraps _TABLES_SQL_ALL / _FOREIGN_KEYS_SQL_ALL directly (the exact
# same query strings the live-fetch path already uses — not copies) so
# the paste-import path and the live-fetch path can never silently
# diverge in shape or filtering. COALESCE(..., '[]') because
# json_agg() over zero rows returns SQL NULL, not an empty array, and a
# bare `null` is exactly the kind of thing that looks like a valid paste
# but silently produces an empty graph instead of a clear error.
TABLES_QUERY_SQL = f"SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM ({_TABLES_SQL_ALL}) t;"
FOREIGN_KEYS_QUERY_SQL = f"SELECT COALESCE(json_agg(row_to_json(fk)), '[]'::json) FROM ({_FOREIGN_KEYS_SQL_ALL}) fk;"

# Third paste-import query — ALL columns for ALL tables in one shot, not
# per-table like _COLUMNS_SQL (which is parameterized by one table,
# fetched lazily on click for a LIVE connection — see that query's own
# comment for why bulk-fetching columns is deliberately avoided at real
# scale there). A paste-imported or from-scratch project has no live
# connection to fetch a single table's columns from later on click, so
# this is the one case where bulk-fetching columns up front is the only
# option, not a scale mistake — the owner explicitly asked for this so
# the table detail panel's column list works for these projects too.
# Same _COLUMNS_SQL column list, extended with schema_name/table_name
# (needed here since it's not scoped to one table) and the same
# _SYS_SCHEMA_FILTER + relkind filter _TABLES_SQL_ALL uses, instead of
# the single-table WHERE clause. Pulled out as its own constant (not
# inlined into COLUMNS_QUERY_SQL's json_agg wrapper) so get_all_columns()
# below can run the identical SELECT directly via psycopg, for a LIVE
# connection, not just as copy-paste text for the paste-import origin.
_ALL_COLUMNS_SQL = f"""
    SELECT n.nspname AS schema_name, c.relname AS table_name,
      a.attname AS column_name, format_type(a.atttypid, a.atttypmod) AS data_type,
      NOT a.attnotnull AS is_nullable, pg_get_expr(d.adbin, d.adrelid) AS default_value,
      a.attnum AS ordinal_position,
      EXISTS (
        SELECT 1 FROM pg_constraint pk
        WHERE pk.conrelid = c.oid AND pk.contype = 'p' AND a.attnum = ANY(pk.conkey)
      ) AS is_primary_key,
      EXISTS (
        SELECT 1 FROM pg_index ix
        WHERE ix.indrelid = c.oid AND ix.indisunique
          AND ix.indpred IS NULL AND ix.indexprs IS NULL
          AND array_length(ix.indkey::int[], 1) = 1 AND ix.indkey[0] = a.attnum
      ) AS is_unique
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum
    WHERE a.attnum > 0 AND NOT a.attisdropped AND c.relkind IN ('r', 'p') AND {_SYS_SCHEMA_FILTER}
    ORDER BY n.nspname, c.relname, a.attnum
"""

COLUMNS_QUERY_SQL = f"""
SELECT COALESCE(json_agg(row_to_json(col)), '[]'::json) FROM (
{_ALL_COLUMNS_SQL}
) col;
""".strip()


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


def get_all_columns(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Bulk columns for every table in every non-system schema — the one
    deliberate exception to "never bulk-fetch columns for a live
    connection" (see get_table_columns()'s own docstring for why that's
    normally avoided at real scale). Exists specifically for "Save as
    Version": that action needs a COMPLETE, self-consistent snapshot,
    not whatever happens to already be cached in the frontend's
    lastGraphData from click history — a table nobody had clicked into
    Editor/Explore yet was silently saved with ZERO columns, which
    looked like a real bug in version comparison (a column that was
    never removed appeared to vanish, because it was never recorded to
    begin with) before the actual cause was traced back here. Called
    once, only when the frontend detects at least one table with no
    columns loaded yet — not on every save, and never during ordinary
    Explore/Editor browsing."""
    with conn.cursor() as cur:
        cur.execute(_ALL_COLUMNS_SQL)
        return _rows_as_dicts(cur)
