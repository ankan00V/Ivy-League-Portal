# syntax=docker/dockerfile:1
#
# Image for the VidyaVerse API as a Hugging Face Docker Space.
#
# Differences from backend/Dockerfile, which stays the compose/Caddy image:
#   * the container runs as UID 1000, which is the user Hugging Face runs
#     Spaces as. The compose image's system account would otherwise own the
#     writable resume and model directories the API needs.
#   * one worker instead of four: a free CPU Space has two vCPUs and the app is
#     asyncio-first, so extra workers only multiply the torch footprint.
#   * the embedding model is baked in, because a production startup verifies the
#     embedding service is healthy and a cold container should not download it.

FROM python:3.12-slim AS builder
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/home/user/.cache/huggingface
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir --user -r requirements.lock.txt
RUN mkdir -p "$HF_HOME" \
    && python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-en-v1.5')"

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HF_HOME=/home/user/.cache/huggingface \
    PATH=/home/user/.local/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 user

COPY --from=builder --chown=user:user /root/.local /home/user/.local
COPY --from=builder --chown=user:user /home/user/.cache /home/user/.cache

WORKDIR /app
COPY --chown=user:user . /app
RUN mkdir -p /app/storage/resumes /app/models \
    && chown -R user:user /app/storage /app/models

USER user
EXPOSE 8000

CMD ["gunicorn", "app.main:app", \
     "--workers", "1", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "180", \
     "--graceful-timeout", "30", \
     "--log-level", "info"]
