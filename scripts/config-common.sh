#!/bin/sh
# Read only known values. Never source an old .env as executable shell code.
env_value() {
  [ -f "$1/.env" ] || return 0
  awk -v key="$2" 'index($0,key "=")==1 {print substr($0,length(key)+2); exit}' "$1/.env"
}
old_password() {
  if [ -s "$1/config/db-password" ]; then cat "$1/config/db-password"
  else env_value "$1" MOF_DB_PASSWORD; fi
}
old_directory() {
  docker ps -a --filter "label=com.docker.compose.project=${project:-mofis-shared-db}" \
    --format '{{.Label "com.docker.compose.project.working_dir"}}' 2>/dev/null | sed -n '1p'
}
hidden_password() {
  [ -t 0 ] || { echo 'Please run this command in an interactive terminal.' >&2; return 1; }
  printf '  › Original database password (hidden): ' >&2
  saved_tty=$(stty -g)
  trap 'stty "$saved_tty"' EXIT
  trap 'stty "$saved_tty"; exit 130' HUP INT TERM
  stty -echo
  IFS= read -r backend_password || { stty "$saved_tty"; return 1; }
  stty "$saved_tty"; trap - EXIT HUP INT TERM; printf '\n' >&2
  [ -n "$backend_password" ] || { echo 'Password must not be empty.' >&2; return 1; }
}
import_old_password() {
  hint=$(old_directory)
  [ "$hint" != "$(pwd)" ] || hint=''
  printf '  Use the directory that originally initialized this database.\n' >&2
  if [ -n "$hint" ]; then
    printf '  › Old deployment directory [%s]: ' "$hint" >&2
  else
    printf '  › Old deployment directory (or Enter to type the original password): ' >&2
  fi
  IFS= read -r old_dir || return 1
  old_dir=${old_dir:-$hint}
  backend_password=''
  imported_client_password=''
  if [ -n "$old_dir" ] && [ -d "$old_dir" ]; then
    backend_password=$(old_password "$old_dir")
    if [ -s "$old_dir/config/client-password" ]; then
      imported_client_password=$(cat "$old_dir/config/client-password")
    else
      imported_client_password=$backend_password
    fi
  fi
  if [ -z "$backend_password" ]; then
    printf '  No saved password found. Use the original database password.\n' >&2
    hidden_password
  else
    printf '  Original database credentials imported (not displayed).\n' >&2
  fi
  case "$imported_client_password" in *[!0-9a-f]*|'') imported_client_password='';; esac
}
