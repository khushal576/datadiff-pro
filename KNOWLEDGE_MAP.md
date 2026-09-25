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
| Whether a tool defaults to shown or hidden (Tool vs Learn), the search box, the "Show learning tools" toggle | `registry.yaml` (`category:` field per tool) + `main.py`'s home page `<script>` block |
| Actually wiring a tool's app into the site (routing)           | `main.py` (`app.mount(...)` calls, bottom of file) |
| The Docker image / what gets copied into the container         | `Dockerfile` |
| Ports, restart policy, env vars for the whole site              | `docker-compose.yml` |
| Why the container runs `--workers 1` (not more)                 | `Dockerfile` (CMD comment) + `CLAUDE.md`'s "Standing rule: stateful tools and --workers" — check every stateful tool, not just df-studio, before ever raising this |
| The canonical color palette every new tool's `:root` should start from | `theme-tokens.css` — copy-source only, never served; see its own header for why |
| Architecture decisions, conventions, "why is it built this way" | `CLAUDE.md` |
| GitHub auth setup for this device                               | `GITHUB_AUTH.md` |

---

## Tool: Packet Journey — mounted at `/tools/packet-journey/`

Fully static, no calculation and no network calls — a narrow, concrete
"watch one real request travel through the layers" tool, deliberately NOT
a comprehensive reference (that was tried once as "Layer Explorer" and
removed). One fixed scenario (HTTP/TCP/IPv4/Ethernet), walked Physical (1)
→ Application (7).

| If you need to change...                                    | Go to |
|-----------------------------------------------------------------|-------|
| The 7-step order, names, PDU labels, colors                      | `index.html` — `STEPS` array |
| Any individual layer's content (header fields, sample values, explanation) | `index.html` — `RENDERERS.<layerkey>` (e.g. `RENDERERS.transport`) |
| Step navigation / prev-next buttons                              | `index.html` — `goToStep()`, `renderStepsNav()` |
| Click-to-explain glossary                                        | `index.html` — `TERM_INFO` |
| The Wireshark correlation block per step (exact labels, filters) | `index.html` — the `.ws-block` markup inside each `RENDERERS.<layerkey>` |
| The brief "other protocols at this layer" list                   | `index.html` — `PROTOCOLS_BY_LAYER` + `protocolListHtml()` |
| Whether the backend does anything beyond serving the page        | `packet-journey/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **The scenario (HTTP GET over TCP/IPv4/Ethernet) is fixed, not
  configurable** — adding a UDP/HTTPS/IPv6 variant is a real scope
  decision, not a small tweak; check with the owner first, since the whole
  point right now is depth on one example over breadth across variants.
- **Steps 5 (Session) and 6 (Presentation) intentionally show NO header
  field** — that absence is the actual teaching content at those two
  steps (a real HTTP/TCP/IP packet has no Session or Presentation header
  at all). Don't "complete the pattern" by inventing fake fields for them.
- **Direction vs. framing are deliberately reconciled**: navigation goes
  Physical→Application (matches what the owner asked for, reads as the
  receiving side revealing headers one at a time), but each step's prose
  still explains that header's job from the SENDING side (since that's
  when it's actually added) — see `packet-journey/CLAUDE.md` for the full
  reasoning if this looks contradictory at a glance.
- **Every glossary reference was checked against `TERM_INFO` with a script
  before shipping** (0 missing, 0 unused) — same convention as every other
  tool here; re-run the same check after adding new content.
- **Each step's `.ws-block` uses the exact same sample values as that
  step's own field table** (same MACs/IPs/ports/TTL) — they're two
  independent hand-written blocks, not generated from one source, so a
  change to the scenario's values must be applied to both.
- **`PROTOCOLS_BY_LAYER`'s per-layer lists are deliberately brief** (one
  line each) — going deeper per protocol here would recreate the exact
  scope that got the standalone "Layer Explorer" tool removed.

---

## Tool: VLAN Designer — mounted at `/tools/vlan-designer/`

Entirely client-side, same pattern as Subnet Calculator — pure logic, no
secrets, no network calls. Built as one connected scenario (VLANs → switch
ports → router → reachability), not a reference tool. Phases 1-2 built;
see `vlan-designer/CLAUDE.md` for the phases still open (DHCP relay, ARP).

| If you need to change...                                    | Go to |
|-----------------------------------------------------------------|-------|
| VLAN-to-subnet allocation (largest-first, with gateway IP)       | `index.html` — `planVlans()` |
| The shared state driving tabs 1-4                                | `index.html` — `VLAN_PLAN` + `refreshDependentTabs()` |
| Switch access/trunk port planning + the 802.1Q frame diagram      | `index.html` — `renderPortsTab()`, "Tab 2" section |
| Router-on-a-stick sub-interfaces + generated CLI config           | `index.html` — `renderRouterTab()`, "Tab 3" section |
| The reachability checker (same-VLAN vs cross-VLAN path)           | `index.html` — `runReachCheck()`, "Tab 4" section |
| ACL rules blocking otherwise-valid routes                         | `index.html` — `checkAcl()` (engine), ACL rows card + `getAclRules()` (Tab 4 UI) |
| STP root-bridge election / port roles (fixed 2-switch topology)   | `index.html` — `computeStp()` (engine), `runStp()`, "Tab 5" section |
| Click-to-explain popovers                                        | `index.html` — `TERM_INFO` dict |
| Whether the backend does anything beyond serving the page        | `vlan-designer/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **IP-math functions are intentionally duplicated from Subnet Calculator**,
  not imported/shared — tools never import each other's code (see root
  `CLAUDE.md`). If a bug is found in one copy (e.g. `hostInfo()`'s /31//32
  handling), check whether the same bug exists in the other tool's copy too.
- **`planVlans()` sorts largest-first internally, re-sorts to input order
  for display** — identical reasoning to Subnet Calculator's `planVlsm()`.
  Don't display in allocation order.
- **Tabs 2-4 have no state of their own** — they're pure re-renders of
  `VLAN_PLAN`, called via `refreshDependentTabs()` whenever tab 1's plan
  changes. There's no per-tab memory across a VLAN-plan edit.
- **Every inline glossary reference was checked against `TERM_INFO` with a
  script before shipping** — a dangling reference silently produces an
  empty/broken popover, which is exactly the kind of thing easy to
  introduce and easy to miss by eye. Re-run that check after adding new
  inline `showInfoPopover(...)` references.
