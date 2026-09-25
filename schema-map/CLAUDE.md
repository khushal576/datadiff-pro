# Schema Map — tool-local notes

Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture
and `../KNOWLEDGE_MAP.md` for the full symptom→file map across every tool.
This file is just the fast-orientation version scoped to this one folder.

## What this tool is

A **read-only**, progressive-disclosure explorer for large, poorly-
documented Postgres schemas — connect, see tables and foreign-key
relationships as an interactive graph, without ever rendering more than
what's currently expanded. Built for two concrete motivations: (1)
planning a monolith → microservice split needs to see which tables are
tightly interconnected vs. isolated, not infer it from scattered `\d`
output; (2) before migrating a table, seeing everything transitively
connected to it prevents a class of migration bug (moving a table
without its real dependencies).

**Editability (manual groups, manual non-FK links) is deliberately out
of scope for now** — the owner explicitly scoped the first build to
read-only exploration only; that's a separate future phase, not an
oversight. See the plan this tool was built from
(`/home/cygnet/.claude/plans/i-want-a-sql-glistening-dawn.md` at the time
of writing, though plan files don't persist long-term — the reasoning
below is the durable record) for the full back-and-forth that led here,
condensed:
- Started as "just visualize the FK graph." A naive force-directed
  layout of hundreds-to-1000 tables is unreadable regardless of layout
  algorithm — the real problem is progressive disclosure, not a better
  renderer.
- Considered Neo4j once editability came up (naming groups, adding
  manual links for relationships that exist in practice but were never
  enforced as real FKs) — a real graph database makes that natural.
  Then considered Kùzu (an embedded, no-server graph database, genuinely
  analogous to DuckDB) as a lighter alternative.
- **Settled on neither.** At the confirmed actual scale (hundreds to
  ~1000 tables, at most 2-hop traversal depth), a real graph database's
  architectural advantages (built for millions-scale graphs) never pay
  for themselves — its fixed per-query overhead (connection/session
  setup, query planning, an FFI boundary for Kùzu specifically) would
  very likely exceed the actual computation time at this scale.
  `networkx` (plain Python, in-process, rebuilt fresh from Postgres on
  each request, no persistence layer) is genuinely faster and lighter
  *at this specific scale* — not a compromise, the actually-correct
  choice given the numbers.

## Build status

Built so far (Steps 1–3 of the plan's sequence):
- **Step 1** — connection scaffolding, reusing SQL Studio's exact
  Connection-panel UX (collapsed by default, host/port/database/username
  in `localStorage`, password never persisted, collapses to a status
  line once connected) and `db_engine.py` idiom (own global `STATE`,
  `psycopg_pool`, credential-pre-validation before opening the pool,
  20-minute idle reaper).
- **Step 2** — `introspection_postgres.py` (direct ports of already-
  verified SQL Studio `SHOW_COMMANDS` queries — Show Schemas, Show
  Tables + Show Table Sizes joined, Show Foreign Keys — deliberately
  fetching NO column data), `GET /schemas` and `GET /graph?schema=X`
  endpoints.
- **Step 3** — Cytoscape.js (CDN, cdnjs, classic `<script>` tag — it's a
  UMD build, not an ES module, unlike SQL Studio's esm.sh CodeMirror
  imports) renders whatever `/graph` returns as a force-directed
  (`cose` layout) graph. This step proves the pipeline end-to-end; it
  deliberately does NOT yet solve "hundreds of tables at once looks like
  a hairball" — that's Step 4 (progressive disclosure via connected
  components) and Step 5 (interactive hub-collapse), not built yet.
- **Step 6, pulled forward** — click a node, see its real columns
  (`GET /table/{schema}/{table}`, fetched only for the clicked table,
  same lazy-loading principle as everything else here) in a right-side
  detail panel. Built ahead of Steps 4/5 because it's independently
  useful and doesn't depend on progressive disclosure landing first —
  the owner asked for it directly after seeing Step 3 render.
