#!/bin/sh

set -e

if [ -n "$DB_HOST" ] && [ -n "$DB_PORT" ]; then
  echo "Waiting for PostgreSQL at $DB_HOST:$DB_PORT..."

  while ! nc -z "$DB_HOST" "$DB_PORT"; do
    sleep 1
  done

  echo "PostgreSQL is ready."
fi

exec "$@"
