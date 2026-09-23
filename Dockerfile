# =============================================================================
# Toolbox — Dockerfile
# =============================================================================
# One image, one container, one process: serves the home page (main.py) and
# every tool mounted inside it (currently just DataDiff Pro).
# Build:   docker build -t toolbox .
# Run:     docker-compose up
# =============================================================================

# Use the official slim Python 3.11 image as the base.
# "slim" strips dev tools and docs to keep the image small (~60 MB base).
FROM python:3.11-slim

# Set a working directory inside the container.
WORKDIR /app

# --- Install dependencies first (separate layer for better caching) ----------
# Copy only the requirements file first so Docker can cache this layer.
# If requirements.txt doesn't change, this layer is reused on every rebuild.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Copy application code ---------------------------------------------------
# DataDiff Pro (tool #1) — uses the un-namespaced "core"/"api" top-level
# packages. Grandfathered as-is; any NEW tool must NOT reuse these two
# names (see encode_decode/ below for the pattern new tools should follow:
# each gets its own uniquely-named top-level package).
COPY core/ ./core/
COPY api/   ./api/
COPY ui/    ./ui/
COPY environments/ ./environments/

# Encode/Decode (tool #2) — namespaced under its own package so it can
# never collide with another tool's "core"/"api"/etc.
COPY encode-decode/server.py ./encode_decode/server.py
COPY encode-decode/ui/       ./encode_decode/ui/

# Subnet Calculator (tool #3) — same namespacing pattern.
COPY subnet-calc/server.py ./subnet_calc/server.py
COPY subnet-calc/ui/       ./subnet_calc/ui/

# DNS Lookup (tool #4) — same namespacing pattern.
COPY dns-lookup/server.py ./dns_lookup/server.py
COPY dns-lookup/ui/       ./dns_lookup/ui/

# VLAN Designer (tool #5) — same namespacing pattern.
COPY vlan-designer/server.py ./vlan_designer/server.py
COPY vlan-designer/ui/       ./vlan_designer/ui/

# Packet Journey (tool #6) — same namespacing pattern.
COPY packet-journey/server.py ./packet_journey/server.py
COPY packet-journey/ui/       ./packet_journey/ui/

# cURL Builder (tool #7) — same namespacing pattern.
COPY curl-builder/server.py ./curl_builder/server.py
COPY curl-builder/ui/       ./curl_builder/ui/

# HTTP Header Reference (tool #8) — same namespacing pattern.
COPY header-reference/server.py ./header_reference/server.py
COPY header-reference/ui/       ./header_reference/ui/

# HTTP Methods & Status Codes (tool #9) — same namespacing pattern.
COPY http-methods-status/server.py ./http_methods_status/server.py
COPY http-methods-status/ui/       ./http_methods_status/ui/

# Cookie Lab (tool #10) — same namespacing pattern.
COPY cookie-lab/server.py ./cookie_lab/server.py
COPY cookie-lab/ui/       ./cookie_lab/ui/

# DataFrame Studio (tool #11) — same namespacing pattern, but copied as a
# whole folder (not the usual two-line server.py + ui/ copy) because it has
# extra backend modules (engine.py, steps.py) alongside server.py.
COPY df-studio/ ./df_studio/

COPY main.py .
COPY registry.yaml .

# Create empty __init__.py files so Python treats these as packages.
RUN touch core/__init__.py api/__init__.py encode_decode/__init__.py subnet_calc/__init__.py dns_lookup/__init__.py vlan_designer/__init__.py packet_journey/__init__.py curl_builder/__init__.py header_reference/__init__.py http_methods_status/__init__.py cookie_lab/__init__.py df_studio/__init__.py

# --- Runtime config ----------------------------------------------------------
# Tell Python not to write .pyc files and not to buffer stdout/stderr.
# Unbuffered output means logs appear immediately in docker-compose logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

EXPOSE 8080

# Start the toolbox app (main.py) with uvicorn — this is the one process
# that serves the home page and every mounted tool.
# --host 0.0.0.0  makes it reachable from outside the container.
# --workers 1     MUST stay 1. DataFrame Studio keeps session state
#                 (engine.SESSIONS) in an in-memory dict inside one process.
#                 With >1 worker, uvicorn runs separate OS processes that
#                 don't share memory, so a session created by one worker is
#                 invisible to the other — the /load that created it and a
#                 later /step can land on different workers and produce
#                 "No active session" for what looks like no reason. Every
#                 other tool here is stateless/client-side and wouldn't
#                 care, but this one does. Don't raise this without giving
#                 df-studio a real shared session store first.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