- **Polish pass** (owner feedback after seeing Step 3 render for real):
  zoom controls (+/−/fit-to-screen buttons and a live zoom-percentage
  readout — cytoscape already supports scroll-to-zoom/drag-to-pan by
  default, but neither is discoverable without a visible affordance),
  per-schema node coloring (a fixed 10-color categorical palette,
  deterministically assigned by sorted schema name — see
  `SCHEMA_COLOR_PALETTE`/`buildSchemaColorMap()` — with an auto-shown
  legend once 2+ schemas are in the current graph), and a node-size mode
  toggle ("by row count" — the original sqrt-scaled behavior — vs.
  "uniform," for when you want to see pure FK structure without volume
  competing for attention). The toggle re-renders from a cached
  `lastGraphData` instead of re-fetching — changing how something
  already-fetched is *displayed* shouldn't cost a network round-trip.
- **Second polish pass** (owner feedback after using the first one):
  label readability — a near-opaque white box behind each table name
  (`text-background-color`/`-opacity`/`-shape`/`-padding`) so an FK
  edge line crossing behind the text no longer merges with the letters;
  a hover tooltip (`showNodeTooltip()`/`#nodeTooltip`) showing table
  name, schema, row count, and size on mouseover, separate from the
  small persistent labels; and **labels held to a constant on-screen
  size regardless of zoom** (`keepLabelSizeConstant()`, `BASE_FONT_SIZE`)
  — cytoscape scales font size together with node geometry by default,
  which the owner correctly flagged as disorienting (text visibly
  growing every time you zoom in). See "Things that will bite you"
  below for the real bug found and fixed while building this (an
  overly defensive `Math.max()` floor that silently broke the
  constant-size guarantee at high zoom) and for why an *earlier*
  attempt at this same request (`min-zoomed-font-size`, shrink-to-hide
  on zoom-out) was removed rather than kept alongside the fix — the two
  approaches directly contradict each other.

- **Filter (a migration blast-radius view, built ahead of Steps 4/5)** —
  the owner asked, after using the graph for real: "which tables are
  directly connected to `orders`, or two degrees down, and via which
  columns." A new sidebar Filter card lets you pick a table + a depth (1
  or 2 hops) and get a **true hide, not a fade/highlight** — everything
  outside the chosen neighborhood is `.hide()`d from the Cytoscape
  instance, not just dimmed, per the owner's explicit answer ("when
  filter show only nodes which comes in filter other does not show").
  Traversal is **undirected** (the owner's confirmed answer: "both
  directions" — what a table references AND what references it both
  count), a plain BFS over an adjacency map built from `foreign_keys`
  (`computeNeighborhood()`/`buildAdjacency()` in `ui/index.html`), so a
  node's reported hop distance is its shortest path from the selected
  table, not double-counted if reachable multiple ways. The sidebar also
  lists every connection found, grouped by hop distance, each row
  showing the actual FK column pair (`orders.customer_id →
  customers.id`, not just the two table names) and clickable to open
  that table's column detail panel. This directly depended on the
  cross-schema-FK fix below landing first — see "Things that will bite
  you."
