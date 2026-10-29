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
case "$command" in
 start) compose up -d --wait --wait-timeout 180;;
 stop) compose stop;;
 restart) compose restart;;
 status) compose ps;;
 logs) compose logs --tail=100;;
 fingerprint) compose exec -T ssh ssh-keygen -lf /etc/ssh/host_keys/ssh_host_ed25519_key.pub;;
 *) echo 'Usage: ./manage.sh start|stop|restart|status|logs|fingerprint'; exit 1;;
esac
