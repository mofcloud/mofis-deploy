#!/bin/sh
set -eu
cd "$(dirname "$0")"
[ -f .env ] || { echo 'Run ./configure.sh first'; exit 1; }
mode=$(sed -n 's/^DEPLOY_MODE=//p' .env)
command=${1:-help}
[ "$#" -eq 0 ] || shift
compose() {
 if [ "$mode" = full ]; then docker compose -f compose.yaml -f compose.postgres.yaml "$@"
 elif [ "$mode" = external ]; then docker compose -f compose.yaml "$@"
 else echo 'Invalid deployment mode' >&2; return 1; fi
}
prepare_images() {
  printf '\n  [1/4] Checking required Docker images\n' >&2
  required_images=$(compose config --images) || return 1
  for image in $required_images; do
    if docker image inspect "$image" >/dev/null 2>&1; then
      printf '  Ready: %s\n' "$image" >&2
    else
      printf '  Downloading %s (progress below; network access required)\n' "$image" >&2
      if ! docker pull "$image"; then
        printf '\n  Image download failed: %s\n  Check server access to the image registry, then run ./manage.sh start again.\n' "$image" >&2
        return 1
      fi
    fi
  done
}
preflight() {
  # Test the real backend credentials before waiting for the pooler health check.
  if [ "$mode" = full ]; then
    printf '\n  [2/4] Starting PostgreSQL (waiting up to 60 seconds for readiness)\n' >&2
    compose up -d --wait --wait-timeout 60 postgres || return 1
    if [ -f config/reset-db-password ]; then
      printf '  Recovering database access; stored data is preserved.\n' >&2
      # Only our managed PG supports this recovery. Use its local admin socket;
      # never change authentication rules or expose a password in process arguments.
      recovery_password=$(cat config/db-password)
      case "$recovery_password" in *[!0-9a-f]*|'') echo 'Invalid recovery password.' >&2; return 1;; esac
      if ! printf "\\\\set recovery_password '%s'\nSELECT format('ALTER ROLE mof PASSWORD %%L', :'recovery_password') \\\\gexec\n" "$recovery_password" |
        compose exec -T -u postgres postgres psql -X -U postgres -d postgres -v ON_ERROR_STOP=1 >/dev/null; then
        printf '  Recovery failed. No data was deleted; check local PostgreSQL administrator access.\n' >&2
        return 1
      fi
      unset recovery_password
      rm -f config/reset-db-password
      printf '  Database password updated. Other clients using the old password must update their connection.\n' >&2
    fi
  else
    printf '\n  [2/4] Using the configured external PostgreSQL server\n' >&2
  fi
  printf '\n  [3/4] Verifying PostgreSQL access (connection timeout: 8 seconds)\n' >&2
  diagnostic=$(mktemp)
  if compose run --rm --no-deps --pull never --entrypoint sh pgbouncer -c '
    export PGCONNECT_TIMEOUT=8
    export PGPASSWORD="$(cat /run/secrets/db_password)"
    export PGSSLMODE="${DB_TLS_MODE:-disable}"
    export PGSSLROOTCERT=/config/db-ca.crt
    psql -h "${DB_HOST:-postgres}" -p "${DB_PORT:-5432}" -U "${DB_USER:-mof}" -d "${DB_NAME:-mof}" -Atqc "SELECT 1"
  ' >"$diagnostic" 2>&1; then
    rm -f "$diagnostic"
    printf '  PostgreSQL connection verified.\n' >&2
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
start_services() {
  printf '\n  [4/4] Starting PgBouncer and SSH (waiting up to 180 seconds for readiness)\n' >&2
  if ! compose up -d --wait --wait-timeout 180; then
    printf '\n  Services are not ready. View details with ./manage.sh status and ./manage.sh logs.\n' >&2
    return 1
  fi
  printf '\n  Ready. View MOFIS connection details with: cat connection.txt\n' >&2
}
start() { prepare_images && preflight && start_services; }
case "$command" in
 upgrade)
   command -v python3 >/dev/null || { echo 'Upgrade requires Python 3. Install python3 and try again.' >&2; exit 1; }
   exec python3 ./scripts/upgrade.py --directory "$PWD" "$@";;
 start) start;;
 repair) ./scripts/repair.sh && prepare_images && preflight && compose up -d --no-deps --force-recreate pgbouncer && start_services;;
 stop) compose stop;;
 restart) compose restart;;
 status) compose ps;;
 logs) compose logs --tail=100;;
 fingerprint) compose exec -T ssh ssh-keygen -lf /etc/ssh/host_keys/ssh_host_ed25519_key.pub;;
 *) echo 'Usage: ./manage.sh start|stop|restart|status|logs|fingerprint|repair|upgrade [version]'; exit 1;;
esac
