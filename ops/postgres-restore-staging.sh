#!/usr/bin/env bash
set -Eeuo pipefail

# Destructive restore. Staging-only by design. Never target a production DB.
for name in DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME BACKUP_FILE; do
  if [[ -z "${!name:-}" ]]; then echo "Missing: $name" >&2; exit 2; fi
done
if [[ "$DB_NAME" != *staging* ]]; then
  echo "Refusing restore: DB_NAME must contain staging" >&2; exit 2
fi
if [[ "${CONFIRM_STAGING_RESTORE:-}" != "RESTORE_$DB_NAME" ]]; then
  echo "Set CONFIRM_STAGING_RESTORE=RESTORE_$DB_NAME to confirm destructive staging restore" >&2
  exit 2
fi
if [[ ! -f "$BACKUP_FILE" || -L "$BACKUP_FILE" ]]; then
  echo "Regular backup file required; symlinks rejected" >&2; exit 2
fi
command -v pg_restore >/dev/null || { echo "pg_restore required" >&2; exit 2; }
export PGHOST="$DB_HOST" PGPORT="$DB_PORT" PGUSER="$DB_USER" PGDATABASE="$DB_NAME" PGPASSWORD="$DB_PASSWORD"
source "$(dirname -- "${BASH_SOURCE[0]}")/postgres-client-check.sh"
require_matching_postgres_clients
pg_restore --list "$BACKUP_FILE" >/dev/null
if [[ -f "${BACKUP_FILE}.sha256" ]]; then
  command -v sha256sum >/dev/null || { echo "sha256sum required" >&2; exit 2; }
  (cd "$(dirname "$BACKUP_FILE")" && sha256sum -c "$(basename "$BACKUP_FILE").sha256")
fi
echo "Restore target: DB_NAME=$DB_NAME DB_HOST=$DB_HOST"
echo "Ensure ALL staging web/workers/beat processes are stopped before continuing."
if [[ "${STAGING_SERVICES_STOPPED:-}" != "YES" ]]; then
  echo "Set STAGING_SERVICES_STOPPED=YES after stopping all staging services" >&2
  exit 2
fi
pg_restore --exit-on-error --clean --if-exists --no-owner --no-acl --dbname="$DB_NAME" "$BACKUP_FILE"
echo "Restore completed; run Django migrate and staging smoke checks before starting services."
