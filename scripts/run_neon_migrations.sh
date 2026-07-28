#!/usr/bin/env bash

# Do not enable `set -e`: three failed migrations intentionally enter degraded mode.
set -uo pipefail

migration_success=false
migration_output="$(mktemp)"
chmod 600 "${migration_output}"
trap 'rm -f "${migration_output}"' EXIT

is_connection_failure() {
  grep -Eqi \
    'sqlstate[^[:alnum:]]*08|could not connect|connection (refused|reset|closed|timed out)|connect timeout|network is unreachable|failed to resolve host|could not translate host|name or service not known|server is not accepting|ssl.*connection' \
    "$1"
}

for attempt in 1 2 3; do
  echo "Running database migration attempt ${attempt}/3..."

  # Migration stderr may contain driver details. Keep workflow logs secret-safe.
  if alembic upgrade head >"${migration_output}" 2>&1; then
    echo "Database migration attempt ${attempt} succeeded."
    migration_success=true
    break
  fi

  if ! is_connection_failure "${migration_output}"; then
    echo "::error::Database migration failed with a non-connection error. Pipeline stopped."
    exit 1
  fi

  echo "Database migration attempt ${attempt} failed."
  if [[ "${attempt}" -lt 3 ]]; then
    sleep_seconds=$((attempt * 10))
    echo "Retrying in ${sleep_seconds} seconds..."
    sleep "${sleep_seconds}"
  fi
done

if [[ "${migration_success}" == "true" ]]; then
  echo "DATABASE_AVAILABLE=true" >> "${GITHUB_ENV:?GITHUB_ENV must be set}"
  echo "GARMIN_ACTIVITY_LIMIT=75" >> "${GITHUB_ENV:?GITHUB_ENV must be set}"
else
  echo "::warning::Neon database unavailable after 3 attempts. Continuing in degraded mode."
  echo "DATABASE_AVAILABLE=false" >> "${GITHUB_ENV:?GITHUB_ENV must be set}"
  echo "GARMIN_ACTIVITY_LIMIT=10" >> "${GITHUB_ENV:?GITHUB_ENV must be set}"
fi
