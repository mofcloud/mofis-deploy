#!/bin/sh
set -eu
cd "$(dirname "$0")"
[ -f .env ] || { echo 'Run ./configure.sh first'; exit 1; }
mode=$(sed -n 's/^DEPLOY_MODE=//p' .env)
set -- "${1:-help}"
command=$1
compose() {
 if [ "$mode" = full ]; then docker compose -f compose.yaml -f compose.postgres.yaml "$@"
 elif [ "$mode" = external ]; then docker compose -f compose.yaml "$@"
 else echo 'Invalid deployment mode' >&2; return 1; fi
}
preflight() {
  # Test the real backend credentials before waiting for the pooler health check.
  if [ "$mode" = full ]; then
    compose up -d --wait --wait-timeout 60 postgres || return 1
  fi
  diagnostic=$(mktemp)
  if compose run --rm --no-deps --entrypoint sh pgbouncer -c '
    export PGCONNECT_TIMEOUT=8
    export PGPASSWORD="$(cat /run/secrets/db_password)"
    export PGSSLMODE="${DB_TLS_MODE:-disable}"
    export PGSSLROOTCERT=/config/db-ca.crt
    psql -h "${DB_HOST:-postgres}" -p "${DB_PORT:-5432}" -U "${DB_USER:-mof}" -d "${DB_NAME:-mof}" -Atqc "SELECT 1"
  ' >"$diagnostic" 2>&1; then
    rm -f "$diagnostic"
    return 0
  fi
  if grep -qi 'password authentication failed' "$diagnostic"; then
    printf '\n  Database password does not match the saved configuration.\n' >&2
    if [ "$mode" = full ]; then
      printf '  Existing data is preserved. Import the original password with:\n\n    ./manage.sh repair\n\n' >&2
    else
      printf '  Update config/db-password with the current external database password.\n' >&2
    fi
  else
    printf '\n  Cannot connect to PostgreSQL. Check the address, permissions and TLS settings.\n' >&2
    tail -n 15 "$diagnostic" >&2
  fi
  rm -f "$diagnostic"
  return 1
}
start() { preflight && compose up -d --wait --wait-timeout 180; }
case "$command" in
 start) start;;
 repair) ./scripts/repair.sh && preflight && compose up -d --no-deps --force-recreate pgbouncer && start;;
 stop) compose stop;;
 restart) compose restart;;
 status) compose ps;;
 logs) compose logs --tail=100;;
 fingerprint) compose exec -T ssh ssh-keygen -lf /etc/ssh/host_keys/ssh_host_ed25519_key.pub;;
 *) echo 'Usage: ./manage.sh start|stop|restart|status|logs|fingerprint|repair'; exit 1;;
esac
