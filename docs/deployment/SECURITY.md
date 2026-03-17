# ROAR Protocol — Security Configuration Guide

## TLS Configuration

- **Protocols**: TLSv1.2 and TLSv1.3 only (TLSv1.0/1.1 disabled)
- **HSTS**: Enabled with `max-age=31536000` (1 year)
- **Certificates**: Let's Encrypt with auto-renewal via certbot

### Verification

```bash
# Check TLS grade
curl -vI https://yourdomain.com 2>&1 | grep "SSL certificate verify"

# Check HSTS header
curl -sI https://yourdomain.com | grep -i strict

# Verify HTTP redirect
curl -sI http://yourdomain.com | grep -i location
```

## CORS Configuration

**NEVER** use `allow_origins=['*']` in production.

Set `ROAR_ALLOWED_ORIGINS` to your specific domains:

```bash
ROAR_ALLOWED_ORIGINS=https://yourdomain.com,https://app.yourdomain.com
```

### Verification

```bash
# Should fail (origin not allowed)
curl -H "Origin: http://evil.com" -I https://yourdomain.com/roar/agents

# Should succeed (allowed origin)
curl -H "Origin: https://yourdomain.com" -I https://yourdomain.com/roar/agents
```

## Rate Limiting

Two layers of protection:

1. **nginx** (perimeter): IP-based, 100 req/min with burst=20
2. **Application** (RedisRateLimiter): Per-IP, configurable per-minute and per-hour limits

### Configuration

```bash
ROAR_RATE_LIMIT_PER_MINUTE=100
ROAR_RATE_LIMIT_PER_HOUR=1000
```

## Message Security

- **HMAC-SHA256 signing**: All messages signed with shared secret
- **Ed25519 signing**: For DID-based identity verification
- **StrictMessageVerifier**: Enforces signature, timestamp, and replay checks
- **Replay protection**: IdempotencyGuard with 10-minute TTL
- **Body size limits**: 1 MiB (server), 256 KiB (hub)

## Redis Security

- Use `rediss://` (TLS) for production Redis connections
- Set `socket_timeout=2.0` to prevent hanging connections
- Keys expire after 24 hours (TTL on all token store entries)

```bash
# Production Redis URL (TLS)
ROAR_REDIS_URL=rediss://your-redis-host:6379
```

## Security Headers

Configured in nginx:

| Header | Value | Purpose |
|--------|-------|---------|
| `Strict-Transport-Security` | `max-age=31536000` | Force HTTPS |
| `X-Frame-Options` | `DENY` | Prevent clickjacking |
| `X-Content-Type-Options` | `nosniff` | Prevent MIME sniffing |
| `X-XSS-Protection` | `1; mode=block` | XSS filter |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Limit referrer info |

## Security Checklist

- [ ] TLS certificate installed and auto-renewal working
- [ ] HTTP redirects to HTTPS (301)
- [ ] HSTS header present
- [ ] CORS origins explicitly configured (no wildcards)
- [ ] Redis using TLS (`rediss://`)
- [ ] No secrets in code or environment files
- [ ] Rate limiting active at nginx and application layers
- [ ] StrictMessageVerifier enabled for message endpoints
- [ ] Body size limits configured
- [ ] Non-root user in Docker container
- [ ] Metrics endpoint restricted to internal networks
