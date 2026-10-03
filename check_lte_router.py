#!/usr/bin/env python3
"""
check_lte_router - Nagios/Icinga plugin for an OpenWrt LTE router (tested:
ZTE MF289F) with the status script sms-gateway/icinga-lte-status.

The status is read via SSH with a key whose only allowed command on the
router is icinga-lte-status (KEY=VALUE lines).

CRITICAL: SIM not ready, not registered, LTE data interface down, no
          internet via LTE, signal below the critical thresholds
WARNING:  signal below the warning thresholds, roaming
UNKNOWN:  router not reachable via SSH / no status
"""

import argparse
import subprocess
import sys

__version__ = '1.0.0'

OK, WARNING, CRITICAL, UNKNOWN = 0, 1, 2, 3
STATE_NAMES = {OK: "OK", WARNING: "WARNING", CRITICAL: "CRITICAL", UNKNOWN: "UNKNOWN"}
REG_STATES = {"0": "not registered", "1": "home", "2": "searching", "3": "denied",
              "4": "unknown", "5": "roaming"}


def read_status(args) -> dict:
    cmd = [
        "ssh", "-i", args.identity,
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={args.timeout}",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={args.known_hosts}",
        args.router, "status",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout + 45)
    if result.returncode != 0:
        lines = (result.stderr or result.stdout).strip().splitlines()
        raise RuntimeError(lines[-1] if lines else f"ssh exit code {result.returncode}")
    status = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            status[key.strip()] = value.strip()
    return status


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_duration(seconds) -> str:
    seconds = int(seconds or 0)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    return f"{days}d{hours:02d}h" if days else f"{hours}h{rest // 60:02d}m"


def evaluate(status: dict, args):
    state = OK
    problems = []

    def raise_to(level, text):
        nonlocal state
        state = max(state, level)
        problems.append(text)

    if status.get("sim") != "READY":
        raise_to(CRITICAL, f"SIM {status.get('sim') or 'missing'}")
    reg = status.get("reg", "")
    if reg not in ("1", "5"):
        raise_to(CRITICAL, f"network {REG_STATES.get(reg, reg or 'unknown')}")
    elif reg == "5" and not args.allow_roaming:
        raise_to(WARNING, "roaming")
    if status.get("data_up") != "true":
        raise_to(CRITICAL, "LTE data connection down")
    elif status.get("internet") != "1":
        raise_to(CRITICAL, "no internet via LTE")

    rsrp, rsrq, sinr, rssi = (to_float(status.get(k)) for k in ("rsrp", "rsrq", "sinr", "rssi"))
    if rsrp is not None:
        if rsrp < args.rsrp_critical:
            raise_to(CRITICAL, f"RSRP {rsrp:g} dBm")
        elif rsrp < args.rsrp_warning:
            raise_to(WARNING, f"RSRP {rsrp:g} dBm")
    if sinr is not None:
        if sinr < args.sinr_critical:
            raise_to(CRITICAL, f"SINR {sinr:g} dB")
        elif sinr < args.sinr_warning:
            raise_to(WARNING, f"SINR {sinr:g} dB")

    summary = (f"{status.get('band') or 'LTE'} {status.get('operator', '')}".strip()
               + f", RSRP {status.get('rsrp', '?')} dBm, RSRQ {status.get('rsrq', '?')} dB,"
               f" SINR {status.get('sinr', '?')} dB, data up {format_duration(status.get('data_uptime'))}")
    text = f"{STATE_NAMES[state]} - "
    text += f"{', '.join(problems)} - {summary}" if problems else summary

    perf = []
    if rsrp is not None:
        perf.append(f"rsrp={rsrp:g}dBm;{args.rsrp_warning:g};{args.rsrp_critical:g}")
    if rsrq is not None:
        perf.append(f"rsrq={rsrq:g}dB")
    if sinr is not None:
        perf.append(f"sinr={sinr:g}dB;{args.sinr_warning:g};{args.sinr_critical:g}")
    if rssi is not None:
        perf.append(f"rssi={rssi:g}dBm")
    if status.get("data_uptime"):
        perf.append(f"data_uptime={status['data_uptime']}s")
    if perf:
        text += " | " + " ".join(perf)
    return state, text


def main():
    parser = argparse.ArgumentParser(description="Check an OpenWrt LTE router (SIM, registration, signal, data)")
    parser.add_argument("--router", default="root@10.10.10.210", help="SSH target of the router")
    parser.add_argument("--identity", default="/var/lib/nagios/.ssh/icinga-lte",
                        help="SSH key allowed to run icinga-lte-status on the router")
    parser.add_argument("--known-hosts", default="/var/lib/nagios/.ssh/known_hosts_icinga_lte",
                        help="known_hosts file with the router's host key")
    parser.add_argument("--rsrp-warning", type=float, default=-115, help="RSRP warning below (dBm, default -115)")
    parser.add_argument("--rsrp-critical", type=float, default=-125, help="RSRP critical below (dBm, default -125)")
    parser.add_argument("--sinr-warning", type=float, default=0, help="SINR warning below (dB, default 0)")
    parser.add_argument("--sinr-critical", type=float, default=-5, help="SINR critical below (dB, default -5)")
    parser.add_argument("--allow-roaming", action="store_true", help="Do not warn when roaming")
    parser.add_argument("-t", "--timeout", type=int, default=15, help="SSH connect timeout (default 15 s)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args()

    try:
        status = read_status(args)
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as e:
        print(f"UNKNOWN - cannot read router status: {e}")
        return UNKNOWN
    if not status:
        print("UNKNOWN - empty status from router")
        return UNKNOWN

    state, text = evaluate(status, args)
    print(text)
    return state


if __name__ == "__main__":
    sys.exit(main())
