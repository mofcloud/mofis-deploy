#!/bin/sh
set -eu
mkdir -p /etc/ssh/host_keys /home/tunnel/.ssh /run/sshd
if [ ! -s /etc/ssh/host_keys/ssh_host_ed25519_key ]; then
  ssh-keygen -q -t ed25519 -N '' -f /etc/ssh/host_keys/ssh_host_ed25519_key
fi
case "${SSH_AUTH_MODE:-key}" in
 key)
  [ -s /config/authorized_keys ] || { echo 'Missing SSH public key' >&2; exit 1; }
  cp /config/authorized_keys /home/tunnel/.ssh/authorized_keys
  password=$(head -c 48 /dev/urandom | base64 | tr -d '\n')
  auth='PasswordAuthentication=no'
  pubkey='PubkeyAuthentication=yes'
  ;;
 password)
  password=$(cat /run/secrets/ssh_password)
  [ "${#password}" -ge 20 ] || { echo 'SSH password must be at least 20 characters' >&2; exit 1; }
  auth='PasswordAuthentication=yes'
  pubkey='PubkeyAuthentication=no'
  rm -f /home/tunnel/.ssh/authorized_keys
  ;;
 *) echo 'Unsupported SSH authentication mode' >&2; exit 1;;
esac
printf 'tunnel:%s\n' "$password" | chpasswd
unset password
chmod 700 /home/tunnel/.ssh
[ ! -e /home/tunnel/.ssh/authorized_keys ] || chmod 600 /home/tunnel/.ssh/authorized_keys
chown -R tunnel:tunnel /home/tunnel/.ssh
/usr/sbin/sshd -t -o "$auth" -o "$pubkey"
echo 'SSH host fingerprint (compare with MOFIS):'
ssh-keygen -lf /etc/ssh/host_keys/ssh_host_ed25519_key.pub
exec /usr/sbin/sshd -D -e -o "$auth" -o "$pubkey"
