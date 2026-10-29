#!/bin/sh
set -eu
# PgBouncer uses doubled single quotes (not libpq backslash escaping).
quote() { printf '%s' "$1" | sed "s/'/''/g"; }
read_secret() { cat "/run/secrets/$1"; }
client_password=$(read_secret client_password)
backend_password=$(read_secret db_password)
case "$client_password" in ''|*[!0-9a-f]*) echo 'Invalid generated client password' >&2; exit 1;; esac
for value in "$backend_password" "${DB_HOST:-postgres}" "${DB_NAME:-mof}" "${DB_USER:-mof}"; do
  case "$value" in *'
'*|*'
'*) echo 'Newlines are not supported in database settings' >&2; exit 1;; esac
done
case "${DB_PORT:-5432}" in ''|*[!0-9]*) exit 1;; esac
case "${DB_TLS_MODE:-disable}" in disable|require|verify-full) ;; *) echo 'Unsupported TLS mode' >&2; exit 1;; esac
umask 077
mkdir -p /run/pgbouncer
printf '"mof" "%s"\n' "$client_password" > /run/pgbouncer/userlist.txt
cat > /run/pgbouncer/pgbouncer.ini <<EOF
[databases]
mof = host='$(quote "${DB_HOST:-postgres}")' port=${DB_PORT:-5432} dbname='$(quote "${DB_NAME:-mof}")' user='$(quote "${DB_USER:-mof}")' password='$(quote "$backend_password")'
[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
unix_socket_dir = /run/pgbouncer
pidfile = /run/pgbouncer/pgbouncer.pid
auth_type = scram-sha-256
auth_file = /run/pgbouncer/userlist.txt
pool_mode = session
max_client_conn = 100
default_pool_size = 20
max_db_connections = 40
server_reset_query = DISCARD ALL
server_connect_timeout = 10
client_login_timeout = 30
client_tls_sslmode = disable
server_tls_sslmode = ${DB_TLS_MODE:-disable}
EOF
if [ "${DB_TLS_MODE:-disable}" = verify-full ]; then
  [ -s /config/db-ca.crt ] || { echo 'Missing database CA certificate' >&2; exit 1; }
  cp /config/db-ca.crt /run/pgbouncer/db-ca.crt
  echo 'server_tls_ca_file = /run/pgbouncer/db-ca.crt' >> /run/pgbouncer/pgbouncer.ini
fi
unset client_password backend_password
chown -R pooler:pooler /run/pgbouncer
exec su-exec pooler pgbouncer /run/pgbouncer/pgbouncer.ini
