#!/bin/bash
# Build the custom plugins as one self-contained x86_64 tarball:
#   python/   standalone CPython (python-build-standalone via uv)
#   lib/      locked dependencies from requirements.txt (hash-checked)
#   bin/goss  goss binary for check_goss
#   check_*   wrappers, check_*.py plugins
#
# Built on Rocky Linux 8 (glibc 2.28), so it runs on every x86_64 Linux with
# glibc >= 2.28 (EL8+, Debian 10+, Ubuntu 20.04+, SLES 15+) without a venv or
# uv on the hosts.
#
# Usage: build/build.sh            -> dist/nagios-plugins-custom-VERSION-x86_64.tar.gz

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
DIST_DIR="${DIST_DIR:-$REPO_DIR/dist}"

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$REPO_DIR/pyproject.toml")"
PREFIX="${PREFIX:-/opt/nagios-plugins-custom-$VERSION}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
GOSS_VERSION="${GOSS_VERSION:-v0.4.10}"
NAME="nagios-plugins-custom-$VERSION-x86_64"

if command -v podman >/dev/null; then
    RUNTIME=podman
else
    RUNTIME=docker
fi

UV_BIN="$(command -v uv || true)"
if [ -z "$UV_BIN" ]; then
    echo "ERROR: uv not found on the build host" >&2
    exit 1
fi

mkdir -p "$DIST_DIR"
rm -rf "${DIST_DIR:?}/$NAME.tar.gz" "${DIST_DIR:?}/$NAME.tar.gz.sha256"

# Explicit platform: local image tags may point to another architecture
# after multi-arch builds
"$RUNTIME" pull -q --platform linux/amd64 quay.io/rockylinux/rockylinux:8 >/dev/null
"$RUNTIME" run --rm --platform linux/amd64 \
    -v "$REPO_DIR:/src:ro,Z" \
    -v "$DIST_DIR:/dist:Z" \
    -v "$UV_BIN:/usr/local/bin/uv:ro,Z" \
    -e PREFIX="$PREFIX" -e NAME="$NAME" -e VERSION="$VERSION" \
    -e PYTHON_VERSION="$PYTHON_VERSION" -e GOSS_VERSION="$GOSS_VERSION" \
    quay.io/rockylinux/rockylinux:8 bash -c '
        set -euo pipefail
        dnf -y -q install tar gzip findutils >/dev/null
        export UV_PYTHON_INSTALL_DIR=/tmp/python UV_CACHE_DIR=/tmp/uv-cache
        stage="/stage$PREFIX"
        mkdir -p "$stage/bin"

        uv python install -q "$PYTHON_VERSION"
        python_bin="$(uv python find "$PYTHON_VERSION")"
        cp -a "$(dirname "$(dirname "$(readlink -f "$python_bin")")")" "$stage/python"
        # Drop parts not needed at runtime
        rm -rf "$stage/python/lib/python3"*/test "$stage/python/lib/python3"*/idlelib \
               "$stage/python/lib/python3"*/tkinter "$stage/python/lib/python3"*/turtledemo \
               "$stage/python/include" "$stage/python/share"
        find "$stage/python" -name __pycache__ -type d -prune -exec rm -rf {} +

        uv pip install -q --python "$stage/python/bin/python3" --target "$stage/lib" \
            --require-hashes --no-cache -r /src/requirements.txt

        # Since v0.4.10 goss ships tarballs plus one SHA256SUMS file
        goss_url="https://github.com/goss-org/goss/releases/download/$GOSS_VERSION"
        goss_tar="goss_${GOSS_VERSION#v}_linux_x86_64.tar.gz"
        curl -fsSL -o "/tmp/$goss_tar" "$goss_url/$goss_tar"
        curl -fsSL "$goss_url/goss_${GOSS_VERSION#v}_SHA256SUMS" |
            grep " $goss_tar\$" | (cd /tmp && sha256sum -c --quiet)
        tar -xzf "/tmp/$goss_tar" -C "$stage/bin" goss
        chmod 755 "$stage/bin/goss"

        cp /src/check_*.py /src/notify_*.py "$stage/"
        for plugin in /src/check_*.py /src/notify_*.py; do
            name="$(basename "$plugin" .py)"
            case "$name" in
                check_lpr)
                    # RFC 1179 needs a privileged source port: the Ansible
                    # role creates python3-lpr (copy of the system python with
                    # cap_net_bind_service); the bundled python cannot get
                    # capabilities because it loads libpython via $ORIGIN
                    cat > "$stage/$name" <<EOF
#!/bin/sh
DIR="\$(dirname "\$(readlink -f "\$0")")"
if [ -x "\$DIR/python3-lpr" ]; then
    exec "\$DIR/python3-lpr" -s "\$DIR/$name.py" "\$@"
fi
exec "\$DIR/python/bin/python3" -s "\$DIR/$name.py" "\$@"
EOF
                    ;;
                *)
                    cat > "$stage/$name" <<EOF
#!/bin/sh
DIR="\$(dirname "\$(readlink -f "\$0")")"
PATH="\$DIR/bin:\$PATH" PYTHONPATH="\$DIR/lib" exec "\$DIR/python/bin/python3" -s "\$DIR/$name.py" "\$@"
EOF
                    ;;
            esac
            chmod 755 "$stage/$name"
        done

        cat > "$stage/BUILDINFO" <<EOF
name=nagios-plugins-custom
version=$VERSION
python=$("$stage/python/bin/python3" -V 2>&1)
uv=$(uv --version)
goss=$GOSS_VERSION
build_os=$(. /etc/os-release; echo "$PRETTY_NAME")
prefix=$PREFIX
EOF
        "$stage/python/bin/python3" -m compileall -q "$stage/lib" "$stage"/check_*.py "$stage"/notify_*.py >/dev/null || true
        tar -C /stage --numeric-owner --owner=0 --group=0 -czf "/dist/$NAME.tar.gz" "${PREFIX#/}"
    '

(cd "$DIST_DIR" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256")
echo "Built $DIST_DIR/$NAME.tar.gz ($(du -h "$DIST_DIR/$NAME.tar.gz" | cut -f1))"