- **`checkAcl()` has no implicit "deny everything else"** unlike a real
  router ACL — only explicit rules matter, no match means permit. A
  deliberate, documented simplification (see the ACL card's hint text),
  not a bug to "fix" toward real Cisco behavior.
- **`computeStp()` models exactly one fixed topology** (two switches, two
  direct parallel links) — not a general spanning-tree algorithm. Tab 5 is
  intentionally NOT wired into `VLAN_PLAN`/`refreshDependentTabs()`; it has
  no relationship to the VLAN plan and was never meant to.

---

## Tool: DNS Lookup — mounted at `/tools/dns-lookup/`

Client-side, but genuinely needs internet access (the one tool in the
Toolbox that isn't fully offline) — `dns-lookup/server.py` only serves the
static page; every actual DNS query is a `fetch()` from the browser
straight to a public DNS-over-HTTPS provider (Cloudflare or Google).

| If you need to change...                                    | Go to |
|-----------------------------------------------------------------|-------|
| Domain input parsing/validation (`normalizeDomain`, `looksLikeDomain`) | `index.html` — `ENGINE` block |
| TTL formatting, MX/SOA/CAA parsing, TXT/CNAME cleanup for display | `index.html` — `humanizeTtl()` / `parseMx()` / `parseSoa()` / `parseCaa()` / `formatRecordData()` |
| Which record types get queried (currently 14: A, AAAA, CNAME, MX, TXT, NS, SOA, CAA, SRV, NAPTR, DNSKEY, DS, TLSA, SSHFP) | `index.html` — `RECORD_TYPES` array |
| Which DoH providers are offered                                  | `index.html` — `PROVIDERS` object |
| The actual `fetch()` call to the DNS provider                    | `index.html` — `dohQuery()` |
| CNAME-chain detection/labeling in results                        | `index.html` — `renderResults()` (`hasChain`, `DNS_TYPE_NAMES`) |
| NXDOMAIN handling (domain doesn't exist at all)                  | `index.html` — `renderNxdomain()` + the `allNxdomain` check in `runLookup()` |
| Click-to-explain popovers for each record type / TTL             | `index.html` — `TERM_INFO` dict |
| SOA's field-by-field breakdown (mname/rname/serial/refresh/retry/expire/minimum) | `index.html` — `renderSoaFieldGrid()` + the `soaMname`/`soaRname`/etc. `TERM_INFO` entries |
| Reverse DNS / PTR lookup (IP → hostname)                          | `index.html` — `ipToReverseArpaName()`, `parseIpv4()`, `runReverseLookup()`, "Reverse lookup tab" section |
| Private/reserved-IP short-circuit for reverse lookups             | `index.html` — `isPrivateOrReservedIpv4()` |
| Whether the backend does anything beyond serving the page        | `dns-lookup/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **An `A` query's answer can contain a `CNAME` row too** — DoH providers
  follow aliases automatically and return the whole chain. The renderer
  labels each row by its OWN type (not the queried type) specifically to
  show this. Don't collapse it to "just show A records."
- **NXDOMAIN (`Status: 3`) is checked separately from "no records of this
  type"** (`Status: 0` with empty/missing `Answer`) — the second case is
  normal and common (most domains lack a TXT record, say), the first means
  the domain doesn't exist anywhere. Conflating them produces a false
  "doesn't exist" for a perfectly real domain.
- **The DoH response omits the `Answer` key entirely on NXDOMAIN** — code
  relies on `data.Answer || []` for this; confirmed against the real
  Cloudflare API, not assumed from docs.
- **This tool's engine tests don't cover the network layer** (can't
  `node -e` a real `fetch`) — only the pure parsing/formatting functions
  are unit-tested that way. The `fetch`/response-shape assumptions were
  instead verified by curling the real provider endpoints directly.
- **Coverage was deliberately expanded from 6 to 14 record types** after
  initial feedback that "all 14 record types" was the actual expectation,
  not just the common six. All 14 are still queried on every lookup — that
  part hasn't changed.
- **Empty record types are hidden by default now (reversed from an earlier
  decision).** An earlier version of this file said "don't hide empty
  sections... the whole point is showing what was actually checked" — the
  owner later found seeing 8+ "no records found" sections on every lookup
  was confusing rather than informative, so `renderResults()` now shows
  only the record types with actual data, with the empty ones (still
  queried, not skipped) tucked behind a "Show N record types with no
  data" toggle (`buildRecordSection()` returns `{empty, html}`;
  `toggleEmptyRecordTypes()` reveals them). Nothing is deleted or
  unqueried — this is a default-visibility change, not a coverage
  rollback. If this gets revisited again, update this note rather than
  leaving both "don't hide" and "hide by default" claims in the file.
- **SOA now gets a dedicated field-by-field breakdown** (`renderSoaFieldGrid()`)
  instead of going through the generic per-record-type table — it's a
  special case inside `renderResults()`'s loop. CAA still just gets light
  inline formatting (`parseCaa()`), that wasn't upgraded to the same
  treatment and there's no plan to.
- **Reverse-DNS octet reversal is mandatory, not cosmetic** — confirmed by
  querying the SAME real IP both reversed and un-reversed: reversed
  succeeds, un-reversed returns `SERVFAIL` (Status 2), not just an empty
  answer. `ipToReverseArpaName()` is the only place this should happen;
  don't hand-construct an `.in-addr.arpa` name anywhere else.
- **Private/reserved IPv4 ranges are rejected BEFORE the network call**
  in the reverse-lookup tab (`isPrivateOrReservedIpv4()`) — querying public
  DNS for `192.168.x.x`'s PTR would just return nothing, which reads as a
  tool failure to someone who doesn't already know why; the upfront
  explanation is deliberate, not an unnecessary guard.

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
| VLSM planning — splitting a base block into per-department pools  | `index.html` — `minPrefixForHosts()` + `planVlsm()` (engine), "VLSM planner tab" section (UI) |
| Splitting a block into N *equal*-sized subnets                    | `index.html` — `prefixForEqualSplit()` + `splitEqualSubnets()` (engine), "Split Equal Subnets tab" section (UI) |
| Supernetting / route summarization (many networks → one CIDR block) | `index.html` — `commonPrefixLength()` + `summarizeNetworks()` (engine), "Supernet / Summarize tab" section (UI) |
| Shared widgets used by VLSM/Split/Supernet (proportional bar, results table, add/remove row buttons) | `index.html` — `.block-bar`/`.seg`, `.data-table`, `.add-row-btn`, `.row-remove-btn` CSS classes (generic on purpose — reused across all three dynamic-row tabs) |
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
- **`planVlsm()` sorts largest-requirement-first internally** to guarantee
  correct address alignment (see the `vlsmOrder` popover for why), but
  `allocations` is re-sorted back to the *input* order before being
  returned/displayed — allocation order and display order are deliberately
  different. Don't "simplify" this by displaying in allocation order; that's
  the one thing users explicitly need to NOT have to think about.
- **`minPrefixForHosts()` can return `/31`** for a 2-host request — that's
  correct (RFC 3021: both addresses usable, zero waste), not a bug, even
  though it looks unintuitive next to a "department pool" framing.
- **`summarizeNetworks()` measures waste against actual merged coverage**,
  not just the min-to-max address span — a gap between two non-contiguous
  input networks correctly counts as waste too, not just space beyond the
  outer edges. If you touch the merge loop, keep the three test cases
  (exact tiling / gapped / overlapping) passing, not just the simple one.
- **Overlap detection carries the `raw` label through the merge step**
  (`merged[...].raw`) specifically so overlap warnings can name both
  networks involved — it's easy to "simplify" the merge loop and lose this,
  producing a warning that says `null` instead of a network name (this
  exact bug was caught and fixed once already during development).
- All three of VLSM / Split / Supernet share the same dynamic-row-list
  pattern (`addXRow()` appends a `.row` div with its own remove button,
  wired to re-run that tab's calc function) and the same `.block-bar` /
  `.data-table` CSS. Copy that pattern for any future tab needing a
  variable-length input list instead of inventing a new one.
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

## Tool: cURL Builder — mounted at `/tools/curl-builder/`

Entirely client-side — the Python backend (`curl-builder/server.py`) only
serves the static page; it has no other routes and never sees any input.
This tool only ever generates a command string; it never issues the
request itself (deliberately, to avoid becoming an SSRF proxy — see its
own `CLAUDE.md`).

| If you need to change...                                            | Go to |
|---------------------------------------------------------------------|-------|
| Anything about the form fields (method, URL, auth, body, headers, cookies, flags) | `curl-builder/ui/index.html` — the relevant `<div class="card">`/`<details>` block |
| The generic dynamic key/value row list (used by query params, headers, cookies, urlencoded + multipart body fields) | `index.html` — `makeRowList(...)` |
| Shell-specific quoting/escaping (bash, cmd.exe, PowerShell)          | `index.html` — `quote()` and `contJoiner()` |
| How the final curl command string is assembled from form state      | `index.html` — `generate()` / `assemble(shell)` |
| Which manual headers get silently overridden by Auth/Body settings  | `index.html` — `autoHeaderKeys` inside `generate()` |
| Whether the backend does anything beyond serving the page            | `curl-builder/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **No backend processing, intentionally** — same rationale as
  Encode/Decode: nothing typed here (tokens, passwords, bodies) should
  ever leave the browser, and a "run this for me" endpoint would let any
  visitor make the server issue arbitrary outbound requests (SSRF). Don't
  add one without re-raising that tradeoff with the owner first.
- **Multipart bodies must never carry a manual `Content-Type` header** —
  curl sets its own with the boundary; the generator already strips a
  manual one and shows a warning, don't remove that guard.
- **File fields are typed paths, not real uploads.** The browser never
  reads the file; the path only needs to exist on whatever machine
  actually runs the generated command.
- Mounted at `/tools/curl-builder/` by `main.py` — this folder is a fully
  self-contained ASGI app and doesn't need to know that.

---

## Tool: HTTP Header Reference — mounted at `/tools/header-reference/`

Entirely client-side — the Python backend (`header-reference/server.py`)
only serves the static page; the glossary itself is a data array baked
into the page, no lookups of any kind happen over the network.

| If you need to change...                                            | Go to |
|-----------------------------------------------------------------------|-------|
| Add, correct, or re-categorize a header                              | `header-reference/ui/index.html` — `HEADERS` array |
| Add/edit a category or its plain-language definition                 | `index.html` — `CATEGORIES` array |
| Search/filter behavior                                                | `index.html` — `matches()` |
| The "Related" cross-reference chips (jump to another header)         | `index.html` — `jumpToHeader()` |
| Sidebar per-category counts                                           | Computed live in `renderSidebar()` from `HEADERS` — never hand-maintained |
| Whether the backend does anything beyond serving the page             | `header-reference/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **No backend processing, intentionally** — same rationale as
  Encode/Decode and cURL Builder: nothing the user types (search text)
  needs to leave the browser, and there's nothing to look up server-side
  since the glossary is static data.
- **Deliberately scoped to browse-only, not paste-and-analyze.** The user
  was offered a choice between a browsable glossary, a paste-your-headers
  analyzer, or both — they chose the glossary alone. Don't add a
  paste-and-analyze mode unprompted; it needs its own header-text parser
  that doesn't exist here.
- **Each header has exactly one canonical entry, in exactly one
  category** — a header relevant to more than one category (e.g. `Origin`
  matters to both Request Context and CORS) lives under whichever
  category best explains its primary purpose, and is cross-referenced via
  `related` from the other category's entries instead of being
  duplicated. Duplicating an entry would double-count it in search
  results and in the sidebar's per-category counts.
- **`related` array entries are exact, case-sensitive header names** —
  `jumpToHeader()` does a plain equality lookup; a typo there just fails
  silently (click does nothing) rather than erroring.
- Mounted at `/tools/header-reference/` by `main.py` — this folder is a
  fully self-contained ASGI app and doesn't need to know that.

---

## Tool: HTTP Methods & Status Codes — mounted at `/tools/http-methods-status/`

Entirely client-side — the Python backend (`http-methods-status/server.py`)
only serves the static page; both reference sets (methods, status codes)
are data arrays baked into the page.

| If you need to change...                                            | Go to |
|-----------------------------------------------------------------------|-------|
| Add/edit a method (examples, edge cases, best practices, mistakes)   | `http-methods-status/ui/index.html` — `METHODS` array |
| Add/edit a status code (meaning, when-to-return, examples, compare)  | `index.html` — `STATUS_CODES` array (grouped by `cls`) |
| Add/edit a Decision Guide question (either tab)                       | `index.html` — `METHOD_GUIDE` / `STATUS_GUIDE` arrays |
| Search/filter behavior                                                | `index.html` — `methodMatches()` / `statusMatches()` |
| Status class filter chips (1xx–5xx)                                   | `index.html` — `renderClassChips()` |
| Whether the backend does anything beyond serving the page             | `http-methods-status/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **The Decision Guide is the reason this tool exists, not a bonus
  feature.** It was built specifically to answer "which one do I pick"
  questions (PUT vs PATCH, 401 vs 403, 301 vs 308, 500 vs 502, etc.) — if
  you redesign this tool's layout, keep it prominent (open by default,
  above the searchable list), don't collapse it into an afterthought.
- **`compare` on a status-code entry is inserted as raw HTML, not
  escaped** (so it can bold the "vs NNN" lead-in) — every other field
  (`meaning`, `whenToReturn`, example notes) IS escaped via `escHtml()`.
  Only hand-written trusted text belongs in `compare`.
- **`compare` is deliberately sparse** — only set on the ~13 codes with a
  genuinely common real-world confusion, not added to every code for
  symmetry. Adding it everywhere would bury the comparisons that actually
  matter.
- **A method's `idempotent` field isn't always boolean** — PATCH uses the
  string `'Usually, not guaranteed'` because that's the honest, spec-
  accurate answer (idempotency there depends entirely on the patch
  document's semantics). `methodBadges()` already handles the
  string-vs-boolean split; don't assume boolean elsewhere.
- **No backend processing, intentionally** — same rationale as every
  other reference tool in this toolbox.
- Mounted at `/tools/http-methods-status/` by `main.py` — this folder is
  a fully self-contained ASGI app and doesn't need to know that.

---

## Tool: Cookie Lab — mounted at `/tools/cookie-lab/`

No backend processing (`cookie-lab/server.py` only serves the static
page) — but unlike every other client-side tool here, this one is **not
purely static**. Its frontend performs real, persistent reads and writes
against `document.cookie`, a live browser API — a deliberate live
playground, not a generator (see the tool's own `CLAUDE.md` for the full
rationale; don't mistake this for a "no backend processing" violation).

| If you need to change...                                            | Go to |
|-----------------------------------------------------------------------|-------|
| The cookie-string builder / pre-click validation warnings             | `cookie-lab/ui/index.html` — `buildCookieString()` / `validateForm()` |
| How a Set Cookie attempt is diagnosed (accepted/rejected + why)       | `index.html` — `setCookieLive()` / `diagnoseOutcome()` |
| Parsing `document.cookie` into the live "Current Cookies" view        | `index.html` — `parseDocumentCookie()` / `renderCurrentCookies()` |
| The "Configured This Session" memory + delete actions                 | `index.html` — `configuredCookies` Map, `recordConfigured()`, `deleteConfigured()` |
| Suggested Experiments cards                                           | `index.html` — `EXPERIMENTS` array |
| Theory/reference content, categories                                  | `index.html` — `THEORY` / `THEORY_CATEGORIES` arrays |
| Decision Guide questions                                              | `index.html` — `COOKIE_GUIDE` array |
| Whether the backend does anything beyond serving the page             | `cookie-lab/server.py` (currently: nothing else, by design) |

### Known non-obvious behavior

- **`Secure` will likely still succeed on `http://localhost:8000`, not
  get rejected** — browsers treat `localhost` as a trustworthy origin
  regardless of scheme, which is what the Secure check actually verifies.
  The tool's copy reflects this as an honest live diagnosis, not a
  canned "rejected" assumption — don't "correct" it to claim rejection.
- **`HttpOnly` set via `document.cookie` drops the ENTIRE write, not just
  that flag.** The checkbox stays enabled on purpose so the user can
  trigger and observe this, rather than being grayed out.
- **`Path` is validated differently than `Domain`** — an unrelated Path
  is never rejected at set-time, only invisible from documents whose
  path doesn't match it; `Domain` IS actively validated and can be
  rejected outright. Copy throughout keeps this distinction precise.
- **The "delete with wrong Path" demo deliberately omits `Max-Age`**
  rather than using `Max-Age=0` — a `Max-Age=0` write to a path with no
  existing cookie is a silent, invisible no-op that teaches nothing; the
  real classic bug (a second, visible, empty-valued sibling cookie
  appearing instead of a clean delete) requires the write to actually
  persist, which needs no expiry at all.
- **No true cross-subdomain `Domain` demo is possible** — this tool is a
  single page on a single host; genuinely testing subdomain-sharing
  behavior needs two real subdomains, which this deployment doesn't
  have. That stays theory-only, stated explicitly in the Reference tab.
- **jsdom (used during this tool's development) is not faithful for**:
  the localhost-Secure exception, `SameSite=None`-requires-`Secure`
  enforcement, HttpOnly's whole-write-drop behavior, `__Host-`/
  `__Secure-` prefix enforcement, and the ~4KB size limit (confirmed
  directly — a 5KB value round-tripped successfully under jsdom, where a
  real browser would drop it) — its `tough-cookie`-backed jar doesn't
  model these browser-specific behaviors. Changes touching them need
  manual verification in a real browser against the running deployment.
- Mounted at `/tools/cookie-lab/` by `main.py` — this folder is a fully
  self-contained ASGI app and doesn't need to know that. Its default
  cookie Path is `location.pathname` (not a hardcoded `/tools/cookie-lab/`)
  for the same relative-path reason every tool's own API calls use
  relative paths — see the root `CLAUDE.md`.

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

---

## Tool: DataFrame Studio — mounted at `/tools/df-studio/`

Click-driven pandas: load CSV/JSON/XML/Parquet, transform via UI
(rename/drop/add column, filter, sort, or a free-form Query box with
Check/Add-to-pipeline modes and quick-insert snippets), inspect
(describe/info/nunique/value counts), export — as a file, as a standalone
`.py` script, or save the pipeline as a reusable named template. Every
step shows the pandas line it maps to. See `df-studio/CLAUDE.md` for the
full picture.

### Symptom → file

| If you need to change...                                          | Go to |
|-----------------------------------------------------------------------|-------|
| Session state, the replay model, file loading, insights, script export, template replay, the Check/Add split (`preview_step`/`apply_step`) | `df-studio/engine.py` |
| A transformation step's behavior or its generated pandas code line     | `df-studio/steps.py` (`STEP_HANDLERS`) |
| API endpoints (`/load`, `/step`, `/step/check`, `/insight`, `/export`, `/script`, `/template/*`) | `df-studio/server.py` |
| Saved-template storage (JSON on disk)                                  | `df-studio/templates_store.py` |
| The frontend: grid (Tabulator.js), form-based step fields, Query box (Check/Add + snippets), pipeline panel, script/template panels | `df-studio/ui/index.html` |
| Adding a brand-new form-based step type                                | `steps.py` (handler) **and** `ui/index.html` (`#f-<type>` fieldset + `<option>`) |
| Adding a new Query-box quick-insert snippet                            | `ui/index.html` — `SNIPPETS` object only, no backend change |

### Known non-obvious behavior (read before touching these areas)

- **Sessions are in-memory only** (`engine.SESSIONS`) — restarting the
  server drops every open session. No persistence to disk by design.
- **The "current" DataFrame is always recomputed by replaying `steps` over
  `original_df`** (`engine.recompute`), never mutated in place — this is
  what makes removing a step from the middle of the pipeline just work.
- **`add_column`/`filter_rows` use `df.eval`/`df.query(engine="python")`** —
  arithmetic, comparisons, string concat on bare column names only, not
  arbitrary Python. The Query box's `custom_code` step is the escape hatch
  for that (real `exec()`, `pd`/`np` in scope, **no sandboxing** —
  deliberate, single-user local tool; revisit before this is ever exposed
  beyond one trusted user). Check mode (`/step/check`) still `exec()`s the
  code — it's a "don't commit yet" toggle, not a safer sandbox.
- **Step handlers raise plain `ValueError`, never `engine.StepError`** —
  `StepError` is a subclass, so `except StepError` alone misses them. This
  bit `engine.apply_template()` for real (a step failing mid-template
  crashed with an unhandled 500 instead of a clean `template_errors`
  response) — fixed by catching `ValueError`. Match that in any new
  per-step try/except.
- **The grid caps preview rows at `engine.PREVIEW_ROW_CAP` (5000)** but
  `/export` and `/script` always run against the full DataFrame — a bigger
  export than the table showed is expected, not a bug.
- **Templates persist `{type, params}` only, never the generated code** —
  code is regenerated from the live `STEP_HANDLERS` on every apply, so a
  codegen fix in `steps.py` automatically improves old saved templates.
- **This is the one tool copied as a whole folder in `../Dockerfile`**
  (`COPY df-studio/ ./df_studio/`) instead of the usual two-line
  `server.py` + `ui/` copy, because it has extra backend modules. Its
  `server.py`/`engine.py` use a try/except dual import so the tool still
  runs standalone from inside `df-studio/` for dev, not just mounted.

## Tool: SQL Studio — mounted at `/tools/sql-studio/`

A Postgres SQL workspace: paste/edit/pretty-print a query (arbitrary
complexity, comments preserved), an optional schema panel — paste
`{"table_name": {"column_name": "data_type"}}` to get table/column
autocomplete, or click "⚡ Fetch Schema" (in the main toolbar, next to
Run) to fetch and load it live once connected — a schema-filter dropdown
right next to it picks which schema(s) to pull from (one, several, or
"All schemas"; not hardcoded to `public`), with same-named tables across
different schemas auto-disambiguated as `schema.table` only when they'd
actually collide — several named query buffers/tabs, keyboard shortcuts
(Ctrl+Enter format, Ctrl+Shift+Enter Run, Ctrl+K template
search, Ctrl+F find/replace floating top-right of the editor VS
Code-style, auto-format on paste), a Templates panel (sidebar, between
Connection and Schema) with ~125 prebuilt Postgres/PL/pgSQL snippets that
insert at the cursor as real Tab-navigable fields, live-filtered against
whatever you're typing with the last word weighted highest — and a
**live Run against a real Postgres database**: a Connection panel (top of
the sidebar, collapsed by default, collapses to a compact status line
once connected) opens a server-side pool of up to 3 connections, Run
executes exactly one statement at a time with a hard 500-row cap enforced
by Postgres itself (`LIMIT`-wrapped, not fetched-then-truncated),
destructive statements (`DROP`/`TRUNCATE`/`DELETE`/`ALTER`) require an
explicit confirm, and results show in a dismissible overlay with CSV/JSON
export — plus **32 "show" commands** (`show tables`, `show table orders
definition`, `show functions`, `show triggers`, `show activity`, ...), a
`psql \d`-family equivalent typed as plain phrases: type one and press
Run, the real system-catalog SQL runs in its place, results show the
same way. They're listed in the Templates panel (typing "show" surfaces
them) and in a full cheatsheet behind the "?" button next to Run. Format,
Templates, and Schema autocomplete remain 100% client-side and
unaffected — only Run/Connect/Export/schema-fetch touch
`sql-studio/server.py`'s backend routes (`db_engine.py`/`query_guard.py`);
show commands are a pure client-side text substitution before Run's
normal pipeline, not a new backend capability.
**Only the header's old "🧩 Templates" nav button was removed** (at the
owner's explicit request) — the Templates panel itself was NOT removed
and is still fully present and always visible; `Ctrl+K` still jumps to
its search box the same way the button used to. See
`sql-studio/CLAUDE.md`'s "Live database connection (Run)" section for the
full Run design (why one global connection instead of df-studio's
per-cookie pattern, the row-cap mechanism's real limits, the
two-copies-kept-in-sync tokenizer).

| If you need to change...                                              | Go to |
|-------------------------------------------------------------------------|-------|
| The CodeMirror editor setup (extensions, basicSetup, keymap, search, paste handler, doc-change listener) | `sql-studio/ui/index.html` — `view`/`EditorState.create(...)` |
| How the pasted schema JSON becomes autocomplete suggestions             | `index.html` — `buildSchemaNamespace()` |
| Applying a newly-pasted schema without rebuilding the editor            | `index.html` — `sqlLangCompartment` / `makeSqlExtension()` / `applySchema()` |
| Format behavior (indentation, keyword case, dialect)                   | `index.html` — `formatQuery()` (`sqlFormat(...)`) — called from the Format button, Ctrl+Enter, and paste-triggered auto-format alike |
| Formatting inside a `$$...$$` stored procedure/function body            | `index.html` — `reformatDollarQuotedBodies()` + `formatPlpgsqlBody()` (sql-formatter itself never touches dollar-quoted content — see `sql-studio/CLAUDE.md` for the known limitations of this hand-rolled pass) |
| Buffer tabs (add/close/rename/switch), migration from the old single-query key | `index.html` — `loadBuffers()`, `switchBuffer()`/`addBuffer()`/`closeBuffer()`/`renameBuffer()`, `renderBufferTabs()` |
| Keyboard shortcuts (Ctrl+Enter format, Ctrl+Shift+Enter Run, Ctrl+K template search) | `index.html` — the `keymap.of([...])` extension in `view`'s config (Format/Run), and the global `keydown` listener near the bottom of the script (Ctrl+K) |
| Ctrl+F find/replace (functionality is stock CodeMirror; only its position/look is custom) | `index.html` — `search({ top: true })` extension + `#editor .cm-panel.cm-search` CSS block (see `sql-studio/CLAUDE.md` for the DOM structure this CSS targets) |
| Auto-format on paste                                                    | `index.html` — `EditorView.domEventHandlers({ paste: ... })` in `view`'s config, `chkAutoFormat` |
| Schema panel parsing/validation/persistence                            | `index.html` — `applySchema()`, `schemaErr` box |
| The "copy schema-fetch query" pgAdmin round-trip helper                 | `index.html` — `SCHEMA_FETCH_QUERY` const, `btnCopySchemaQuery` (uses `json_object_agg`, not `jsonb_object_agg` — see `sql-studio/CLAUDE.md` for a real ordering bug caught by testing against an actual Postgres) |
| Fetching + loading the schema live from the connected database          | `index.html` — `btnFetchSchema` click handler (runs `buildSchemaFetchQuery(getCurrentSchemaFilter())` via `POST /query`, then `applySchema()`) — shares the same query-builder as the manual-copy path (`btnCopySchemaQuery`) above |
| Which schema(s) Fetch Schema pulls from, adding/changing the schema-filter dropdown | `index.html` — `#btnSchemaFilter`/`#schemaFilterPanel`, `schemaFilterAll`/`selectedSchemas` state, `getCurrentSchemaFilter()`, `ensureSchemaListLoaded()`, `resetSchemaFilterState()` (called from `applyConnectionStatus()` on connect/disconnect) — see `sql-studio/CLAUDE.md` for the cross-schema table-name-collision handling in `buildSchemaFetchQuery()` |
| The Templates library (adding/editing snippets, categories, search)     | `index.html` — `TEMPLATES` array (one `{cat, name, sql}` per entry — add a template by adding an entry, nothing else to wire up) |
| The live "type to find it" ranking (last-word priority)                | `index.html` — `currentLineWords()` + `scoreTemplate()` (see `sql-studio/CLAUDE.md` for how the weighting works and how it was verified) |
| Templates panel rendering / search / insertion                          | `index.html` — `renderTemplateList()`, `insertTemplate()` (live mode replaces the trigger word via `currentLineLastWordSpan()`; blank-line padding uses `isAtLineStart()`/`isAtLineEnd()`, whitespace-aware not just single-character — see `sql-studio/CLAUDE.md` for two real bugs found here) |
| Which words in a template become Tab-stop fields, adding a new one     | `index.html` — `PLACEHOLDER_TOKENS` Set (whitelist, not auto-detected) + `toSnippetTemplate()` — see `sql-studio/CLAUDE.md` for how the whitelist was built and verified against all 125 templates |
| localStorage keys for restoring buffers/schema on reload                | `index.html` — `BUFFERS_KEY` (`sql_studio_buffers`), `ACTIVE_BUFFER_KEY` (`sql_studio_active_buffer`), `SCHEMA_KEY` (`sql_studio_schema`), `AUTOFORMAT_KEY` (`sql_studio_autoformat_on_paste`), `CONNECTION_KEY` (`sql_studio_connection` — host/port/database/username only, password never persisted); `QUERY_KEY` (`sql_studio_query`) is legacy, read-only, for one-time migration into buffer #1 |
| The live Postgres connection pool (connect/disconnect/status, idle reaper) | `sql-studio/db_engine.py` — `STATE` (module-level, singular — see `sql-studio/CLAUDE.md` for why NOT a per-cookie dict), `connect()`/`disconnect()`/`status()`, `_reaper_loop()`/`_ensure_reaper_started()` |
| Whether a query is allowed to run, the destructive-statement check, the `LIMIT 500` wrap | `sql-studio/query_guard.py` — `prepare()` (entry point), `classify()`, `split_statements()` — the server-side, authoritative copy; `index.html`'s `splitTopLevelStatements()`/`firstStatementKeyword()` is the client-side UX-only twin, kept in sync by hand |
| Connect/Disconnect/Run/Export backend routes                            | `sql-studio/server.py` — `/connect`, `/disconnect`, `/status`, `/query`, `/export/csv`, `/export/json` |
| Connection panel UI (collapsed-by-default ↔ full-form ↔ collapsed-status-line, localStorage persistence) | `index.html` — `applyConnectionStatus(status, forceOpen)`, `loadConnectionFields()`/`saveConnectionFields()`, `#detConnection` (see `sql-studio/CLAUDE.md` for the `forceOpen` rule — only Disconnect's click handler passes `true`) |
| Run button, the results overlay, the destructive-confirm dialog          | `index.html` — `runQuery()`/`sendQuery()`, `renderResults()` (`#resultsDialog`), `openConfirmDialog()` (`#confirmDialog`) |
| The "show tables"/"show table X definition"/etc. commands — adding one, changing the mapped SQL, the "?" cheatsheet | `index.html` — `SHOW_COMMANDS` array (single source of truth for matching AND the cheatsheet AND the Templates entries), `matchShowCommand()`, `buildHelpDialog()` (`#helpDialog`) — see `sql-studio/CLAUDE.md`'s "Show commands" section before touching array order |

### Known non-obvious behavior

- **Loaded via `<script type="module">`, not a plain `<script>`** — the
  only tool in the Toolbox that does this. CodeMirror 6 is ESM-only, so its
  packages (and `sql-formatter`) are imported directly from esm.sh rather
  than a classic `<script src>` tag like df-studio's Tabulator.js.
- **CodeMirror 6 needs all its packages to resolve to one shared instance**
  of `@codemirror/state`/`@codemirror/view`, or importing them separately
  causes an "Unrecognized extension value" runtime error — hit for real
  while building this tool. Fixed by importing `@codemirror/state` as the
  version *range* `@^6.0.0` (matching the range baked into `codemirror`'s
  own bundle) via esm.sh, so both resolve to the same shim URL. See
  `sql-studio/CLAUDE.md` for the full verification trail — don't change
  these import URLs without re-reading it.
- **`sql-formatter` throws on unparseable SQL** rather than best-effort
  formatting — surfaced in the red error box under the editor, not
  swallowed silently.
- **A structure Outline panel (parsed DECLARE/IF/LOOP/CASE tree, click to
  jump, click-a-variable-to-highlight-its-uses) existed briefly and was
  removed** at the owner's request — too much sidebar/scroll weight for
  this tool's actual workflow. It's not recoverable from git history
  (`sql-studio/` — really the whole repo — is untracked, no VCS at all) —
  see `sql-studio/CLAUDE.md` for the approach if it's ever rebuilt. The
  Templates panel is a **different** case — it's still fully present, see
  the next bullet; only its header nav button was removed.
- **Only the header's old "🧩 Templates" nav button was removed, NOT the
  Templates panel** — the panel (~125-snippet searchable library with
  live-filtering and Tab-stop snippet fields) is still fully present and
  always visible in the sidebar, between Connection and Schema. The
  button just used to open/scroll to it and focus search; `Ctrl+K` still
  does that exact same thing. Don't confuse this with the Outline panel
  above, which really was removed entirely — these are two different
  histories for two different features.
- **The sidebar (`.col-right`) DOES cap its own height and scroll
  independently** (`max-height: calc(100vh - 40px); overflow-y: auto`,
  still `position: sticky`) — **this is a reversal of an earlier
  decision, not an oversight.** The identical change was tried once right
  after the Outline panel shipped, explicitly reverted at the owner's
  request, and documented here as "don't reintroduce without asking
  again." The owner then asked again, once Connection + Templates + 32
  show commands + Schema stacked in one column made an unbounded sidebar
  genuinely unusable (confirmed by the owner's own screenshot). See
  `sql-studio/CLAUDE.md`'s "What this tool is" section for the full
  history — if this gets reverted a second time, treat that the same way
  as the first revert (don't silently re-add it without being asked).
- **Ctrl+F's find/replace panel floats top-right of the editor instead of
  its library-default full-width bottom bar** — the find/replace
  functionality itself is 100% stock `@codemirror/search` (bundled into
  `basicSetup`'s `searchKeymap`, no custom logic); only its position and
  look are overridden (`search({ top: true })` + `#editor .cm-panel.cm-
  search` CSS, `position: absolute` anchored to `#editor`). See
  `sql-studio/CLAUDE.md` for the DOM structure that CSS depends on.
- **Buffer tabs replaced a single flat `sql_studio_query` key** with an
  array (`sql_studio_buffers`) — an existing user's previously-saved query
  is migrated into buffer #1 automatically on first load after this
  shipped, verified against fresh-install/migration/existing-buffers/
  corrupted-JSON scenarios with a standalone Node test before shipping.
- **The paste event fires before CodeMirror inserts the pasted text** —
  auto-format-on-paste's handler has to `setTimeout(fn, 0)` before calling
  `formatQuery()`, or it formats the doc as it was *before* the paste.
- **The live Postgres connection is one global value, not per browser
  tab** — every open tab shares the same connection/pool and sees the same
  `GET /status`. This is deliberate (the owner asked for "a single
  database at a time" with "a pool of 3"), not a missed per-session-cookie
  pattern — see `sql-studio/CLAUDE.md` for why copying df-studio's
  per-cookie `SESSIONS` shape here would have broken that constraint.
- **The idle-connection reaper starts lazily on first successful
  `/connect`, not via a FastAPI `lifespan` hook** — `main.py` mounts every
  tool via `app.mount(...)`, and Starlette does not forward lifespan
  events into mounted sub-apps, so a `lifespan=` handler here would
  silently never run. See `sql-studio/CLAUDE.md`'s "Live database
  connection (Run)" section.
- **Run is hard-limited to exactly one statement, and rejects `COPY`
  outright** — both checked via `query_guard.py`'s statement splitter
  (server-side, authoritative) and `index.html`'s `splitTopLevelStatements()`
  (client-side, UX-only fast path). A `;` or a keyword inside a string,
  comment, or `$$...$$` dollar-quoted body is never mistaken for a
  statement boundary — both implementations reuse the same
  string/comment/dollar-quote-aware tokenizing rules as the PL/pgSQL
  formatter's own `tokenizePlpgsqlBody()`.
- **Export never re-runs the query — it serializes the last cached
  result** (`db_engine.STATE.last_result`, set on every successful
  rows-shaped `/query`, cleared on every non-rows one). Re-querying on
  export would double-execute a `DELETE`/`UPDATE`; this is why it doesn't.
- **The 500-row cap is enforced by an outer `LIMIT` at Postgres itself**
  (`SELECT * FROM (<query>) AS _sq LIMIT 500`), not fetched-then-truncated
  in Python — guarantees the row count returned, but does **not** by
  itself guarantee bounded query *cost* for aggregate/`GROUP BY`/window
  queries over a huge table (Postgres still computes the full aggregation
  before the outer `LIMIT` trims output). Runtime is bounded separately —
  see the next bullet.
- **A 15-second `statement_timeout` applies to every query, set on the
  connection pool's conninfo** (`db_engine.STATEMENT_TIMEOUT_MS`) — this
  is what actually bounds a slow query, since the row cap above doesn't. A
  query that runs long gets cancelled by Postgres (`QueryCanceled`) and
  surfaced as a clean error instead of hanging one of the pool's 3
  connections indefinitely.
- **The live connection already survives an ordinary browser refresh —
  no session/cookie/client-side storage involved.** `STATE` lives in
  server-process memory; `GET /status` (polled on every page load)
  reports it regardless of how many times the page reloads. Only three
  things actually drop it: the 20-minute idle reaper
  (`db_engine.IDLE_TIMEOUT_SECONDS`), an explicit Disconnect click, or the
  server process itself restarting (e.g. `docker-compose up --build` to
  ship a code change) — the last one is easy to mistake for "refresh
  drops it" if a rebuild and a refresh happen close together during
  active development. Verified directly (connect, then poll `/status`
  repeatedly with nothing else touched — stayed connected). Don't add
  session storage or client-side reconnect logic to "fix" this.
- **Run honors a text selection (pgAdmin/DataGrip-style)** — a non-empty
  selection in the editor runs only that selected text
  (`view.state.sliceDoc(...)`), not the whole buffer; no selection falls
  back to the previous whole-document behavior. Covers the Run button,
  `Ctrl+Shift+Enter`, and the destructive-confirm preview all at once,
  since they all just consume whatever `runQuery()` decides `sqlText` is.
- **A `<dialog>`'s `display` CSS must stay scoped to `[open]`** — a real
  bug: `dialog#resultsDialog { display: flex; ... }` with no `[open]`
  qualifier out-specificities the browser's own `dialog:not([open]) {
  display: none; }` (an ID selector beats a type+pseudo-class one), so the
  results panel showed permanently, inline in the page, instead of only
  via `showModal()` on Run. Fixed by moving `display: flex;
  flex-direction: column;` to `dialog#resultsDialog[open]`; sizing rules
  stayed unscoped since they don't affect visibility. See
  `sql-studio/CLAUDE.md` before adding more dialog CSS.
- **The Connection panel starts collapsed and stays that way on a silent
  page-load status check** — only an explicit Disconnect click passes
  `forceOpen: true` to re-expand it. A silent `GET /status` on load must
  never force it open; an earlier version did, which is what the owner
  flagged as "connection should not [be] shown [by] default." See
  `sql-studio/CLAUDE.md`'s "Live database connection (Run)" section.
- **The header has no trust badge at all now** — just the title. Both
  badges that ever existed (the original "100% client-side" one, and a
  later Run-specific second line) plus the descriptive subtitle line were
  each tried and explicitly removed at the owner's request ("wasting
  space, no use case" the first time, "make more space" the second).
  Don't reintroduce any of them without asking again.
- **The "⚡ Fetch Schema" button lives in the main editor toolbar (next to
  Run), not inside the Schema panel** — moved there at the owner's
  request so it's reachable without expanding/scrolling the sidebar. Its
  id (`btnFetchSchema`) and all its JS (click handler, the disabled/title
  toggling in `updateConnectionGatedButtons()`) are unchanged — only its
  HTML position moved, `getElementById` doesn't care where in the page an
  element lives.
- **The Schema panel's two explanatory hint paragraphs were removed**
  ("no one reads this") — `btnLoadExample` survived, relocated to a small
  link next to `btnApplySchema`. The third hint (explaining
  `btnCopySchemaQuery`, directly above that button) was left alone.
- **"show" commands are a pure client-side text substitution, not a new
  backend capability** — `matchShowCommand()` swaps the typed phrase for
  real SQL entirely in the browser, before `POST /query` is ever called;
  `query_guard.py` never sees or knows about "show tables" text. All 32
  are verified against a real Postgres (not written from memory) — see
  `sql-studio/CLAUDE.md`'s "Show commands" section.
- **`SHOW_COMMANDS` array order matters for literal-phrase commands that
  share a prefix with a generic parameterized one** — e.g. `show table
  sizes` must be listed before the generic `show table <name>` pattern,
  or "sizes" gets matched as if it were a table name. Parameterized
  patterns with a trailing suffix (`show table X definition`) don't have
  this problem — they're strictly anchored and can't collide with the
  bare `show table X` form regardless of order.
- **Object definitions are looked up by bare name via explicit catalog
  joins, not `'name'::regclass`/`'name'::regproc` casts** — those depend
  on the connection's `search_path` and silently do the wrong thing for
  anything outside it. See `sql-studio/CLAUDE.md` for the specific bug
  this was rewritten to avoid.
- **Clicking a "?" cheatsheet row runs it immediately for a no-parameter
  command, but only inserts it into the editor for a parameterized one**
  — a real reported friction point, not a design nicety: "Show
  Materialized Views" used to just paste text requiring a manual Run
  press, exactly backwards when the whole point was seeing the list of
  names right away. Each row's small right-aligned tag ("▶ run now" / "✎
  fill in & run") tells you which one to expect before clicking. See
  `sql-studio/CLAUDE.md` for the detection mechanism and its one sharp
  edge (a future parameterized command not written with a `(\S+)`
  capture group would be silently misclassified as run-now).
- **`show table X definition`/`show function X definition`/etc. used to
  render as one unreadable line** — the results `<table>`'s CSS needs
  `white-space: nowrap` for ordinary short-value rows, which silently
  collapsed the real embedded newlines in these DDL results. Fixed by
  detecting the *shape* (one row, one column, the cell is a string
  containing `\n`) and rendering that case as preformatted text instead
  of a table — see `sql-studio/CLAUDE.md` for `.results-definition` and
  why it uses `pre-wrap` rather than plain `pre`.

## Tool: Schema Map — mounted at `/tools/schema-map/`

A **read-only**, progressive-disclosure explorer for large Postgres
schemas — connect, and see tables + foreign-key relationships as an
interactive Cytoscape.js graph, without ever rendering more than what's
currently expanded (a naive "graph every table at once" is unreadable
past a few dozen tables regardless of layout algorithm — this tool
exists specifically for schemas with hundreds to ~1000 tables). Built
for two motivations: seeing which tables cluster together before a
monolith → microservice split, and seeing everything transitively
connected to a table before migrating it. Editability (manual groups,
manual non-FK links) is deliberately out of scope for the current build
— see `schema-map/CLAUDE.md` for the full reasoning trail (Neo4j and
Kùzu were both seriously considered and rejected in favor of `networkx`,
given the actual confirmed scale).

**Build status**: Steps 1–3 of a 6-step plan are done (connection,
data-fetching, basic graph rendering), plus Step 6 (lazy per-table
column loading on click) pulled forward, plus a visual polish pass
(zoom controls, per-schema node coloring, a row-count/uniform node-size
toggle), plus a Filter feature (pick a table, see everything within 1–2
hops, with the rest of the graph genuinely hidden, not faded) — progressive
disclosure via connected components (Step 4) and interactive hub-collapse
(Step 5) are not yet built. See `schema-map/CLAUDE.md`'s "Build status"
section before assuming any of those exist.

| If you need to change...                                              | Go to |
|-------------------------------------------------------------------------|-------|
| The connection pool (connect/disconnect/status, idle reaper)            | `schema-map/db_engine.py` — same idiom as `sql-studio/db_engine.py` but a genuinely separate `STATE`, smaller pool (`max_size=2`) |
| Which catalog queries run, adding a new introspection query             | `schema-map/introspection_postgres.py` — `get_schemas()`, `get_tables()`, `get_foreign_keys()`, `get_graph()`, `get_table_columns()`; every query is a direct port of an already-verified `sql-studio/ui/index.html` `SHOW_COMMANDS` query, extended to also select each FK's real target schema (`to_schema`) — see "Known non-obvious behavior" below |
| The `/schemas`, `/graph`, `/table/{schema}/{table}` backend routes      | `schema-map/server.py` |
| The schema picker, Connection panel UI                                  | `schema-map/ui/index.html` — `loadSchemaList()`, `applyConnectionStatus()` (Connection panel markup/behavior deliberately mirrors SQL Studio's) |
| How the graph is drawn (node sizing, edge styling, colors, layout)      | `schema-map/ui/index.html` — `renderGraph()`, `sizeFor()`, `buildSchemaColorMap()` — see `schema-map/CLAUDE.md` for why node sizing uses `sqrt` not linear scaling, and why schema colors are deterministic, not random |
| The column detail panel, zoom controls                                  | `schema-map/ui/index.html` — `openTableDetail()`/`closeDetailPanel()` (note the `cy.resize()` call — see `schema-map/CLAUDE.md`), `btnZoomIn`/`btnZoomOut`/`btnZoomFit` handlers |
| The detail panel's per-column FK relationship list                      | `schema-map/ui/index.html` — `buildRelationshipsHtml()`, built from cached `lastGraphData.foreign_keys`, no new endpoint |
| The table-connection Filter (hop depth, blast-radius list, hide/show)   | `schema-map/ui/index.html` — `computeNeighborhood()`/`buildAdjacency()` (undirected BFS over `foreign_keys`), `applyFilter()`/`clearFilter()` (`cy.hide()`/`.show()`, not a fade), `renderFilterResults()` |
| Table search / jump-to-table                                            | `schema-map/ui/index.html` — `populateTableSearch()`, `jumpToTable()` (`#canvasSearch`, native `<input list>`/`<datalist>`) |
| Hub ranking, orphan-table list                                          | `schema-map/ui/index.html` — `computeTableDegrees()` (reuses `buildAdjacency()`), `renderInsights()` (`#detInsights`) |
| FK-column badges in the columns table, the Relationships section        | `schema-map/ui/index.html` — `getTableForeignKeys()` (shared by both), `buildRelationshipsHtml()` |

### Known non-obvious behavior

- **No column data is fetched for any table until it's individually
  clicked** — true since Step 2's queries were first written
  (`introspection_postgres.get_tables()` deliberately stops at
  `{schema_name, table_name, row_estimate, total_size}`), and clicking a
  node now actually surfaces those columns via a separate per-table
  fetch (`GET /table/{schema}/{table}`, `openTableDetail()` in
  `ui/index.html`). Don't "simplify" a future change by folding columns
  into the bulk `/graph` query — see `schema-map/CLAUDE.md`.
- **`row_estimate` is `pg_class.reltuples` (a fast estimate), not
  `COUNT(*)`** — same metric SQL Studio's "Show Table Sizes" uses, and
  for the same reason (hundreds of full-table-scan counts just to draw
  a graph would be slow). A never-`ANALYZE`d table reports `-1`, clamped
  to `0` before node sizing.
- **`cytoscape.js` loads as a classic `<script>` tag, not inside the
  `type="module"` script** — it's a UMD build (global `cytoscape`
  function), not an ES module like SQL Studio's esm.sh CodeMirror
  imports. See `schema-map/CLAUDE.md` for why the load-order isn't a
  race condition despite that split.
- **Node IDs are `schema.table`, not just `table`** — same cross-schema
  name-collision case already verified for SQL Studio's schema-fetch
  feature (`public.orders` vs. `analytics.orders`) applies here too;
  namespacing by schema in the node id avoids two different tables
  colliding into one graph node.
- **A foreign key's target can be in a different schema than its source
  — `introspection_postgres.py` must select the target's real schema
  (`to_schema`), never assume it matches `from_schema`.** A real bug
  found and fixed while building the Filter feature (which builds node
  ids from this data and would silently traverse to the wrong node
  otherwise) — verified against a genuine cross-schema FK added to the
  dev database. See `schema-map/CLAUDE.md` for the full story.
- **A single-schema `/graph` fetch must include cross-schema FKs from
  BOTH directions** — `_FOREIGN_KEYS_SQL_ONE_SCHEMA` matches the
  selected schema on either the FROM or TO side (`OR`, not just FROM).
  An earlier version only matched FROM, silently dropping any FK where
  a table OUTSIDE the selected schema references INTO it — found when
  the Filter feature showed a table's outgoing dependencies but not its
  incoming ones while a single schema was selected. See
  `schema-map/CLAUDE.md` for the full story and why this one's easy to
  reintroduce by accident.
- **The table detail panel shows FK relationships now, not just
  columns** — below the columns table, a "Relationships" section lists
  every FK this table takes part in as a clickable `column → other
  table.column` link, split into "References" (outgoing) and
  "Referenced by" (incoming). Built client-side from the already-cached
  graph data, not a new backend call. Node labels also moved above each
  node (`text-valign: "top"`), not below.
- **"Degree" in the Insights card counts distinct connected tables, not
  raw FK rows** — two FK columns on the same table pointing at the same
  other table count as one coupling relationship, not two. See
  `schema-map/CLAUDE.md` for the verified real numbers (`orders`/`users`
  top the hub list at degree 6, `employees`/`analytics.daily_stats` are
  the orphans).
- **The Filter feature's traversal is undirected and hides, not fades**
  — the owner explicitly confirmed both: "both directions" (what a
  table references AND what references it both count toward its
  neighborhood) and a true hide ("show only nodes which comes in filter
  other does not show"), not the more common highlight/dim pattern. A
  node's reported hop distance is its shortest path from the selected
  table (plain BFS, first-visit wins) — don't reintroduce a
  directed-only or fade-based version without re-confirming that's
  actually what's wanted now.
- **Table labels are held to a constant on-screen size regardless of
  zoom** (`keepLabelSizeConstant()`) — cytoscape scales font size with
  the rest of the graph's geometry by default, which reads as
  disorienting text growth while zooming in. Past 60 tables in the
  current view, no persistent labels are drawn at all (hover tooltip
  only) — a stopgap for "the whole loaded scope renders at once," not a
  substitute for real progressive disclosure (Step 4, not built yet).
  See `schema-map/CLAUDE.md` for a real bug found while building this
  (a clamp floor that silently broke the constant-size guarantee at
  high zoom) and why `min-zoomed-font-size` was removed rather than
  kept alongside the fix — the two approaches directly contradict each
  other.
