#!/usr/bin/env bash
# Turn a fresh Ubuntu 24.04 server into a machine that can run KnoRI.
#
#   ssh root@<server>
#   curl -fsSLO https://raw.githubusercontent.com/<org>/knori/main/deploy/scripts/provision_vps.sh
#   bash provision_vps.sh
#
# Safe to run again. Every step checks first and only acts when something is actually
# missing, and the script prints a list at the end of what it changed. Running it twice
# in a row should print "nothing to change" the second time.
#
# It installs: Docker Engine + Compose, a firewall (22/80/443 only), fail2ban,
# automatic security updates, a `deploy` user, /srv/knori, and swap if the box has less
# than 8 GB of RAM.
#
# It does NOT install KnoRI itself. See deploy/README.md for the steps after this one.
#
# Options (environment variables):
#   DEPLOY_USER=deploy        the unprivileged user that runs the stack
#   DEPLOY_SSH_KEY="ssh-ed25519 AAAA..."   public key to install for that user
#   APP_DIR=/srv/knori        where the checkout lives
#   SWAP_SIZE=4G              swap file size, created only when RAM < 8 GB
#   HARDEN_SSH=true           turn off password logins (skipped if no key is installed)
set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-deploy}"
APP_DIR="${APP_DIR:-/srv/knori}"
SWAP_SIZE="${SWAP_SIZE:-4G}"
SWAP_FILE="${SWAP_FILE:-/swapfile}"
HARDEN_SSH="${HARDEN_SSH:-true}"
RAM_THRESHOLD_KB=$(( 8 * 1024 * 1024 ))

export DEBIAN_FRONTEND=noninteractive

CHANGES=()
changed() { CHANGES+=("$1"); printf '  [changed] %s\n' "$1"; }
already() { printf '  [ok]      %s\n' "$1"; }
step()    { printf '\n== %s\n' "$1"; }
warn()    { printf '  [warn]    %s\n' "$1" >&2; }

[ "$(id -u)" -eq 0 ] || { echo "Run this as root: sudo bash $0" >&2; exit 1; }

if [ -r /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  if [ "${ID:-}" != "ubuntu" ] || [ "${VERSION_ID:-}" != "24.04" ]; then
    warn "this script was written for Ubuntu 24.04, found ${PRETTY_NAME:-unknown}; continuing"
  fi
fi

# --------------------------------------------------------------------- base packages

step "Base packages"
BASE_PACKAGES=(ca-certificates curl gnupg jq ufw fail2ban unattended-upgrades age rsync)
MISSING=()
for package in "${BASE_PACKAGES[@]}"; do
  dpkg -s "$package" >/dev/null 2>&1 || MISSING+=("$package")
done
if [ "${#MISSING[@]}" -gt 0 ]; then
  apt-get update -qq
  apt-get install -y -qq "${MISSING[@]}"
  changed "installed ${MISSING[*]}"
else
  already "base packages present"
fi

# --------------------------------------------------------------------- docker engine

step "Docker Engine"
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  already "docker $(docker --version | awk '{print $3}' | tr -d ,) with the compose plugin"
else
  install -m 0755 -d /etc/apt/keyrings
  if [ ! -s /etc/apt/keyrings/docker.asc ]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    changed "added Docker's package signing key"
  fi
  codename="$(. /etc/os-release && echo "${VERSION_CODENAME}")"
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${codename} stable" \
    >/etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker >/dev/null
  changed "installed Docker Engine and the compose plugin"
fi

# Container logs are the only logs we keep, so they must not fill the disk (plan.md §9).
step "Docker log rotation"
if [ -s /etc/docker/daemon.json ] && grep -q '"max-size"' /etc/docker/daemon.json; then
  already "json-file log rotation configured"
else
  mkdir -p /etc/docker
  cat >/etc/docker/daemon.json <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "5" }
}
JSON
  systemctl restart docker
  changed "set container logs to rotate at 50 MB x 5"
