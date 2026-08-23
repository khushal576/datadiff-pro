# Knowledge Map

Purpose: a lookup table from "I need to change X" straight to the file that
owns it — so opening this repo with 10+ tools doesn't mean re-reading
everything to find where something lives. `CLAUDE.md` has the *rules*; this
file has the *floor plan*.

**Rule for every future tool**: when a tool is added, it gets its own
section below in the same shape as DataDiff Pro's. Keep this file in sync
with reality — a stale map is worse than no map, because it actively
misleads. If a file's job changes, update its row here in the same commit.

---

## Repo-wide (the Toolbox shell — not any one tool's code)

| If you need to change...                                    | Go to |
|---------------------------------------------------------------|-------|
| The home page layout / card styling                           | `main.py` (`_HOME_TEMPLATE`, `_render_card`) |
| Which tools show up as cards, their title/description/icon    | `registry.yaml` |
| Actually wiring a tool's app into the site (routing)           | `main.py` (`app.mount(...)` calls, bottom of file) |
| The Docker image / what gets copied into the container         | `Dockerfile` |
| Ports, restart policy, env vars for the whole site              | `docker-compose.yml` |
| Architecture decisions, conventions, "why is it built this way" | `CLAUDE.md` |
| GitHub auth setup for this device                               | `GITHUB_AUTH.md` |

---

## Tool: Subnet Calculator — mounted at `/tools/subnet-calc/`

