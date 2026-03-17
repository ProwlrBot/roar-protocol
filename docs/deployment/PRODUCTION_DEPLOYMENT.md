# ROAR Protocol — Production Deployment Guide

## Prerequisites

- Docker & Docker Compose v2+
- Domain name with DNS pointing to your server
- Python 3.12+ (if running without Docker)

## Quick Start (Docker Compose)

```bash
# 1. Clone and enter the project
git clone https://github.com/ProwlrBot/roar-protocol.git
cd roar-protocol

# 2. Configure environment
cp .env.example .env
# Edit .env — set ROAR_ENV=production, ROAR_ALLOWED_ORIGINS, etc.

# 3. Update nginx config
# Edit deployment/nginx/roar.conf — replace YOUR_DOMAIN with your domain

# 4. Set up TLS certificates
sudo apt install certbot
sudo certbot certonly --standalone -d yourdomain.com
# Certs will be at /etc/letsencrypt/live/yourdomain.com/

# 5. Launch the stack
docker compose -f deployment/docker-compose.prod.yml up -d

# 6. Verify
curl https://yourdomain.com/roar/health
```

## Manual Deployment (without Docker)

```bash
# 1. Install dependencies
cd python
pip install -e ".[server,redis,monitoring]"

# 2. Set environment variables
export ROAR_REDIS_URL=redis://localhost:6379
export ROAR_ENV=production
export ROAR_LOG_LEVEL=INFO
export ROAR_ALLOWED_ORIGINS=https://yourdomain.com

# 3. Start Redis
redis-server --daemonize yes

# 4. Start with Gunicorn
gunicorn roar_sdk.asgi:app \
  --workers $(( 2 * $(nproc) + 1 )) \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 120 \
  --access-logfile -

# 5. Set up nginx (see deployment/nginx/roar.conf)
sudo cp deployment/nginx/roar.conf /etc/nginx/conf.d/roar.conf
sudo nginx -t && sudo systemctl reload nginx
```

## TLS Certificate Renewal

```bash
# Test renewal
sudo certbot renew --dry-run

# Auto-renewal is handled by certbot systemd timer
systemctl status certbot.timer
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ROAR_REDIS_URL` | Yes (prod) | `redis://localhost:6379` | Redis connection URL. Use `rediss://` for TLS. |
| `ROAR_ENV` | No | `development` | Environment name |
| `ROAR_LOG_LEVEL` | No | `DEBUG` | Logging level |
| `ROAR_ALLOWED_ORIGINS` | Yes (prod) | - | Comma-separated CORS origins |
| `ROAR_RATE_LIMIT_PER_MINUTE` | No | `100` | Per-IP requests/minute |
| `ROAR_RATE_LIMIT_PER_HOUR` | No | `1000` | Per-IP requests/hour |
| `GUNICORN_WORKERS` | No | `3` | Number of Gunicorn workers |

## Health Checks

```bash
# Application health
curl https://yourdomain.com/roar/health

# Expected response:
# {"status":"healthy","protocol":"roar/1.0","dependencies":{"redis":"connected"}}

# Prometheus metrics
curl https://yourdomain.com/metrics

# Redis connectivity
redis-cli -u $ROAR_REDIS_URL ping
```

## Scaling

- **Workers**: Set `GUNICORN_WORKERS` to `(2 * CPU_cores) + 1`
- **Redis**: Use Redis Cluster or ElastiCache for high availability
- **Load balancing**: Add upstream servers in nginx config