- **Third polish pass** (owner feedback after using the Filter card for
  real): a **Relationships section in the table detail panel** —
  clicking any node now shows, below its columns, every FK it takes
  part in as a clickable `column → other_schema.other_table.column`
  link, grouped into "References" (this table's own FK columns pointing
  out) and "Referenced by" (other tables' FK columns pointing in) —
  `buildRelationshipsHtml()` in `ui/index.html`, built from the already-
  cached `lastGraphData.foreign_keys` (no new endpoint, no new network
  call). The owner's own words: clicking a table showed its columns but
  gave no way to tell *which* column was a foreign key or what it
  pointed at — this closes that gap directly in the panel you're
  already looking at, instead of only in the separate Filter card's
  connection list. Also: node labels moved from below the node to above
  it (`text-valign: "top"`, `text-margin-y: -6`, was `"bottom"`/`4`),
  and the Filter feature now **force-shows labels on whatever small
  subset it filters down to**, regardless of what the full unfiltered
  graph's `LABEL_VISIBLE_THRESHOLD` decided — a filtered neighborhood is
  never more than a handful of tables (the owner's own observation:
  "we never have more than 10 dependency in one or 2 hop"), so there's
  no clutter reason to keep labels off just because the *original*
  full-graph view had too many tables to show them all. See `applyFilter()`/
  `clearFilter()` and the new `currentShowLabels` module-level variable.
- **Fourth pass — four "quick win" improvements, scoped by the owner
  from a list of my own suggestions before any code was written**:
  1. **Table search** (`#canvasSearch`, top-left over the graph canvas,
     map-search-bar styling) — a native `<input list>`/`<datalist>`
     type-ahead over every table in the current graph, deliberately not
     a custom dropdown widget (free keyboard nav/filtering from the
     browser, zero new dependency). Picking a result or pressing Enter
     calls `jumpToTable()`: centers/fits the graph on that node
     (`cy.animate({fit:...})`), opens its detail panel, and — the
     owner's own ask — pre-fills the Filter card's table picker too, so
     finding a table and tracing its dependencies chain together. If
     the target table is currently hidden by an active filter,
     `jumpToTable()` clears the filter first (fitting to a hidden
     element does nothing visible, so this isn't optional).
  2. **Insights card** (`#detInsights`, sidebar, between Schema and
     Filter) — "Most connected tables" (top `TOP_HUBS_COUNT` = 8 by
     degree) and "Orphan tables" (zero FK connections at all), both
     from `computeTableDegrees()`. "Degree" is the count of *distinct*
     neighboring tables, not raw FK-row count — a table with two FK
     columns pointing at the same other table (`orders` →
     `user_addresses` via both `billing_` and `shipping_address_id`) is
     one coupling relationship for this purpose, not two. Verified live:
     `public.orders`/`public.users` top the hub list at degree 6 each,
     and the orphan list correctly finds exactly the two zero-FK
     fixtures the original plan called out (`employees`,
     `analytics.daily_stats`). Every row is clickable → `jumpToTable()`.
  3. **FK columns marked directly in the columns table** — a small 🔗
     badge next to any column that's part of a FK, either this table's
     own outgoing reference or the target of another table's incoming
     one (tooltip distinguishes which). Reading the Relationships
     section below used to be the only way to know a column was a FK
     at all; now it's visible without scrolling.
  4. **Refactor enabling #3**: `buildRelationshipsHtml(nodeData)` was
     split into `getTableForeignKeys(nodeData)` (returns
     `{outgoing, incoming}`) + `buildRelationshipsHtml(outgoing,
     incoming)`, so the Relationships section and the column badges
     share one filter over `lastGraphData.foreign_keys` instead of two
     that could silently drift apart. If you ever add a third
     FK-derived view, call `getTableForeignKeys()` again rather than
     re-filtering `lastGraphData.foreign_keys` by hand.

**Not yet built**: Step 4 (schema → connected-components → group
expansion, so nothing renders before you explicitly ask for it), Step 5
(hub-collapse toggle). None of the "explicitly deferred" items from the
plan either (manual groups/links, other DB engines, community detection
beyond plain connected components).

## How it's built

- `server.py` — thin FastAPI app: `GET /` (UI), `POST /connect`,
  `POST /disconnect`, `GET /status`, `GET /schemas`, `GET /graph`. No
  `/query` endpoint and no `query_guard.py` equivalent at all — unlike
  SQL Studio, this tool never accepts free-form user SQL, only ever runs
  its own fixed introspection queries, so none of that machinery
  (statement splitting, destructive-keyword detection, the confirm-
  dialog flow) is needed or present here.
- `db_engine.py` — copied from `sql-studio/db_engine.py`'s shape (own
  module-level `STATE`, not shared with SQL Studio's — Schema Map and
  SQL Studio might reasonably be pointed at two different databases at
  once), but smaller pool (`max_size=2` vs. SQL Studio's 3 — this tool
  only ever runs a handful of introspection queries per fetch, never
  sustained query traffic) and one new piece SQL Studio's doesn't have:
  `run(fn, *args)`, a generic "execute this plain function against a
  pooled connection" helper — the one integration point
  `introspection_postgres.py` uses. Same credential-pre-validation fix
  as SQL Studio's (`psycopg.connect()` directly before opening the pool
  — `pool.open()` alone with `min_size=0` doesn't eagerly create a real
  connection, so a bad password wouldn't be caught until the first
  query; a real bug already found and fixed once there, ported the fix
  here proactively rather than reintroducing it).