Entirely client-side, same pattern as Encode/Decode — `subnet-calc/server.py`
only serves the static page. No secrets involved here (it's just math), but
client-side keeps it instant and consistent with the rest of the Toolbox.

| If you need to change...                                    | Go to |
|-----------------------------------------------------------------|-------|
| Any core subnetting math (mask↔CIDR, network/broadcast, host range, same-subnet check) | `index.html` — "CALCULATION ENGINE" block at the top of the `<script>`, pure functions, no DOM |
| The bit-visualization grid (network vs host bit coloring)       | `index.html` — `bitGridHtml()` + `.bitgrid`/`.bit` CSS |
| The "how this was calculated" worked-binary explanation          | `index.html` — `.explain` block inside `runCalculator()` / `runCompare()` |
| The Calculator tab's inputs/results wiring                       | `index.html` — "Calculator tab" section of "UI WIRING" |
| The Compare-Two-IPs tab                                          | `index.html` — "Compare tab" section of "UI WIRING" |
| Public/private/reserved IP classification (the colored banner)   | `index.html` — `classifyIp()` (engine) + `renderIpTypeBanner()` (UI) |
| The click-to-explain "?" popovers on each result tile             | `index.html` — `TERM_INFO` dict + `showInfoPopover()`/`hideInfoPopover()` |
| Whether the backend does anything beyond serving the page        | `subnet-calc/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **Engine functions are deliberately pure and DOM-free**, sitting above the
  `UI WIRING` comment block in the script. This was built "backend logic
  first" on purpose — verify any change to the engine with plain function
  calls (see the `node`-run test harness used during development) before
  touching how it's wired to the page.
- **Special-cased prefixes**: `/32` (single host, no network/broadcast
  concept) and `/31` (RFC 3021 point-to-point, both addresses usable) are
  handled explicitly in `hostInfo()` — don't let a generic "count − 2"
  formula regress onto these two sizes.
- **`maskOctetsToCidr()` validates mask shape** (contiguous 1s then 0s) and
  returns `null` for anything else (e.g. `255.255.0.1`) — the UI relies on
  that `null` to avoid reacting to a mask the user hasn't finished typing.
- All bitwise ops use `>>> 0` to force unsigned 32-bit values — JS bitwise
  operators are signed 32-bit, and dropping this would silently break IPs
  in the upper half of the address space (anything ≥ `128.0.0.0`).

---

## Tool: Encode/Decode — mounted at `/tools/encode-decode/`

Entirely client-side — the Python backend (`encode-decode/server.py`) only
serves the static page; it has no other routes and never sees any input.

| If you need to change...                                    | Go to |
|-----------------------------------------------------------------|-------|
| Anything at all about behavior (every operation runs client-side) | `encode-decode/ui/index.html` (`<script>` block) |
| Base64 / Base64URL / Hex / URL / HTML entity logic              | `index.html` — "Text Encoding tab" section of the script |
| Gzip compress/decompress                                        | `index.html` — "Gzip tab" section (`CompressionStream`/`DecompressionStream`) |
| AES-GCM passphrase encryption                                   | `index.html` — "AES-GCM tab" section (`deriveAesKey`, PBKDF2 100k iterations) |
| RSA key generation / encrypt / decrypt                          | `index.html` — "RSA-OAEP tab" section |
| JWT signing/verification (HS256, RS256)                         | `index.html` — "JWT tab" section |
| SHA hashing                                                      | `index.html` — "Hash tab" section |
| Whether the backend does anything beyond serving the page        | `encode-decode/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **No backend processing, intentionally.** This was a deliberate security
  choice (see `CLAUDE.md` history / conversation) — real secrets
  (passphrases, private keys) must never be sent over the network, even
  locally. Don't add a `/encrypt`-style POST endpoint to `server.py` without
  re-raising that tradeoff with the owner first.
- **RSA-OAEP has a plaintext size limit** (~190 bytes at 2048-bit/SHA-256).
  It's meant for wrapping a small secret (like an AES key), not general
  data. The UI hints at this; don't remove the hint if touching that tab.
- **AES output packs `salt(16) + iv(12) + ciphertext` into one Base64
  blob** — the decrypt path assumes that exact layout. If the format ever
  changes, old ciphertexts become undecryptable; treat that as a breaking
  change worth flagging, not a silent tweak.

---

## Tool: DataDiff Pro — mounted at `/tools/datadiff-pro/`

### Symptom → file

| If you need to change...                                          | Go to |
|-----------------------------------------------------------------------|-------|
| How JSON / XML / CSV text gets parsed into Python objects              | `core/normalizer.py` |
| XML-specific quirks (attributes, `xsi:nil`, list detection)            | `core/normalizer.py` (`_parse_xml` and helpers) |
| CSV delimiter sniffing / cell type coercion                            | `core/normalizer.py` (`_parse_csv`, `_coerce_csv_value`) |
| Field renaming / restructuring rules ("Field Mapper" panel)            | `core/mapper.py` |
| Generic nested path lookup/insert/delete used by the mapper & validator | `core/path_resolver.py` |
| The actual left-vs-right comparison logic, MATCH/MISMATCH/EQUIVALENT   | `core/diff_engine.py` |
| How two lists of objects get paired up before comparing                | `core/list_resolver.py` |
| What counts as "equivalent but not equal" (null-likes, bool-likes, numeric tolerance, custom YAML groups) | `core/equivalence.py` |
| "Deep Mode" — parsing string-encoded JSON/XML found inside fields      | `core/deep_expander.py` |
| Post-mapping check for silently dropped fields                         | `core/validator.py` |
| The `/compare` API contract (request/response shape, error format)     | `api/app.py` |
| The FastAPI app object that `main.py` mounts                           | `api/app.py` (`app = FastAPI(...)`) |
| The frontend: layout, results table, filters, export (JSON/CSV/Excel)  | `ui/index.html` (single file, no build step) |
| Example equivalence-rule / list-key YAML config                        | `environments/example.yaml` |
| Batch/large-file comparison outside the browser                        | `notebook/compare_automation.ipynb` |

### Data flow (in call order)

```
ui/index.html --POST /compare--> api/app.py
  -> core/normalizer.py     (parse both sides)
  -> core/deep_expander.py  (only if deep_mode)
  -> core/mapper.py         (only if a field mapping was supplied)
       -> core/path_resolver.py   (path lookups used internally)
  -> core/validator.py      (only if a mapping was applied)
  -> core/equivalence.py + core/list_resolver.py   (built inside api/app.py,
       then handed to DiffEngine)
  -> core/diff_engine.py    (the actual comparison, returns DiffResult)
<- api/app.py returns JSON -> ui/index.html renders the table
```

### Known non-obvious behavior (read before touching these areas)

- **Frontend API calls must stay relative** (`fetch('compare', ...)`, never
  `fetch('/compare', ...)`). This is what lets `ui/index.html` work both
  mounted at `/tools/datadiff-pro/` and if ever run standalone. Any new
  fetch call added to the frontend must follow this.
- **`core/mapper.py`'s `_apply_single`** used to silently drop intermediate
  target-path segments when the target path was deeper than the source path
  (e.g. `a` → `x.y` produced `{"y": ...}` instead of `{"x": {"y": ...}}`).
  Fixed — see git log for `core/mapper.py`. If touching the leaf-rename
  branch again, re-run the depth-mismatch case as a regression check.
- **`core/list_resolver.py`'s `resolve()`** used to silently drop any
  non-dict item sharing a list with dict items (no EXTRA_LEFT/RIGHT record
  at all). Fixed — mixed lists now get the dict items paired normally and
  the leftover scalar items paired by index, merged into one result. If
  touching `resolve()`, re-check a mixed dict+scalar list still surfaces
  every item.
- **XML root tag is deliberately kept as a data key**, not unwrapped (see
  `_unwrap_xml_lists`'s docstring in `core/normalizer.py`) — this is so XML
  and its JSON equivalent produce the same top-level shape. Don't "fix" this
  by unwrapping the root; it would break XML-vs-JSON comparisons.
