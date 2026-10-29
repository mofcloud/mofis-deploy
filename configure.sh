#!/bin/sh
set -eu
cd "$(dirname "$0")"
[ ! -e .env ] && [ ! -e config ] || { echo 'Configuration already exists; not overwriting.' >&2; exit 1; }
command -v openssl >/dev/null || { echo 'Install openssl first.' >&2; exit 1; }
ask() { printf '%s' "$1" >&2; IFS= read -r answer || exit 1; }
ask 'Deployment: 1) New PostgreSQL (default)  2) Existing PostgreSQL: '
case "$answer" in ''|1) mode=full;; 2) mode=external;; *) echo 'Choose 1 or 2'; exit 1;; esac
ask 'SSH authentication: 1) Public key (default)  2) Generated password: '
case "$answer" in ''|1) auth=key;; 2) auth=password;; *) echo 'Choose 1 or 2'; exit 1;; esac
key=''
if [ "$auth" = key ]; then
  ask 'Paste your computer OpenSSH PUBLIC key (one line): '; key=$answer
  printf '%s\n' "$key" | grep -Eq '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-[^ ]+) [A-Za-z0-9+/=]+( .*)?$' || { echo 'Expected a public key, never a private key.'; exit 1; }
  command -v ssh-keygen >/dev/null || { echo 'Install openssh-clients first.'; exit 1; }
fi
ask 'Server address to enter in MOFIS (IP or hostname): '; server=$answer
case "$server" in ''|*[!A-Za-z0-9.:-]*) echo 'Invalid server address'; exit 1;; esac
host=postgres; port=5432; db=mof; user=mof; tls=disable; ca=''
if [ "$mode" = external ]; then
 ask 'Existing PostgreSQL hostname: '; host=$answer
 ask 'PostgreSQL port [5432]: '; port=${answer:-5432}
 ask 'Existing dedicated database name [mof]: '; db=${answer:-mof}
 ask 'Database owner username [mof]: '; user=${answer:-mof}
 case "$host:$db:$user" in *[!A-Za-z0-9_.:-]*) echo 'Use hostname and simple database/user identifiers'; exit 1;; esac
 [ -n "$host" ] || exit 1
 case "$port" in ''|*[!0-9]*) exit 1;; esac
 [ "$port" -ge 1 ] && [ "$port" -le 65535 ] || exit 1
 ask 'Database TLS: 1) Verify certificate (default)  2) Encrypt only  3) Disable (private network only): '
 case "$answer" in ''|1) tls=verify-full; ask 'Database CA certificate file path: '; ca=$answer; [ -s "$ca" ] || exit 1;; 2) tls=require;; 3) tls=disable;; *) exit 1;; esac
 printf 'Database password (hidden): ' >&2
 saved_tty=$(stty -g); trap 'stty "$saved_tty"' EXIT HUP INT TERM
 stty -echo
 IFS= read -r backend_password || exit 1
 stty "$saved_tty"; trap - EXIT HUP INT TERM; printf '\n' >&2
 [ -n "$backend_password" ] || exit 1
else
 backend_password=$(openssl rand -hex 32)
fi
umask 077
mkdir config
# Validate actual key structure, not only its prefix.
if [ "$auth" = key ]; then
 printf '%s\n' "$key" > config/authorized_keys
 ssh-keygen -lf config/authorized_keys >/dev/null || { rm -rf config; exit 1; }
fi
printf '%s' "$backend_password" > config/db-password
openssl rand -hex 32 | tr -d '\n' > config/client-password
openssl rand -hex 24 | tr -d '\n' > config/ssh-password
openssl rand -hex 32 | tr -d '\n' > config/postgres-password
# PostgreSQL runs as a non-root container user. The host directory stays 0700.
chmod 644 config/db-password config/postgres-password
[ -z "$ca" ] || cp "$ca" config/db-ca.crt
{
 printf 'MOFIS_DEPLOY_VERSION=%s\n' "$(cat VERSION)"
 printf 'DEPLOY_MODE=%s\nSSH_AUTH_MODE=%s\n' "$mode" "$auth"
 printf 'SSH_BIND_ADDRESS=0.0.0.0\nSSH_PORT=2222\n'
 printf 'DB_HOST=%s\nDB_PORT=%s\nDB_NAME=%s\nDB_USER=%s\nDB_TLS_MODE=%s\n' "$host" "$port" "$db" "$user" "$tls"
} > .env
{
 printf 'MOFIS: Add team shared database / SSH tunnel\n'
 printf 'PostgreSQL URI: postgresql://mof:%s@pgbouncer:6432/mof?sslmode=disable\n' "$(cat config/client-password)"
 printf 'SSH host: %s\nSSH port: 2222\nSSH user: tunnel\nAuthentication: %s\n' "$server" "$auth"
 if [ "$auth" = password ]; then printf 'SSH password: %s\n' "$(cat config/ssh-password)"; else printf 'Select your matching private key or SSH Agent in MOFIS.\n'; fi
 printf 'Verify SSH fingerprint with: ./manage.sh fingerprint\n'
} > connection.txt
echo 'Configured. Run ./manage.sh start; then open connection.txt locally for MOFIS settings.'
