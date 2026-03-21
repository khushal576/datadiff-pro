# =============================================================================
# DataDiff Pro — Dockerfile
# =============================================================================
# Build:   docker build -t datadiff-pro .
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
COPY core/ ./core/
COPY api/   ./api/
COPY ui/    ./ui/
COPY environments/ ./environments/

# Create empty __init__.py files so Python treats core/ and api/ as packages.
RUN touch core/__init__.py api/__init__.py

# --- Runtime config ----------------------------------------------------------
# Tell Python not to write .pyc files and not to buffer stdout/stderr.
# Unbuffered output means logs appear immediately in docker-compose logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

EXPOSE 8080

# Start the FastAPI app with uvicorn.
# --host 0.0.0.0  makes it reachable from outside the container.
# --workers 2     handles two concurrent requests (plenty for a local tool).
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
