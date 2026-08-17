# =====================================================================
# Dockerfile — grievance-service (Flask microservice, part of the grievance system)
# ---------------------------------------------------------------------
# Same two-stage pattern as every other service in this project, on
# purpose: in a microservices repo you want every Dockerfile to be
# BORING and predictable — a new teammate (or you, in six months)
# should be able to read one service's Dockerfile and immediately know
# how all the others work too. Only the port number, the image LABEL,
# and (for frontend-service only) the static/templates COPY lines
# differ between services.
#
#   Stage 1 "builder" — compiles dependencies (gcc etc.) into a venv.
#   Stage 2 "runtime" — slim image, venv copied in, no compilers.
# =====================================================================

# ============================ STAGE 1: BUILDER ============================
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# gcc: needed to build PyMongo's optional C extensions during pip install.
# Lives only in this discarded builder stage, never in the shipped image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy ONLY requirements.txt first so Docker's layer cache can skip the
# whole `pip install` step on every rebuild where dependencies didn't
# change (which is almost every rebuild, once a service stabilises).
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt


# ============================ STAGE 2: RUNTIME =============================
FROM python:3.11-slim AS runtime

LABEL maintainer="Grievance Team" \
      service="grievance-service" \
      version="1.0" \
      description="Grievance Management System — grievance-service microservice"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    FLASK_APP=app.py

WORKDIR /app

# Copy the pre-built virtual environment — this is the biggest layer in
# the image but only changes when requirements.txt changes upstream.
COPY --from=builder /opt/venv /opt/venv

# ---- Application code layer(s), ordered least- to most-often-changed ----
COPY app.py .

# Non-root user: a compromised process can't write to system paths or
# bind privileged ports. Required by Kubernetes' "restricted" Pod
# Security Standard, which is what you want enabled on a real cluster.
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

# Container-level health check, independent of (and complementary to)
# the Kubernetes liveness/readiness probes in the Deployment manifest —
# useful when running this image directly with `docker run`.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5002/healthz').read()" || exit 1

# Documents the listening port — does NOT publish it by itself; that's
# what container.ports in the Deployment + a Service object are for.
EXPOSE 5002

# Gunicorn (not `python app.py`) is the production entrypoint — Flask's
# built-in dev server is single-threaded and not meant to take real load.
CMD ["gunicorn", "--workers", "3", "--bind", "0.0.0.0:5002", "--access-logfile", "-", "app:app"]
