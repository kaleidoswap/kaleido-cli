#!/bin/sh

set -eu

PACKAGE_NAME="kaleido-cli"
ARCHIVE_REPO="https://github.com/kaleidoswap/kaleido-cli/archive/refs/heads"
INSTALL_REF="${KALEIDO_INSTALL_REF:-main}"

say() {
    printf '==> %s\n' "$*"
}

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

run() {
    say "$*"
    "$@"
}

find_python() {
    if command -v python3 >/dev/null 2>&1; then
        printf '%s\n' python3
        return 0
    fi
    if command -v python >/dev/null 2>&1; then
        printf '%s\n' python
        return 0
    fi
    return 1
}

PYTHON_BIN="$(find_python)" || fail "Python 3.10 or newer is required."

"$PYTHON_BIN" - <<'PY' || fail "Kaleido CLI requires Python 3.10 or newer."
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY

TMP_DIR=""
cleanup() {
    if [ -n "${TMP_DIR}" ] && [ -d "${TMP_DIR}" ]; then
        rm -rf "${TMP_DIR}"
    fi
}
trap cleanup EXIT INT TERM

LOCAL_CHECKOUT=0
if [ -f "./pyproject.toml" ] && [ -d "./kaleido_cli" ]; then
    INSTALL_TARGET="$(pwd)"
    LOCAL_CHECKOUT=1
else
    command -v tar >/dev/null 2>&1 || fail "'tar' is required for the bootstrap installer."
    TMP_DIR="$(mktemp -d 2>/dev/null || mktemp -d -t kaleido-cli)"
    ARCHIVE_PATH="${TMP_DIR}/${PACKAGE_NAME}.tar.gz"
    ARCHIVE_URL="${ARCHIVE_REPO}/${INSTALL_REF}.tar.gz"

    if command -v curl >/dev/null 2>&1; then
        run curl -fsSL "${ARCHIVE_URL}" -o "${ARCHIVE_PATH}"
    elif command -v wget >/dev/null 2>&1; then
        run wget -qO "${ARCHIVE_PATH}" "${ARCHIVE_URL}"
    else
        fail "curl or wget is required to download the installer payload."
    fi

    run tar -xzf "${ARCHIVE_PATH}" -C "${TMP_DIR}"

    INSTALL_TARGET="$(find "${TMP_DIR}" -mindepth 1 -maxdepth 1 -type d -name 'kaleido-cli-*' | head -n 1)"
    [ -n "${INSTALL_TARGET}" ] || fail "Failed to unpack the Kaleido CLI source archive."
fi

if command -v uv >/dev/null 2>&1; then
    if [ "${LOCAL_CHECKOUT}" -eq 1 ]; then
        run uv tool install --force --editable "${INSTALL_TARGET}"
    else
        run uv tool install --force "${INSTALL_TARGET}"
    fi
else
    run "${PYTHON_BIN}" -m pip install --user --upgrade "${INSTALL_TARGET}"
fi

USER_BIN_DIR="$("$PYTHON_BIN" - <<'PY'
import os
import site
import sysconfig

user_base = site.getuserbase()
scripts_path = sysconfig.get_path("scripts", vars={"base": user_base, "platbase": user_base})
print(os.path.abspath(scripts_path))
PY
)"

printf '\nKaleido CLI installed.\n'
printf "Next step: run 'kaleido setup'\n"

if ! command -v kaleido >/dev/null 2>&1; then
    printf "If 'kaleido' is not found yet, add %s to your PATH and restart your shell.\n" "${USER_BIN_DIR}"
fi
