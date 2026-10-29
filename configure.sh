#!/bin/sh
set -eu
cd "$(dirname "$0")"
[ ! -e .env ] && [ ! -e config ] || { echo 'Configuration already exists; not overwriting.' >&2; exit 1; }
command -v openssl >/dev/null || { echo 'Install openssl first.' >&2; exit 1; }
# Keep plain text readable in logs, and add restrained color on interactive terminals.
accent=''; bold=''; muted=''; reset=''
if [ -t 2 ] && [ "${TERM:-dumb}" != dumb ] && [ -z "${NO_COLOR:-}" ]; then
  accent=$(printf '\033[36m'); bold=$(printf '\033[1m')
  muted=$(printf '\033[2m'); reset=$(printf '\033[0m')
fi
section() { printf '\n  %s%s%s\n' "$bold" "$1" "$reset" >&2; }
ask() { printf '  %s›%s %s' "$accent" "$reset" "$1" >&2; IFS= read -r answer || exit 1; }
choose() {
  while :; do
    ask "$1"
    answer=${answer:-1}
    case "$answer" in 1|2) return;; 3) [ "$2" = 3 ] && return;; esac
    printf '  Please enter a number from 1 to %s.\n' "$2" >&2
  done
}
printf '\n  %sMOFIS%s  %sShared database setup%s\n' "$bold" "$reset" "$muted" "$reset" >&2
printf '  Choose your setup. Press Enter to use the default.\n' >&2
section '1 / 3  Deployment'
printf '  %s1%s  New PostgreSQL  %s(default)%s\n' "$accent" "$reset" "$muted" "$reset" >&2
printf '     PostgreSQL + PgBouncer + SSH\n' >&2
printf '  %s2%s  Existing PostgreSQL\n' "$accent" "$reset" >&2
printf '     PgBouncer + SSH, connected to your database\n\n' >&2
choose 'Deployment [1]: ' 2
case "$answer" in 1) mode=full;; 2) mode=external;; esac
section '2 / 3  SSH authentication'
printf '  %s1%s  Public key  %s(default)%s\n' "$accent" "$reset" "$muted" "$reset" >&2
printf '     Use a private key or SSH Agent in MOFIS\n' >&2
printf '  %s2%s  Generated password\n' "$accent" "$reset" >&2
printf '     A random password will be saved in connection.txt\n\n' >&2
choose 'Authentication [1]: ' 2
case "$answer" in 1) auth=key;; 2) auth=password;; esac
key=''
if [ "$auth" = key ]; then
  ask 'Paste your computer OpenSSH PUBLIC key (one line): '; key=$answer
  printf '%s\n' "$key" | grep -Eq '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-[^ ]+) [A-Za-z0-9+/=]+( .*)?$' || { echo 'Expected a public key, never a private key.'; exit 1; }
  command -v ssh-keygen >/dev/null || { echo 'Install openssh-clients first.'; exit 1; }
fi
section '3 / 3  Connection details'
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
 section 'Database encryption'
 printf '  1  Verify certificate (default)\n  2  Encrypt only\n  3  Disable (private network only)\n\n' >&2
 choose 'Database TLS [1]: ' 3
 case "$answer" in ''|1) tls=verify-full; ask 'Database CA certificate file path: '; ca=$answer; [ -s "$ca" ] || exit 1;; 2) tls=require;; 3) tls=disable;; *) exit 1;; esac
 printf '  › Database password (hidden): ' >&2
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
section 'Configuration ready'
case "$mode" in full) deployment='PostgreSQL + PgBouncer + SSH';; external) deployment='PgBouncer + SSH (existing database)';; esac
printf '  Deployment      %s\n  Authentication  %s\n  SSH endpoint    %s:2222\n' "$deployment" "$auth" "$server" >&2
printf '\n  %sNext steps%s\n' "$bold" "$reset" >&2
printf '  1. Start services    ./manage.sh start\n  2. View connection   cat connection.txt\n  3. Check status      ./manage.sh status\n\n' >&2
printf '  Keep connection.txt private; it contains your credentials.\n\n' >&2
