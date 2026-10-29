#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
. ./scripts/config-common.sh
[ "$(env_value . DEPLOY_MODE)" = full ] || { echo 'For an external database, update config/db-password with its current password.' >&2; exit 1; }
[ -f config/db-password ] || { echo 'Run configure.sh first.' >&2; exit 1; }
project=$(env_value . COMPOSE_PROJECT_NAME)
project=${project:-mofis-shared-db}
printf '\n  Repair database connection\n  Import the original password; database contents and role passwords are not changed.\n\n'
import_old_password
# Keep the inode: Compose secrets may already be bind-mounted in running containers.
printf '%s' "$backend_password" > config/db-password
chmod 644 config/db-password
printf '\n  Saved the original backend password. MOFIS connection details are unchanged.\n'
