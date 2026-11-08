# Staging, backup, restore and release gates

## What this delivers

A dedicated, loopback-bound staging application + Celery worker + single beat,
and scripts for PostgreSQL custom-format backups with integrity checks and
**destructive staging-only** restore. Infrastructure is not provisioned by these files.

## Required infrastructure

- Separate staging domain, certificates/HTTPS reverse proxy and firewall
- Dedicated *staging-only* PostgreSQL 16 and Redis with access controls
- Dedicated encrypted secret store and SMTP sandbox; no production payments
- Long-lived storage for public media and private support attachments
- A backup vault separate from the application host

## Deploy an isolated staging host

1. Create `.env.staging` from `.env.staging.example` locally on the staging host.
   Do not commit it. Generate a new `SECRET_KEY` and `MFA_FERNET_KEY`.
2. Provide staging database and Redis. Do not reuse production identifiers.
3. Configure HTTPS termination and a frontend staging origin separately.
4. Build and validate:
   ```sh
   docker compose -f compose.staging.yaml config
   docker compose -f compose.staging.yaml build
   docker compose -f compose.staging.yaml run --rm web python manage.py check --deploy
   docker compose -f compose.staging.yaml run --rm web python manage.py migrate --noinput
   docker compose -f compose.staging.yaml run --rm web python manage.py collectstatic --noinput
   docker compose -f compose.staging.yaml up -d
   docker compose -f compose.staging.yaml ps
   ```
5. Confirm a real email OTP → Authenticator login, restricted admin access,
   store/product moderation, customer cart/checkout, order cancellation,
   worker task execution and private support file access.

## Backup

Install PostgreSQL client tools with the same major version as the database on
the operator host (PostgreSQL 16 for the supplied stack). Both scripts check
the server and pg_dump/pg_restore major versions before operating. A newer
client can emit settings such as transaction_timeout that an older server
cannot restore; a successful dump alone does not prove compatibility.
Export dedicated
credentials from a secrets manager without shell history; use a secure,
unshared directory and an encrypted off-site vault.

```sh
export DB_HOST=staging-postgres.example.internal DB_PORT=5432
export DB_USER=mallbyte_staging DB_NAME=mallbyte_staging
export BACKUP_DIR=/secure/mallbyte-staging-backups
# DB_PASSWORD comes from a secrets manager, not this guide.
bash ops/postgres-backup.sh
```

The script uses `pg_dump -Fc`, checks the dump with `pg_restore --list`,
restricts file permissions, and writes a SHA-256 manifest. **A checksum is
not encryption**. Move the dump to encrypted off-site storage.

Note: PostgreSQL dumps do **not** contain public media, private support
attachments, Redis data or the MFA encryption key; back these up separately.
Ensure backup retention and off-site restore permissions are defined.

## Destructive restore DRILL (staging only)

Isolate the staging environment, stop web/worker/beat, provide a fresh
empty or disposable staging DB and an authorized backup path:

```sh
export BACKUP_FILE=/secure/mallbyte-staging-backups/your-file.dump
export CONFIRM_STAGING_RESTORE=RESTORE_mallbyte_staging
export STAGING_SERVICES_STOPPED=YES
bash ops/postgres-restore-staging.sh
```

After restoration, verify migrations, row counts, OTP/MFA decryptability
(using the original encryption key), media references, order integrity,
worker schedules and internal error logs. Record measured RPO/RTO and
perform a negative test proving production restore targets are refused.

## Launch gates

- CI green, migrations and `check --deploy` clean
- Both browser-mock tests and real staging integration tests passed
- No production-grade secret in repository, no placeholder credentials
- MFA enrollment and recovery tested on fresh staging accounts
- No externally accessible Django admin with password-only authentication
- Rate limiting, privilege/ownership and session expiry tested
- Postgres, Redis, worker, beat and media health monitored
- Real backup and restore drill recorded
- TLS, webhook signatures, payment sandbox/production cutover reviewed
- Load test meets agreed latency/error thresholds
- Operator-approved rollback and incident response documented

Never run the destructive restore against production. Do not claim
production readiness from Docker build or GitHub Actions alone.

## Production runtime hardening

- Docker liveness probes on `/healthz/` are intentionally exempt from HTTP-to-HTTPS redirects; all other routes remain HTTPS-only.
- PostgreSQL requires TLS by default (`DB_SSLMODE=require`); prefer `verify-full` with your provider's CA file and hostname validation. Do not use `disable` or `prefer` in production.
- Django's static root is `/app/static`. The separate **internal, loopback-only** Nginx gateway listens at `127.0.0.1:8080` and mounts **only** public media and collected static files read-only; private support attachments are never mounted into the gateway.
- The operator's public TLS reverse proxy should forward HTTPS requests to port 8080 (not to the Django development port), must overwrite `X-Forwarded-Proto=https`, and must restrict the origin to trusted traffic. Never forward client-controlled proxy headers unchanged.
- Both `/healthz/` (Django app) and `/gateway-healthz` (gateway process) are intentionally non-sensitive *liveness* responses. Neither checks PostgreSQL/Redis readiness.
- Public media is available under `/media/`; static assets under `/static/`. In production, remember `python manage.py collectstatic --noinput` with the shared static volume mounted before deploying. The web/gateway share named volumes within their own Compose project.
- Private attachments must always be served via authenticated Django API endpoints, never via `/media/` or a public static mount.
- Protect public upload types and size limits separately; the gateway denies direct requests under `/private_media/`.

**Do not deploy a new gateway if the existing reverse-proxy routing is not updated at the same time.** Existing loopback port 8000 is retained for application debugging; production traffic should use the internal gateway at 8080 via TLS termination.