fi

# ----------------------------------------------------------------------- deploy user

step "Deploy user"
if id -u "$DEPLOY_USER" >/dev/null 2>&1; then
  already "user ${DEPLOY_USER} exists"
else
  adduser --disabled-password --gecos "KnoRI deploy" "$DEPLOY_USER" >/dev/null
  changed "created user ${DEPLOY_USER}"
fi

if id -nG "$DEPLOY_USER" | tr ' ' '\n' | grep -qx docker; then
  already "${DEPLOY_USER} is in the docker group"
else
  usermod -aG docker "$DEPLOY_USER"
  changed "added ${DEPLOY_USER} to the docker group"
fi

USER_HOME="$(getent passwd "$DEPLOY_USER" | cut -d: -f6)"
AUTHORIZED="${USER_HOME}/.ssh/authorized_keys"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "${USER_HOME}/.ssh"

add_key() {
  local key="$1" source="$2"
  [ -n "$key" ] || return 0
  if [ -f "$AUTHORIZED" ] && grep -qxF "$key" "$AUTHORIZED"; then
    already "ssh key from ${source} already installed"
    return 0
  fi
  printf '%s\n' "$key" >>"$AUTHORIZED"
  chown "$DEPLOY_USER:$DEPLOY_USER" "$AUTHORIZED"
  chmod 600 "$AUTHORIZED"
  changed "installed an ssh key from ${source} for ${DEPLOY_USER}"
}

if [ -n "${DEPLOY_SSH_KEY:-}" ]; then
  add_key "$DEPLOY_SSH_KEY" "DEPLOY_SSH_KEY"
elif [ -s /root/.ssh/authorized_keys ]; then
  # A provider-created box usually has the owner's key on root already; copying it
  # means the deploy user is reachable without pasting the key again.
  while IFS= read -r line; do
    case "$line" in ssh-*|ecdsa-*|sk-*) add_key "$line" "root" ;; esac
  done </root/.ssh/authorized_keys
fi

if [ ! -s "$AUTHORIZED" ]; then
  warn "${DEPLOY_USER} has no ssh key yet. Add one before you log out, or you cannot deploy."
fi

# ------------------------------------------------------------------------- app folder

step "Application folder"
if [ -d "$APP_DIR" ]; then
  already "${APP_DIR} exists"
else
  install -d -m 0755 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$APP_DIR"
  changed "created ${APP_DIR}"
fi
current_owner="$(stat -c '%U' "$APP_DIR")"
if [ "$current_owner" != "$DEPLOY_USER" ]; then
  chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"
  changed "gave ${APP_DIR} to ${DEPLOY_USER}"
fi

# ---------------------------------------------------------------------------- swap

step "Swap"
ram_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
if [ "$ram_kb" -ge "$RAM_THRESHOLD_KB" ]; then
  already "$(( ram_kb / 1024 / 1024 )) GB of RAM: no swap file needed"
elif swapon --show --noheadings | grep -q .; then
  already "swap is already on"
else
  # An Opus run plus a Postgres autovacuum on a 4 GB box is where this saves the day.
  fallocate -l "$SWAP_SIZE" "$SWAP_FILE" || dd if=/dev/zero of="$SWAP_FILE" bs=1M count=4096
  chmod 600 "$SWAP_FILE"
  mkswap "$SWAP_FILE" >/dev/null
  swapon "$SWAP_FILE"
  grep -qF "$SWAP_FILE" /etc/fstab || echo "$SWAP_FILE none swap sw 0 0" >>/etc/fstab
  sysctl -q -w vm.swappiness=10
  grep -q '^vm.swappiness' /etc/sysctl.conf || echo "vm.swappiness=10" >>/etc/sysctl.conf
  changed "created ${SWAP_SIZE} of swap at ${SWAP_FILE}"
fi

# ------------------------------------------------------------------------- firewall

