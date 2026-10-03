#!/bin/bash
# Install the read-only LTE status script on the OpenWrt router and authorize
# the monitoring key of an Icinga agent for it (check_lte_router).
#
# Usage: sms-gateway/install-status.sh ROUTER PUBKEY_FILE
#   ROUTER       SSH target with admin access, e.g. root@10.10.10.210
#   PUBKEY_FILE  public key of the agent's check user (check_lte_router --identity)

set -euo pipefail

if [ $# -ne 2 ]; then
    echo "Usage: $0 ROUTER PUBKEY_FILE" >&2
    exit 1
fi
ROUTER="$1"
PUBKEY_FILE="$2"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
read -r -a SSH_OPTS <<< "${SSH_OPTS:-}"
pubkey="$(cat "$PUBKEY_FILE")"
case "$pubkey" in
    ssh-ed25519\ *|ssh-rsa\ *) ;;
    *) echo "ERROR: $PUBKEY_FILE is not an SSH public key" >&2; exit 1 ;;
esac

entry="command=\"/usr/bin/icinga-lte-status\",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding $pubkey"

# Dropbear's scp needs the OpenSSH legacy protocol (-O)
scp -O -q "${SSH_OPTS[@]}" "$SCRIPT_DIR/icinga-lte-status" "$ROUTER:/usr/bin/icinga-lte-status"
printf '%s\n' "$entry" | ssh "${SSH_OPTS[@]}" "$ROUTER" '
    set -e
    chmod 755 /usr/bin/icinga-lte-status
    keys=/etc/dropbear/authorized_keys
    read -r entry
    key="${entry##* ssh-}"
    grep -vF "$key" "$keys" > "$keys.new" || true
    echo "$entry" >> "$keys.new"
    chmod 600 "$keys.new"
    mv "$keys.new" "$keys"
    grep -qx /usr/bin/icinga-lte-status /etc/sysupgrade.conf || echo /usr/bin/icinga-lte-status >> /etc/sysupgrade.conf
'
echo "icinga-lte-status installed on $ROUTER"
