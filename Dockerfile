# syntax=docker/dockerfile:1
#
# Single-container deployment image for Antideploy.
#
# VidyaVerse is normally two services (FastAPI + Next.js), which is what
# docker-compose.prod.yml runs behind Caddy. Antideploy's free plan allows one
# live application, so this image runs both processes in one container:
# Next.js owns the public port and FastAPI listens on loopback inside it.
#
# This needs no application code change. The frontend proxy in
# frontend/src/app/api/[...path]/route.ts already falls back to
# http://127.0.0.1:8000 when no external backend URL is configured, so the
# browser calls /api/* on its own origin and Next forwards it to the API here.

# ---------- frontend build ----------
FROM node:22-bookworm-slim AS web-build
WORKDIR /web
ENV NEXT_TELEMETRY_DISABLED=1
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# NEXT_PUBLIC_API_BASE_URL is intentionally left unset at build time: with no
# absolute base, src/lib/api.ts routes browser calls to the same origin and the
# catch-all proxy forwards them to the loopback API.
RUN npm run build

# ---------- backend dependencies ----------
FROM python:3.12-slim AS api-build
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*
# Pinned graph only: a runtime image must not resolve a new dependency set
# because an upstream package published a release.
COPY backend/requirements.lock.txt ./
RUN pip install --no-cache-dir --user -r requirements.lock.txt

# Bake the embedding model into the image. Production startup verifies the
# embedding service is healthy, and a free container should not spend its first
# minute downloading ~90 MB from Hugging Face while the platform waits for the
# port to bind.
ENV HF_HOME=/root/.cache/huggingface
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

# ---------- runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    BACKEND_INTERNAL_URL=http://127.0.0.1:8000 \
    HF_HOME=/root/.cache/huggingface

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Node runtime for the Next.js server. Both base images are Debian bookworm,
# so the Node distribution's own toolchain and libraries come across as a unit.
COPY --from=node:22-bookworm-slim /usr/local /usr/local
COPY --from=api-build /root/.local /usr/local
COPY --from=api-build /root/.cache /root/.cache

COPY backend/ /app/api/
COPY --from=web-build /web/.next/standalone /app/web
COPY scripts/antideploy_entrypoint.sh /usr/local/bin/entrypoint.sh

# Resume uploads and model artifacts are written at runtime. They live outside
# the image's source tree so a rebuild never depends on them existing.
RUN chmod +x /usr/local/bin/entrypoint.sh \
    && mkdir -p /app/api/storage/resumes /app/api/models

WORKDIR /app
EXPOSE 3000

CMD ["/usr/local/bin/entrypoint.sh"]