step "Firewall"
if ufw status | head -1 | grep -q "Status: active"; then
  already "ufw is active"
  FIREWALL_WAS_ON="true"
else
  FIREWALL_WAS_ON="false"
fi

ufw --force default deny incoming >/dev/null
ufw --force default allow outgoing >/dev/null
for rule in "22/tcp" "80/tcp" "443/tcp"; do
  if ufw status | grep -q "^${rule}"; then
    already "port ${rule} already open"
  else
    ufw allow "$rule" >/dev/null
    changed "opened ${rule}"
  fi
done
if [ "$FIREWALL_WAS_ON" = "false" ]; then
  ufw --force enable >/dev/null
  changed "enabled ufw (deny incoming, allow 22/80/443)"
fi
# Postgres is only reachable inside the compose network; nothing here publishes 5432.

# -------------------------------------------------------------------------- fail2ban

step "fail2ban"
if [ -f /etc/fail2ban/jail.d/knori.conf ]; then
  already "sshd jail configured"
else
  cat >/etc/fail2ban/jail.d/knori.conf <<'CONF'
# Ban an IP for an hour after 5 failed ssh logins in 10 minutes.
[sshd]
enabled  = true
backend  = systemd
maxretry = 5
findtime = 10m
bantime  = 1h
CONF
  changed "configured the sshd jail"
fi
if systemctl is-enabled fail2ban >/dev/null 2>&1 && systemctl is-active fail2ban >/dev/null 2>&1; then
  systemctl reload fail2ban >/dev/null 2>&1 || systemctl restart fail2ban
  already "fail2ban running"
else
  systemctl enable --now fail2ban >/dev/null
  changed "started fail2ban"
fi

# ---------------------------------------------------------------- automatic updates

step "Automatic security updates"
if [ -f /etc/apt/apt.conf.d/20auto-upgrades ] \
   && grep -q '"1"' /etc/apt/apt.conf.d/20auto-upgrades; then
  already "unattended-upgrades enabled"
else
  cat >/etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
CONF
  systemctl enable --now unattended-upgrades >/dev/null 2>&1 || true
  changed "enabled unattended security upgrades"
fi

# ---------------------------------------------------------------------- ssh hardening

step "SSH"
if [ "$HARDEN_SSH" != "true" ]; then
  already "skipped (HARDEN_SSH is not true)"
elif [ ! -s "$AUTHORIZED" ]; then
  warn "not turning off password logins: ${DEPLOY_USER} has no ssh key, that would lock you out"
elif [ -f /etc/ssh/sshd_config.d/99-knori.conf ]; then
  already "password logins already off"
else
  cat >/etc/ssh/sshd_config.d/99-knori.conf <<'CONF'
# Keys only. Set by deploy/scripts/provision_vps.sh; delete this file to undo.
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
CONF
  if sshd -t; then
    systemctl reload ssh 2>/dev/null || systemctl reload sshd
    changed "turned off password logins (keys only)"
  else
    rm -f /etc/ssh/sshd_config.d/99-knori.conf
    warn "sshd rejected the new config; left password logins on"
  fi
fi

# --------------------------------------------------------------------------- summary

step "Summary"
if [ "${#CHANGES[@]}" -eq 0 ]; then
  echo "  nothing to change — this machine was already provisioned"
else
  printf '  %s\n' "${CHANGES[@]}"
fi

cat <<EOF

Next steps (deploy/README.md has the detail):
  1. Point your domain's A record at this machine.
  2. As ${DEPLOY_USER}: clone the repository into ${APP_DIR}
  3. Write ${APP_DIR}/.env  (chmod 600) — see .env.example
  4. cd ${APP_DIR} && deploy/scripts/deploy.sh <image tag>

Log in as the deploy user from now on:  ssh ${DEPLOY_USER}@$(hostname -I 2>/dev/null | awk '{print $1}')
EOF
