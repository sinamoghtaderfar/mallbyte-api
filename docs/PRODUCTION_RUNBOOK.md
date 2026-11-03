# MallByte Production Deployment Runbook

This is a deployment **scaffold**, not a completed deployment. Do not expose it publicly before the security and disaster-recovery checklist is complete.

## Prerequisites

- A trusted HTTPS reverse proxy terminating TLS and forwarding only expected headers.
- Managed PostgreSQL with strong credentials and tested backups.
- Managed Redis with authentication/TLS where supported.
- A secure secret store for `SECRET_KEY`, database/Redis/SMTP credentials and API keys.
- Appropriate DNS, firewall, monitoring and operational ownership.

## Configuration

1. Copy `.env.production.example` to `.env.production` on the deployment host.
2. Replace all placeholders with real noncommitted secrets.
3. Set `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` and `CORS_ALLOWED_ORIGINS` to the exact domains in use.
4. Ensure only the trusted reverse proxy can reach `127.0.0.1:8000`.
5. Persist `/app/media`, `/app/private_media`, `/app/static`; expose public media/static via an authenticated or trusted web layer as applicable. NEVER expose private_support_media directly.
6. Set up the separate Celery worker and beat using the production image and the same environment, with only one beat scheduler.

## Preflight checks

```sh
docker compose -f compose.production.yaml config
docker compose -f compose.production.yaml run --rm web python manage.py check --deploy
docker compose -f compose.production.yaml run --rm web python manage.py migrate --noinput
docker compose -f compose.production.yaml run --rm web python manage.py collectstatic --noinput
docker compose -f compose.production.yaml up -d --build web
docker compose -f compose.production.yaml ps
```

`check --deploy` may surface further issues. Resolve all warnings; do not bypass production checks.

## Health checks

GET `/healthz/` is an intentionally minimal unauthenticated liveness endpoint. It does NOT attest to database/Redis availability; use authenticated monitoring and operational dependency checks separately.

## Release policy

- Do not run this in production with `DEBUG=True` or insecure placeholder credentials.
- Deploy only green CI commits and make database changes backward-compatible.
- Test full checkout, seller operations, permissions and support attachments in staging.
- Verify the recovery procedure with a real backup restore and rehearse rollback.
- Set alerts for elevated 5xx, worker failures, expired TLS certificates and storage usage.
- Before launch, complete the separate MFA and security review for privileged accounts.
