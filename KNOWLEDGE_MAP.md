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
  not just the common six. Most domains will legitimately show "no records
  found" for several of these (SRV/NAPTR/DNSKEY/DS/TLSA/SSHFP are all
  niche) — that's the correct, honest result, not a sign the lookup missed
  something. Don't hide empty sections to make the page look tidier; the
  whole point is showing what was actually checked.
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
