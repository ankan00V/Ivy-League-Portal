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

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

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

# Obscura is the render provider that executes JavaScript, and it is a native
# binary rather than a Python package, so requirements.txt cannot bring it in.
# Without it the provider reports itself unconfigured and the chain quietly
# falls through to crawlee - the scraper keeps working but stops reaching the
# client-rendered job boards Obscura was added for, which is a failure that
# would only show up as a gradual drop in listings.
ARG OBSCURA_VERSION=v0.1.11
ARG OBSCURA_SHA256=""
RUN set -eux; \
    arch="$(uname -m)"; \
    case "$arch" in \
      aarch64|arm64) obs_arch="aarch64" ;; \
      x86_64|amd64)  obs_arch="x86_64" ;; \
      *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac; \
    asset="obscura-${obs_arch}-linux.tar.gz"; \
    curl -fsSL --retry 3 -o /tmp/obscura.tar.gz \
      "https://github.com/h4ckf0r0day/obscura/releases/download/${OBSCURA_VERSION}/${asset}"; \
    if [ -n "$OBSCURA_SHA256" ]; then \
      echo "${OBSCURA_SHA256}  /tmp/obscura.tar.gz" | sha256sum -c -; \
    fi; \
    tar xzf /tmp/obscura.tar.gz -C /tmp; \
    install -m 0755 /tmp/obscura /usr/local/bin/obscura; \
    if [ -f /tmp/obscura-worker ]; then install -m 0755 /tmp/obscura-worker /usr/local/bin/obscura-worker; fi; \
    rm -rf /tmp/obscura*; \
    obscura --version
ENV OBSCURA_BINARY_PATH=/usr/local/bin/obscura

# Copy Python packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Install gunicorn for production usage
RUN pip install gunicorn uvicorn[standard]

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