- `introspection_postgres.py` — `get_schemas()`, `get_tables(schema)`,
  `get_foreign_keys(schema)`, `get_graph(schema)` (the one function
  `server.py`'s `/graph` route calls, combining the other two). Every
  query is a direct port of an already-verified `SHOW_COMMANDS` query
  from `sql-studio/ui/index.html`, not written from scratch — same
  `SYS_SCHEMA_FILTER`-equivalent non-system-schema exclusion. Returns
  plain dicts (via `psycopg`'s cursor `.description` + `zip`), not SQL
  text — unlike SQL Studio's `SHOW_COMMANDS`, which return SQL strings
  to be run through Run's own pipeline, this tool executes these
  queries directly since it never accepts free-form user SQL.
- `ui/index.html` — single file, no build step, same convention as every
  other tool. Layout is a left `.sidebar` (Connection + Schema picker,
  both `<details>` cards) driving a right `.main` graph canvas — the
  inverse of SQL Studio's layout (editor-dominant, info sidebar) since
  this tool is graph-canvas-dominant. `renderGraph()` destroys and
  recreates the Cytoscape instance on every load (same "rebuild from
  scratch, don't try to diff" pattern df-studio's Tabulator usage
  already established) — node IDs are `schema.table` (not just
  `table`), so same-named tables in different schemas (already a real,
  verified case for SQL Studio's schema-fetch feature — `public.orders`
  vs. `analytics.orders`) get distinct graph nodes instead of colliding.

## Things that will bite you if you don't know them

- **Never fetches column data for tables that haven't been individually
  clicked — by design, not an oversight, not yet built either.** A
  schema with hundreds of tables shouldn't pay (in fetch size, transfer
  time, or render cost) for every table's full column list just to draw
  the graph. `introspection_postgres.py`'s queries deliberately stop at
  `{schema_name, table_name, row_estimate, total_size}` — no `columns`
  key at all yet. When Step 6 lands, column fetching will be a *separate*
  per-table endpoint, triggered only on click — don't "simplify" this by
  folding columns back into `get_tables()`'s bulk query.
- **Node sizing (`sizeFor()` in `ui/index.html`) uses `sqrt(row_estimate
  / maxRows)`, not a linear scale**, clamped to a 28–88px range. Linear
  scaling would make one huge table's node enormous and everything else
  an invisible speck; sqrt compresses that range while still keeping
  size meaningfully different. `row_estimate` itself is `pg_class.
  reltuples` (the same fast-estimate metric SQL Studio's "Show Table
  Sizes" uses), not `COUNT(*)` — a table that's never been `ANALYZE`d
  reports `-1`, clamped to 0 via `Math.max(t.row_estimate, 0)` before
  sizing, not treated as an error.
- **`cytoscape.js` is loaded as a classic `<script>` tag, not inside the
  `type="module"` script.** It's a UMD build exposing a global
  `cytoscape` function, not an ES module — attempting to `import` it the
  way SQL Studio imports CodeMirror from esm.sh would fail. The classic
  script tag runs during HTML parsing (synchronous, in document order);
  the module script is deferred until after parsing finishes — that
  ordering is what guarantees `cytoscape` already exists as a global by
  the time the module script's code that references it actually runs,
  not a race condition to worry about.
- **The graph endpoint's `schema` query param uses the empty string to
  mean "all schemas," not the string `"all"` or an omitted param in the
  literal sense** — `ui/index.html`'s schema `<select>` has an `"All
  schemas"` option with `value=""`, and `loadGraph()` checks
  `if (schema)` before appending `?schema=...` to the request URL, so an
  empty selection genuinely omits the query param rather than sending
  `schema=`. `server.py`'s `/graph` route's `schema: Optional[str] =
  None` then correctly falls through to
  `introspection_postgres.get_graph(conn, None)`, which its own
  `get_tables()`/`get_foreign_keys()` treat as "no schema filter." If
  you ever change the `<select>`'s "all" sentinel value, keep this
  empty-string-means-omit-the-param behavior in sync on both ends.
- Mounted at `/tools/schema-map/` by `main.py` in the repo root, same as
  every other tool — this folder never needs to know that.
- **`cy.resize()` must be called whenever `.detail-panel`'s visibility
  toggles** (`openTableDetail()`/`closeDetailPanel()` in `ui/index.html`
  both do this) — the graph canvas is a flex sibling of the detail
  panel, so showing/hiding the panel changes the canvas's actual
  available width, but Cytoscape doesn't observe layout/CSS changes on
  its own. Skipping this call leaves the canvas rendering at its old
  size, visibly cut off or with dead space, until the next explicit
  interaction happens to trigger a redraw.
- **Schema node colors are deterministic, not per-render-random** —
  `buildSchemaColorMap()` sorts schema names alphabetically and walks
  `SCHEMA_COLOR_PALETTE` in that fixed order, so the same schema keeps
  the same color across reloads and across toggling the size-mode
  radio (which re-renders from `lastGraphData` without re-fetching).
  Don't swap this for `Math.random()`-based color picking — two schemas
  landing on visually-similar random hues would defeat the point of
  coloring by schema in the first place. The palette has 10 entries and
  cycles (`% length`) past that — a schema-heavy database (this tool's
  whole reason to exist) hitting 11+ schemas gets color *reuse*, not an
  error; the legend (`renderSchemaLegend()`) only shows once 2+ schemas
  are present in the current graph, not for a single-schema view where
  a legend would just restate the obvious.
- **`keepLabelSizeConstant()` must never clamp its result with a fixed
  minimum floor — a real bug, caught by computing the actual on-screen
  result across zoom levels, not assumed correct.** An earlier version
  did `Math.max(2, BASE_FONT_SIZE / cy.zoom())` "defensively," which
  silently breaks the whole point of the function at high zoom: past
  the zoom level where `BASE_FONT_SIZE / cy.zoom()` would naturally dip
  below 2, the floor takes over and the model font-size stops shrinking
  — but cytoscape's zoom multiplier keeps growing, so the *rendered*
  size grows past `BASE_FONT_SIZE` instead of staying constant, exactly
  the "text zooms in with the graph" behavior this function exists to
  prevent. Fixed by removing the floor entirely and instead bounding
  `cy`'s own `minZoom`/`maxZoom` (0.05–8) at graph creation, so the
  division never needs a floor in the first place — cytoscape's default
  zoom range is effectively unbounded (1e-50 to 1e50), which is what
  made the floor feel necessary originally. If you ever change
  `BASE_FONT_SIZE` or the zoom bounds, recompute this by hand across a
  few zoom values (`BASE_FONT_SIZE / zoom`, then `× zoom` to confirm it
  round-trips to `BASE_FONT_SIZE`) rather than trusting it by inspection
  — this exact bug looked correct at zoom=1 and only showed up at the
  range's edges.
- **A foreign key can reference a table in a DIFFERENT schema than the
  one holding it — `introspection_postgres.py`'s FK queries must select
  the target's real schema (`fn.nspname AS to_schema`, via a
  `pg_namespace` join on `c.confrelid`), never assume `to_schema ==
  from_schema`.** This was a real latent bug, not a hypothetical: the
  original queries only ever joined `pg_namespace` for the *source*
  table, so every FK row's target was silently assumed same-schema —
  harmless purely by accident while every test fixture's FKs happened
  to be same-schema, until it wasn't. Found (by re-reading this code
  while building the Filter feature, not reported by the owner) and
  fixed, then verified against a genuine cross-schema FK added to the
  dev database (`analytics.orders.customer_id →
  public.customers.id`) — confirmed the API now reports `to_schema:
  "public"`, not the old buggy `"analytics"`. This matters *especially*
  now: `ui/index.html` builds every graph node id as `schema.table` (see
  "same-named tables in different schemas... get distinct graph nodes"
  above) and the Filter feature's BFS (`computeNeighborhood()`) walks
  those exact ids — a wrong `to_schema` wouldn't just mislabel one
  tooltip, it would point the traversal at a same-named table in the
  wrong schema (or a nonexistent node) and silently corrupt the
  blast-radius result. If you ever add a write path or another engine's
  introspection module, re-verify this same schema-qualification
  requirement holds there too — don't assume it's Postgres-specific
  paranoia.
