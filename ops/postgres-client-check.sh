#!/usr/bin/env bash
# Source after PGHOST/PGPORT/PGUSER/PGDATABASE/PGPASSWORD have been set.
require_matching_postgres_clients() {
  command -v psql >/dev/null || { echo "psql required for compatibility preflight" >&2; return 2; }
  local server_version server_major client output client_major
  server_version="$(psql -X -A -t -v ON_ERROR_STOP=1 -c 'SHOW server_version_num')" || {
    echo "Could not verify PostgreSQL server version" >&2; return 2;
  }
  if [[ ! "$server_version" =~ ^[0-9]+$ ]]; then
    echo "Invalid PostgreSQL server version" >&2; return 2
  fi
  server_major=$((server_version / 10000))
  for client in pg_dump pg_restore; do
    output="$("$client" --version)" || return 2
    if [[ ! "$output" =~ PostgreSQL\)\ ([0-9]+)\. ]]; then
      echo "Could not determine $client major version" >&2; return 2
    fi
    client_major="${BASH_REMATCH[1]}"
    if [[ "$client_major" != "$server_major" ]]; then
      echo "$client major $client_major must match PostgreSQL server major $server_major; use matching client tools before backup/restore" >&2
      return 2
    fi
  done
}
