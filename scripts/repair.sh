#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
. ./scripts/config-common.sh
[ "$(env_value . DEPLOY_MODE)" = full ] || { echo 'For an external database, update config/db-password with its current password.' >&2; exit 1; }
[ -f config/db-password ] || { echo 'Run configure.sh first.' >&2; exit 1; }
project=$(env_value . COMPOSE_PROJECT_NAME)
project=${project:-mofis-shared-db}
printf '\n  Repair database connection\n  1  Import the original password (default)\n  2  Forgot password: generate a new password; preserve stored data\n     Other clients using the old password must update their connection.\n\n'
while :; do
  printf '  › Repair [1]: '
  IFS= read -r repair_choice
  case "${repair_choice:-1}" in
    1) import_old_password; break;;
    2) backend_password=$(openssl rand -hex 32); touch config/reset-db-password; break;;
    *) printf '  Please enter 1 or 2.\n';;
  esac
done
# Keep the inode: Compose secrets may already be bind-mounted in running containers.
printf '%s' "$backend_password" > config/db-password
chmod 644 config/db-password
printf '\n  Saved backend credentials. MOFIS connection details are unchanged.\n'
