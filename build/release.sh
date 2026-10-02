#!/bin/bash
# Upload the bundle from dist/ as GitHub release v<version> (pyproject.toml).
# The Ansible role downloads it from there.
#
# Usage: build/release.sh       requires an authenticated GitHub CLI (gh auth login)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
DIST_DIR="${DIST_DIR:-$REPO_DIR/dist}"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$REPO_DIR/pyproject.toml")"
NAME="nagios-plugins-custom-$VERSION-x86_64.tar.gz"

(cd "$DIST_DIR" && sha256sum -c --quiet "$NAME.sha256")

notes="Custom Nagios/Icinga plugins, one self-contained x86_64 bundle
(standalone Python, locked dependencies, goss).

$(tar -xzOf "$DIST_DIR/$NAME" "opt/nagios-plugins-custom-$VERSION/BUILDINFO")

SHA-256:
\`\`\`
$(cat "$DIST_DIR/$NAME.sha256")
\`\`\`"

cd "$REPO_DIR"
gh release create "v$VERSION" --title "v$VERSION" --notes "$notes" \
    "$DIST_DIR/$NAME" "$DIST_DIR/$NAME.sha256"