- **Second, related bug in the SAME area, found right after the first:
  when one specific schema is selected (not "All schemas"),
  `_FOREIGN_KEYS_SQL_ONE_SCHEMA` must match the selected schema on
  EITHER side (`n.nspname = %s OR fn.nspname = %s`), not just the FROM
  side.** The original version only kept rows where the selected
  schema was the *source* — a table OUTSIDE the selected schema that
  references INTO it (`analytics.orders → public.customers`, while
  viewing just `public`) was silently dropped from the result entirely,
  so the Filter feature's traversal never even saw that edge to walk in
  the first place, regardless of how correct the BFS itself was. Caught
  by the owner testing the Filter feature and noticing a table's
  incoming dependency ("b to a") didn't show up, only its outgoing ones
  ("a to b"). Fixed by widening the `WHERE` to an `OR` and passing
  `schema` twice to `cur.execute()`; re-verified live — selecting just
  `public` now correctly includes the `analytics.orders →
  public.customers` edge (29 FKs total, same as "all schemas" returns,
  where before the one-schema view silently had only 28). If you ever
  touch `_TABLES_SQL_ONE_SCHEMA` or add a third query with a
  schema-scoping `WHERE`, check whether it has the same one-sided-filter
  shape before assuming it's fine — this exact mistake is easy to
  reintroduce because it reads as "obviously correct" at a glance (of
  course you filter by the schema you're looking at) while actually
  only covering half the real relationships that schema is part of.
- **`min-zoomed-font-size` and constant-size labels are mutually
  exclusive — don't add the first back as a "declutter" fix without
  removing the second.** An earlier version used
  `"min-zoomed-font-size": 6` to hide labels once they'd render too
  small to read when zoomed out, which is a real, valid Cytoscape.js
  feature — but it only works by *letting* font size shrink with zoom,
  which is exactly what `keepLabelSizeConstant()` was built to prevent.
  Decluttering at real scale is `LABEL_VISIBLE_THRESHOLD` instead (a
  table-count cutoff, currently 60: past it, no persistent labels are
  drawn at all — `label: showLabels ? "data(label)" : ""` in the node
  style — and the hover tooltip becomes the only way to identify a
  node). That threshold is a stopgap for the current "the whole loaded
  scope renders at once" behavior, not a substitute for Step 4's
  progressive disclosure — the honest fix for "500 tables looks messy"
  is not rendering 500 tables in one view in the first place, not a
  smarter label-hiding rule.
