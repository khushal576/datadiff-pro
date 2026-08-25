# Repo direction: single-repo, single-container multi-tool website

This repo started as one tool (DataDiff Pro). The owner wants it to grow into
a **one-stop collection of internal tools** reachable through one shared home
page — potentially many tools over time, all served as **one bundled website
from one Dockerfile / one container**. This file exists so that as the repo
grows, future work stays consistent instead of drifting tool-by-tool.

**Decision: one repo, one Dockerfile, one container.** No separate repo per
tool, no separate container per tool, no reverse proxy, no inter-container
network. An earlier iteration of this plan used separate containers per tool
behind a proxying gateway — the owner explicitly rejected that in favor of
one bundled process. Do not reintroduce multi-container/gateway architecture
without the owner asking for it again.

## How it actually works

- `main.py` at the repo root is the **one entrypoint**. It defines the home
  page (`GET /`) and mounts every tool's own FastAPI `app` object under
  `/tools/<name>` using Starlette's `app.mount(...)` — an in-process ASGI
  mount, not a network call. No httpx, no proxy, no separate port per tool.
- Each tool still lives in its own folder (`core/`, `api/`, `ui/` today for
  DataDiff) and keeps its own FastAPI `app` object fully self-contained and
  functional on its own — `main.py` just imports and mounts it.
- `registry.yaml` is display-only metadata for the home page cards (name,
  title, description, icon). It does **not** wire up routing — adding a
  tool still requires one `app.mount(...)` line in `main.py`. Don't confuse
  "registered in registry.yaml" with "actually wired up."
- One `Dockerfile` copies every tool's code plus `main.py` and
  `registry.yaml` into one image. One `docker-compose.yml`, one service,
  one port (`8000` on the host — deliberately not `8080`, which is commonly
  taken locally by other tools such as Jenkins).
- Each tool's frontend still calls its own API with **relative paths**
  (`fetch('compare', ...)`, not `fetch('/compare', ...)`). This is what
  lets the same page work whether it's mounted under `/tools/<name>/` or
  (if a tool is ever run standalone for dev/testing) at its own root — same
  reasoning as before, just no longer load-bearing for isolation, only for
  correctness of relative links.

## Current structure

```
datadiff-pro/                (repo root)
├── core/  api/  ui/          DataDiff Pro's own code (unchanged since launch)
├── environments/  notebook/
├── main.py                    THE entrypoint — home page + mounts every tool
├── registry.yaml               home-page card metadata (display only)
├── Dockerfile                  builds the one image (copies every tool)
├── docker-compose.yml          one service, host port 8000
├── requirements.txt             shared dependency set for the whole image
├── README.md
├── CLAUDE.md                   (this file)
└── GITHUB_AUTH.md
```

Runtime: `docker-compose up --build -d` from the repo root. Open
**http://localhost:8000** for the home page; click a tool card to open it in
a new tab at `/tools/<name>/`.

## Finding your way around

`KNOWLEDGE_MAP.md` is the "I need to change X, where do I go" lookup table —
per-tool, symptom-to-file, plus the known non-obvious behaviors worth
knowing before touching certain code. Read it before exploring a tool's
files from scratch. Every tool added must get its own section there in the
same shape as DataDiff Pro's — this is what keeps navigation sane once the
repo has 10+ tools instead of 1. If you change what a file is responsible
for, update its row in that file in the same commit — a stale map actively
misleads, which is worse than no map.

## Adding a new tool

(Followed twice already — Encode/Decode and Subnet Calculator — this is the
tested checklist, not a guess.)

1. New top-level folder for the tool's own code (its own `core`/`api`/`ui`
   equivalent — organize however fits that tool, doesn't need to mirror
   DataDiff's shape, doesn't need to be FastAPI, but it must expose an ASGI
   `app` object if it's Python/FastAPI-based so `main.py` can mount it the
   same way).
2. Its frontend calls its own API with relative paths (see above) — this is
   the one hard requirement for a page to work correctly when mounted under
   a path prefix.
3. **Give it a uniquely-named top-level Python package** — never reuse
   `core` or `api` (DataDiff Pro already owns those, grandfathered as-is).
   Namespace the tool's own code under its own folder name instead (see
   `encode-decode/` → copied into the image as `encode_decode/`, imported
   as `from encode_decode.server import app`). This is the one thing that
   actually breaks silently if skipped — two tools both exposing a top-level
   `core` package means whichever gets imported second in `main.py` wins,
   and the other tool's real code never runs.
4. In `main.py`: `from <tool_package>.<module> import app as <name>_app`,
   then `app.mount("/tools/<name>", <name>_app)`.
5. One entry in `registry.yaml` so it gets a home-page card.
6. Add its dependencies to the root `requirements.txt` (watch for version
   conflicts with existing tools' dependencies — since everything now
   shares one Python environment, this is the real cost of the "one
   container" tradeoff; a genuine conflict is the signal to reconsider, not
   something to route around silently). If a tool needs no Python packages
   beyond what's already there (e.g. a pure client-side tool like
   Encode/Decode), this step is a no-op — nothing to add.
7. Update `KNOWLEDGE_MAP.md` with this tool's section.
8. **Add a `CLAUDE.md` inside the tool's own folder** — short, scoped to
   just that tool (what it does, where each piece of logic lives, its own
   gotchas), pointing back to this file and `KNOWLEDGE_MAP.md` for anything
   repo-wide. This is what lets a future session opened directly inside
   `<tool>/` get oriented without pulling in every other tool's context
   first. See `encode-decode/CLAUDE.md` or `subnet-calc/CLAUDE.md` for the
   shape to copy.
9. Rebuild the one image: `docker-compose up --build -d`.

## Operating notes (the owner is not a developer)

- One thing to start/stop: `docker-compose up --build -d` / `docker-compose
  down` from the repo root. No network setup, no per-tool containers.
- Only commit when explicitly asked. Only push when explicitly asked. This
  has been the working agreement all along — it does not change as the repo
  grows.
- GitHub auth for this device is `gh` CLI over HTTPS with a daily forced
  logout (see `GITHUB_AUTH.md`) — that setup is device-level, unrelated to
  this repo's internal structure.
- If a decision here doesn't fit a real situation that comes up, stop and
  ask the owner rather than silently deviating — then update this file with
  the answer so the next session has it.
