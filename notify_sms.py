#!/usr/bin/env python3
"""
notify_sms - Icinga2 notification command that sends an SMS through the LTE
router's modem (sms-gateway/icinga-sms on the router).

The router is only reachable from the home network, so the notification runs
on an agent there (Notification.command_endpoint). The SMS is handed over via
SSH with a dedicated key whose only allowed command on the router is
icinga-sms; the router accepts only numbers from its allow list.

Example:
  notify_sms --to +4917... --type PROBLEM --host "P03 Hebepumpe Haus" \\
      --service tapo-status-on --state CRITICAL --output "Device OFF"
"""

import argparse
import subprocess
import sys
import time

__version__ = '1.0.0'


def build_message(args) -> str:
    """Short single-SMS text: most important information first."""
    subject = args.host if not args.service else f"{args.host} {args.service}"
    text = f"{args.type} {args.state}: {subject}"
    if args.time:
        text += f" {args.time}"
    if args.output and args.type not in ("RECOVERY",):
        text += f" - {args.output.splitlines()[0] if args.output.splitlines() else args.output}"
    return text[:160]


def send(args, message: str) -> subprocess.CompletedProcess:
    cmd = [
        "ssh", "-i", args.identity,
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={args.timeout}",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={args.known_hosts}",
        args.gateway, "send", args.to,
    ]
    return subprocess.run(cmd, input=message, capture_output=True, text=True,
                          timeout=args.timeout + 90)


def main():
    parser = argparse.ArgumentParser(description="Send an Icinga2 notification as SMS via the LTE router")
    parser.add_argument("--to", required=True, help="Recipient number (must be allowed on the router)")
    parser.add_argument("--type", default="PROBLEM", help="Notification type ($notification.type$)")
    parser.add_argument("--host", required=True, help="Host display name")
    parser.add_argument("--service", default="", help="Service name (empty for host notifications)")
    parser.add_argument("--state", required=True, help="State ($service.state$ / $host.state$)")
    parser.add_argument("--output", default="", help="Plugin output")
    parser.add_argument("--time", default="", help="Short time stamp, e.g. $icinga.short_date_time$")
    parser.add_argument("--gateway", default="root@10.10.10.210", help="SSH target of the router (default: root@10.10.10.210)")
    parser.add_argument("--identity", default="/var/lib/nagios/.ssh/icinga-sms",
                        help="SSH key allowed to run icinga-sms on the router")
    parser.add_argument("--known-hosts", default="/var/lib/nagios/.ssh/known_hosts_icinga_sms",
                        help="known_hosts file with the router's host key")
    parser.add_argument("--timeout", type=int, default=15, help="SSH connect timeout in seconds")
    parser.add_argument("--retries", type=int, default=2, help="Retries on failure (default: 2)")
    parser.add_argument("--dry-run", action="store_true", help="Print the message instead of sending")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()

    message = build_message(args)
    if args.dry_run:
        print(message)
        return 0

    last_error = ""
    for attempt in range(args.retries + 1):
        try:
            result = send(args, message)
            if result.returncode == 0:
                print(f"SMS {result.stdout.strip()}")
                return 0
            last_error = (result.stderr or result.stdout).strip()
            # Rejected number or usage error: retrying does not help
            if result.returncode in (2, 3):
                break
        except subprocess.TimeoutExpired:
            last_error = "timeout"
        if attempt < args.retries:
            time.sleep(10)

    print(f"SMS failed: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
