# Stage 1: Extract openclaw application from official image
FROM ghcr.io/openclaw/openclaw:latest AS openclaw-base

# Stage 2: Python 3.12 slim runtime with Node.js
FROM python:3.12-slim

# Install security updates, Node.js 22.x, and curl
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy openclaw application from base image
COPY --from=openclaw-base /app /openclaw-app

# Create openclaw wrapper script
RUN echo '#!/bin/sh\nexec node /openclaw-app/openclaw.mjs "$@"' > /usr/local/bin/openclaw \
    && chmod +x /usr/local/bin/openclaw

WORKDIR /app

# Install Python dependencies
COPY agent-container/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Agent Container application files
COPY agent-container/server.py .
COPY agent-container/openclaw.json .

# Create session storage directory
RUN mkdir -p /tmp/openclaw/sessions

ENV OPENCLAW_SKIP_ONBOARDING=1
ENV OPENCLAW_CONFIG=/app/openclaw.json
ENV PORT=8080

# Health check for container orchestration
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

EXPOSE 8080

# Build from repo root: docker build -f agent-container/Dockerfile .
CMD ["python", "-u", "server.py"]
