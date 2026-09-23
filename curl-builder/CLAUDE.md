# cURL Builder — tool-local notes

Part of the Toolbox monorepo — see `../CLAUDE.md` for repo-wide architecture
and `../KNOWLEDGE_MAP.md` for the full symptom→file map across every tool.
This file is just the fast-orientation version scoped to this one folder.

## What this tool is

A form-based curl command generator. Pick method/URL/query params/auth/
headers/body/cookies/flags, and it builds a copy-pasteable `curl` command —
for bash/zsh, cmd.exe, or PowerShell, with correct quoting for each. It
never sends the request itself; it only ever produces a string.

## How it's built

- `server.py` — does exactly one thing: serves `ui/index.html`. No other
  routes, no request handling of any kind.
- `ui/index.html` — everything else. Single file, no build step, one
  `<script>` block, no external dependencies.
- **No backend processing, by design** — same reasoning as `encode-decode/`.
  Nothing the user types (tokens, passwords, API keys, bodies) ever leaves
  the browser. If you're tempted to add a "send this request for me"
  endpoint, don't — that would turn this into an open SSRF proxy (any
  visitor could make the server issue arbitrary outbound requests). This
  tradeoff needs the owner's sign-off to reverse, not a silent addition.

## Where each feature lives (inside `ui/index.html`'s script)

- `makeRowList(...)` — the one generic component behind every dynamic
  key/value list: Query Parameters, Headers, Cookies, the urlencoded body
  fields, and the multipart body fields (which also carry an `isFile` +
  optional MIME override per row).
- `quote(str, shell)` / `contJoiner(shell)` — all shell-specific escaping.
  bash/zsh: single-quote, `'` → `'\''`. cmd.exe: double-quote, `"` → `\"`.
  PowerShell: single-quote, `'` → `''` (deliberately avoids double quotes
  there so `$` in a token — e.g. a password — never gets interpolated).
- `generate()` — the one function that reads the whole form and rebuilds
  the command from scratch on every input event. Not debounced; string
  building is cheap enough that this doesn't need to be.
- `autoHeaderKeys` (inside `generate()`) — tracks which header names are
  already implied by Auth/Body settings (e.g. `Authorization` from Bearer,
  `Content-Type` from a raw/GraphQL body) so a manually-added header with
  the same name is skipped instead of emitted twice, with a warning shown
  for how many were skipped.

## Things that will bite you if you don't know them

- **Multipart bodies must never get a manual `Content-Type` header.** curl
  sets its own with the multipart boundary; a user-supplied one breaks the
  request. `generate()` already adds `content-type` to `autoHeaderKeys`
  when `bodyType === "multipart"` and shows a warning if one was skipped —
  keep that guard if you touch the body-type logic.
- **Form URL-Encoded body does *not* get an explicit `Content-Type`
  header.** curl adds `application/x-www-form-urlencoded` on its own for
  `--data-urlencode`, so emitting it explicitly would just be redundant.
  Raw and GraphQL bodies are the opposite case — curl's default there would
  be wrong (it'd still say urlencoded), so those *do* get an explicit
  header.
- **File fields are just typed paths, not uploads.** The multipart "File"
  toggle and the Binary body's file path are plain text inputs — this page
  never reads real files from the browser. The path the user types must
  exist on whatever machine actually runs the generated command, which is
  not necessarily this machine. This is called out in the UI hint text;
  don't remove it if you touch that section.
- **Only bash/zsh, cmd.exe, and PowerShell are supported targets.** If a
  fourth is ever added, it needs its own entries in both `quote()` and
  `contJoiner()` — the two are a matched pair, tested together per shell.
- Mounted at `/tools/curl-builder/` by `main.py` in the repo root — this
  folder never needs to know that; it's a fully self-contained ASGI app
  either way.
