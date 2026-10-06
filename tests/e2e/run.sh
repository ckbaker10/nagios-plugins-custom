#!/usr/bin/env bash
# End-to-end acceptance test for the release bundle.
#
# Builds dist/nagios-plugins-custom-<version>-x86_64.tar.gz (or uses an
# existing one) and installs it like the Ansible role does in throwaway
# containers of the supported distributions. In each container it checks the
# checksum, BUILDINFO, that every plugin wrapper starts, that the bundled
# Python finds all locked dependencies, and runs check_goss and
# check_space_usage for real. Nothing is published.
#
# Usage: tests/e2e/run.sh [IMAGE...]     default: all images below
# Environment (all optional):
#   E2E_TARBALL   test this tarball instead of building one
#   E2E_ENGINE    container engine (default: podman, else docker)

set -euo pipefail

REPO=$(cd "$(dirname "$0")/../.." && pwd)
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' "$REPO/pyproject.toml")
NAME=nagios-plugins-custom-$VERSION-x86_64
ENGINE=${E2E_ENGINE:-$(command -v podman >/dev/null && echo podman || echo docker)}

# glibc >= 2.28 targets from the README
IMAGES=(
    quay.io/rockylinux/rockylinux:8
    quay.io/rockylinux/rockylinux:9
    quay.io/rockylinux/rockylinux:10
    docker.io/library/debian:12
    docker.io/library/debian:13
    docker.io/library/ubuntu:22.04
    docker.io/library/ubuntu:24.04
    docker.io/library/ubuntu:26.04
    registry.opensuse.org/opensuse/leap:15.6
    registry.opensuse.org/opensuse/leap:16.0
)
[ $# -gt 0 ] && IMAGES=("$@")

if [ -n "${E2E_TARBALL:-}" ]; then
    TARBALL=$(readlink -f "$E2E_TARBALL")
else
    DIST_DIR=$(mktemp -d "${TMPDIR:-/tmp}/npc-e2e.XXXXXX")
    trap 'rm -rf "$DIST_DIR"' EXIT
    echo "== Building $NAME"
    DIST_DIR=$DIST_DIR "$REPO/build/build.sh" >"$DIST_DIR/build.log" 2>&1 ||
        { tail -20 "$DIST_DIR/build.log"; exit 1; }
    TARBALL=$DIST_DIR/$NAME.tar.gz
fi
[ -f "$TARBALL" ] && [ -f "$TARBALL.sha256" ] || { echo "missing $TARBALL(.sha256)" >&2; exit 1; }

# Runs inside the target container; prints PASS/FAIL lines, exits non-zero on failure.
read -r -d '' INSIDE <<'EOF' || true
set -u
failures=0
pass() { echo "PASS  $*"; }
fail() { echo "FAIL  $*"; failures=$((failures + 1)); }
P=/opt/nagios-plugins-custom-$VERSION

# The role installs tar and gzip; minimal images may lack them
if ! command -v tar >/dev/null || ! command -v gzip >/dev/null; then
    if command -v dnf >/dev/null; then dnf -y -q install tar gzip >/dev/null
    elif command -v zypper >/dev/null; then zypper -q -n install tar gzip >/dev/null
    else apt-get -qq update && apt-get -qq install -y tar gzip >/dev/null
    fi
fi

(cd /dist && sha256sum -c --quiet "$(basename "$TARBALL").sha256") && pass "checksum" || fail "checksum"
tar -C / -xzf "/dist/$(basename "$TARBALL")" && ln -sfn "$P" /opt/nagios-plugins-lukas \
    && pass "unpacked to $P" || fail "unpack"
grep -qx "version=$VERSION" "$P/BUILDINFO" && pass "BUILDINFO version $VERSION" || fail "BUILDINFO"

for wrapper in /opt/nagios-plugins-lukas/check_* /opt/nagios-plugins-lukas/notify_sms; do
    case $wrapper in *.py) continue ;; esac
    name=$(basename "$wrapper")
    out=$("$wrapper" --help 2>&1) && [ -n "$out" ] && pass "$name --help" \
        || fail "$name --help: $(echo "$out" | tail -1)"
done

PYTHONPATH="$P/lib" "$P/python/bin/python3" -s -c \
    'import requests, urllib3, yaml, psutil, Crypto, pkcs7, kasa, aiohttp, cryptography, ecdsa' \
    && pass "bundled Python imports all locked dependencies" || fail "dependency import"

printf 'file:\n  /etc/os-release:\n    exists: true\n  /nonexistent:\n    exists: false\n' >/tmp/goss.yaml
out=$(/opt/nagios-plugins-lukas/check_goss -g /tmp/goss.yaml 2>&1); rc=$?
[ "$rc" = 0 ] && case $out in "OK - "*) true ;; *) false ;; esac \
    && pass "check_goss OK" || fail "check_goss rc=$rc: $out"
printf 'file:\n  /nonexistent:\n    exists: true\n' >/tmp/goss-fail.yaml
/opt/nagios-plugins-lukas/check_goss -g /tmp/goss-fail.yaml >/dev/null 2>&1; rc=$?
[ "$rc" = 2 ] && pass "check_goss CRITICAL on failing test" || fail "check_goss failing test rc=$rc"

out=$(/opt/nagios-plugins-lukas/check_space_usage -p /etc 2>&1); rc=$?
[ "$rc" -le 2 ] && case $out in OK*|WARNING*|CRITICAL*) true ;; *) false ;; esac \
    && pass "check_space_usage: ${out%% |*}" || fail "check_space_usage rc=$rc: $out"

exit "$failures"
EOF

total=0
for image in "${IMAGES[@]}"; do
    echo "== $image"
    if "$ENGINE" run --rm --platform linux/amd64 \
        -v "$(dirname "$TARBALL"):/dist:ro,Z" \
        -e VERSION="$VERSION" -e TARBALL="$TARBALL" \
        "$image" bash -c "$INSIDE"; then
        :
    else
        total=$((total + 1))
    fi
done

echo
if [ "$total" -eq 0 ]; then
    echo "All ${#IMAGES[@]} images passed."
else
    echo "$total of ${#IMAGES[@]} images failed."
    exit 1
fi
