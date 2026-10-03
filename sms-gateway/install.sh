#!/bin/bash
# Install the SMS gateway on the OpenWrt LTE router and authorize the
# notification key of an Icinga agent for it.
#
# Usage: sms-gateway/install.sh ROUTER PUBKEY_FILE NUMBER [NUMBER...]
#   ROUTER       SSH target with admin access, e.g. root@10.10.10.210
#   PUBKEY_FILE  public key of the agent's nagios user (notify_sms --identity)
#   NUMBER       allowed recipients in international format (+49...)
#
# Re-running replaces the allow list and keeps a single key entry.

set -euo pipefail

if [ $# -lt 3 ]; then
    echo "Usage: $0 ROUTER PUBKEY_FILE NUMBER [NUMBER...]" >&2
    exit 1
fi
ROUTER="$1"
PUBKEY_FILE="$2"
shift 2

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
read -r -a SSH_OPTS <<< "${SSH_OPTS:-}"
pubkey="$(cat "$PUBKEY_FILE")"
case "$pubkey" in
    ssh-ed25519\ *|ssh-rsa\ *) ;;
    *) echo "ERROR: $PUBKEY_FILE is not an SSH public key" >&2; exit 1 ;;
esac
for n in "$@"; do
    [[ "$n" =~ ^\+[0-9]{8,15}$ ]] || { echo "ERROR: $n is not in +<country><number> format" >&2; exit 1; }
done

entry="command=\"/usr/bin/icinga-sms\",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding $pubkey"

# Dropbear's scp needs the OpenSSH legacy protocol (-O)
scp -O -q "${SSH_OPTS[@]}" "$SCRIPT_DIR/icinga-sms" "$ROUTER:/usr/bin/icinga-sms"
printf '%s\n' "$@" | ssh "${SSH_OPTS[@]}" "$ROUTER" 'cat > /etc/icinga-sms.allow && chmod 600 /etc/icinga-sms.allow'
printf '%s\n' "$entry" | ssh "${SSH_OPTS[@]}" "$ROUTER" '
    set -e
    chmod 755 /usr/bin/icinga-sms
    keys=/etc/dropbear/authorized_keys
    read -r entry
    key="${entry##* ssh-}"
    grep -vF "$key" "$keys" > "$keys.new" || true
    echo "$entry" >> "$keys.new"
    chmod 600 "$keys.new"
    mv "$keys.new" "$keys"
    # keep script and allow list across firmware upgrades
    for f in /usr/bin/icinga-sms /etc/icinga-sms.allow; do
        grep -qx "$f" /etc/sysupgrade.conf || echo "$f" >> /etc/sysupgrade.conf
    done
'
echo "icinga-sms installed on $ROUTER for $# number(s)"
