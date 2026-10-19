# Use the official Python image as a parent image
FROM python:3.12-slim as builder

# Set work directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies needed for building packages
RUN apt-get update \
    && apt-get -y install libpq-dev gcc \
    && apt-get clean

# Install the reviewed, pinned dependency graph. Runtime images must not resolve
# a new dependency set merely because an upstream package published a release.
COPY requirements.lock.txt .
RUN pip install --no-cache-dir --user -r requirements.lock.txt

#########
# FINAL #
#########

FROM python:3.12-slim

# Create directory for the app user
RUN mkdir -p /home/app

# Create the app user
RUN addgroup --system app && adduser --system --group app

# Create the appropriate directories
ENV HOME=/home/app
ENV APP_HOME=/home/app/web
RUN mkdir $APP_HOME
WORKDIR $APP_HOME

# Install dependencies required for runtime
RUN apt-get update \
    && apt-get install -y libpq-dev curl ca-certificates \
    && apt-get clean

# Obscura is an optional JavaScript-rendering provider distributed as a native
# binary. The default image deliberately omits it: downloading an executable
# without a verified digest during application builds is a supply-chain risk.
# An operator can opt in only by setting INSTALL_OBSCURA=true and providing the
# exact trusted SHA-256 for the selected release.
ARG INSTALL_OBSCURA=false
ARG OBSCURA_VERSION=v0.1.11
ARG OBSCURA_SHA256
RUN set -eux; \
    if [ "$INSTALL_OBSCURA" = "true" ]; then \
      test -n "$OBSCURA_SHA256"; \
      arch="$(uname -m)"; \
      case "$arch" in \
        aarch64|arm64) obs_arch="aarch64" ;; \
        x86_64|amd64)  obs_arch="x86_64" ;; \
        *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
      esac; \
      asset="obscura-${obs_arch}-linux.tar.gz"; \
      curl -fsSL --retry 3 -o /tmp/obscura.tar.gz \
        "https://github.com/h4ckf0r0day/obscura/releases/download/${OBSCURA_VERSION}/${asset}"; \
      echo "${OBSCURA_SHA256}  /tmp/obscura.tar.gz" | sha256sum -c -; \
      tar xzf /tmp/obscura.tar.gz -C /tmp; \
      install -m 0755 /tmp/obscura /usr/local/bin/obscura; \
      if [ -f /tmp/obscura-worker ]; then install -m 0755 /tmp/obscura-worker /usr/local/bin/obscura-worker; fi; \
      rm -rf /tmp/obscura*; \
      obscura --version; \
    fi
ENV OBSCURA_BINARY_PATH=

# Copy Python packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy project
COPY . $APP_HOME

# Chown all the files to the app user
RUN chown -R app:app $APP_HOME

# Change to the app user
USER app

# Expose port
EXPOSE 8000

# Command to run the application using Gunicorn with Uvicorn workers
CMD ["gunicorn", "app.main:app", "--workers", "4", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--log-level", "info"]
