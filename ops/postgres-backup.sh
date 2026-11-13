#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

# Execute on an operator host with PostgreSQL client tools and an isolated
# credential environment. Requires DB_HOST, DB_PORT, DB_USER, DB_PASSWORD,
# DB_NAME and BACKUP_DIR. Do not put secrets in CLI arguments or Git.
for name in DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME BACKUP_DIR; do
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required environment variable: $name" >&2
    exit 2
  fi
done

command -v pg_dump >/dev/null || { echo "pg_dump required" >&2; exit 2; }
command -v pg_restore >/dev/null || { echo "pg_restore required" >&2; exit 2; }
if [[ "$DB_NAME" != *staging* && "${ALLOW_PRODUCTION_BACKUP:-}" != "YES" ]]; then
  echo "Non-staging backups require ALLOW_PRODUCTION_BACKUP=YES" >&2
  exit 2
fi
export PGHOST="$DB_HOST" PGPORT="$DB_PORT" PGUSER="$DB_USER" PGDATABASE="$DB_NAME" PGPASSWORD="$DB_PASSWORD"
source "$(dirname -- "${BASH_SOURCE[0]}")/postgres-client-check.sh"
require_matching_postgres_clients
if [[ -L "$BACKUP_DIR" ]]; then
  echo "Refusing symlinked backup directory" >&2
  exit 2
fi
mkdir -p -- "$BACKUP_DIR"
chmod 700 -- "$BACKUP_DIR"
BACKUP_DIR="$(cd -- "$BACKUP_DIR" && pwd -P)"
target="$BACKUP_DIR/${DB_NAME}-$(date -u +%Y%m%dT%H%M%SZ)-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n').dump"
tmp="${target}.partial"
trap 'rm -f -- "$tmp"' EXIT
pg_dump --format=custom --no-owner --no-acl --file="$tmp"
pg_restore --list "$tmp" >/dev/null
chmod 600 -- "$tmp"
mv -- "$tmp" "$target"
if command -v sha256sum >/dev/null; then
  sha256sum "$target" > "${target}.sha256"
  chmod 600 -- "${target}.sha256"
fi
trap - EXIT
echo "Backup created: $target"
echo "Store backup and checksum in encrypted off-site storage with limited access."
