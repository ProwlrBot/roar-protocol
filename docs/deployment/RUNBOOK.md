# ROAR Protocol — Incident Response Runbook

## Service Health Check

```bash
# Quick status
curl -s https://yourdomain.com/roar/health | python -m json.tool

# Docker service status
docker compose -f deployment/docker-compose.prod.yml ps

# Gunicorn workers
docker compose -f deployment/docker-compose.prod.yml exec app ps aux | grep gunicorn
```

## Common Issues

### Redis Connection Failure

**Symptoms**: Health check shows `"redis": "disconnected"`, degraded mode warning in logs.

**Impact**: Falls back to InMemoryTokenStore — token enforcement is per-worker only.

```bash
# Check Redis
docker compose -f deployment/docker-compose.prod.yml exec redis redis-cli ping

# Check Redis logs
docker compose -f deployment/docker-compose.prod.yml logs redis --tail 50

# Restart Redis
docker compose -f deployment/docker-compose.prod.yml restart redis

# Verify recovery
curl -s https://yourdomain.com/roar/health | grep redis
```

### High Error Rate (>5%)

**Symptoms**: Prometheus alert `HighErrorRate` firing.

```bash
# Check application logs
docker compose -f deployment/docker-compose.prod.yml logs app --tail 100 | grep ERROR

# Check nginx error log
docker compose -f deployment/docker-compose.prod.yml logs nginx --tail 100

# Check for resource exhaustion
docker stats --no-stream
```

### Rate Limiting Issues

**Symptoms**: Legitimate users getting 429 responses.

```bash
# Check current rate limit config
echo $ROAR_RATE_LIMIT_PER_MINUTE
echo $ROAR_RATE_LIMIT_PER_HOUR

# Check nginx rate limiting
docker compose -f deployment/docker-compose.prod.yml exec nginx nginx -T | grep limit_req

# Temporarily increase limits (restart required)
export ROAR_RATE_LIMIT_PER_MINUTE=200
docker compose -f deployment/docker-compose.prod.yml up -d app
```

### TLS Certificate Expiry

**Symptoms**: Browser warnings, HTTPS connection failures.

```bash
# Check certificate expiry
openssl s_client -connect yourdomain.com:443 2>/dev/null | openssl x509 -noout -enddate

# Renew certificate
sudo certbot renew

# Reload nginx
docker compose -f deployment/docker-compose.prod.yml exec nginx nginx -s reload
```

### Application Not Starting

```bash
# Check logs
docker compose -f deployment/docker-compose.prod.yml logs app --tail 50

# Common causes:
# - Missing ROAR_REDIS_URL (if Redis is expected)
# - Port 8000 already in use
# - Missing Python dependencies

# Rebuild and restart
docker compose -f deployment/docker-compose.prod.yml build app
docker compose -f deployment/docker-compose.prod.yml up -d app
```

## Restart Procedures

```bash
# Graceful restart (zero-downtime with multiple workers)
docker compose -f deployment/docker-compose.prod.yml exec app kill -HUP 1

# Full restart
docker compose -f deployment/docker-compose.prod.yml restart

# Nuclear option (rebuild everything)
docker compose -f deployment/docker-compose.prod.yml down
docker compose -f deployment/docker-compose.prod.yml up -d --build
```

## Monitoring URLs

| Service | URL | Purpose |
|---------|-----|---------|
| Health | `/roar/health` | Service status + dependencies |
| Metrics | `/metrics` | Prometheus metrics |
| Agents | `/roar/agents` | Registered agent list |
