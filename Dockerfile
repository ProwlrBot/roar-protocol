# ROAR Protocol — Hub + Agent Server
# Build: docker build -t roar-hub .
# Run:   docker run -p 8090:8090 roar-hub
#
# For agent server mode:
#   docker run -p 8089:8089 -e ROAR_MODE=agent roar-hub

FROM python:3.12-slim AS base

WORKDIR /app

# Install SDK with server dependencies
COPY python/ ./python/
RUN pip install --no-cache-dir -e "python/.[server,ed25519,cli]"

# Copy examples for demo mode
COPY examples/ ./examples/

# Default: hub mode on port 8090
ENV ROAR_MODE=hub
ENV ROAR_HOST=0.0.0.0
ENV ROAR_PORT=8090

EXPOSE 8090 8089

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
