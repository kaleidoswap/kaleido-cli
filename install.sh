#!/bin/sh

set -eu

PACKAGE_NAME="kaleido-cli"
ARCHIVE_REPO="https://github.com/kaleidoswap/kaleido-cli/archive/refs/heads"
INSTALL_REF="${KALEIDO_INSTALL_REF:-master}"

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

python_ok() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

find_python() {
    if [ -n "${KALEIDO_PYTHON:-}" ]; then
        python_ok "$KALEIDO_PYTHON" || fail "KALEIDO_PYTHON=$KALEIDO_PYTHON is not Python 3.10 or newer."
        printf '%s\n' "$KALEIDO_PYTHON"
        return 0
    fi
    for candidate in python3 python3.14 python3.13 python3.12 python3.11 python3.10 python; do
        if command -v "$candidate" >/dev/null 2>&1 && python_ok "$candidate"; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

PYTHON_BIN="$(find_python)" || fail "Kaleido CLI requires Python 3.10 or newer. Install one, or point KALEIDO_PYTHON at it."

if [ -f "./pyproject.toml" ] && [ -d "./kaleido_cli" ]; then
    exec "$PYTHON_BIN" ./install.py
fi

"$PYTHON_BIN" - "${ARCHIVE_REPO}/${INSTALL_REF}.tar.gz" "${PACKAGE_NAME}" <<'PY'
from __future__ import annotations

import shutil
import os
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

archive_url = sys.argv[1]
package_name = sys.argv[2]
tmp_dir = Path(tempfile.mkdtemp(prefix=f"{package_name}-"))

try:
    archive_path = tmp_dir / f"{package_name}.tar.gz"
    print(f"==> downloading {archive_url}")
    urllib.request.urlretrieve(archive_url, archive_path)

    print(f"==> extracting {archive_path}")
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(tmp_dir)

    roots = [path for path in tmp_dir.iterdir() if path.is_dir() and path.name.startswith(f"{package_name}-")]
    if not roots:
        raise SystemExit("Failed to unpack the Kaleido CLI source archive.")

    installer = roots[0] / "install.py"
    if not installer.exists():
        raise SystemExit("The Kaleido CLI source archive does not contain install.py.")

    namespace = {"__file__": str(installer), "__name__": "__main__"}
    os.environ["KALEIDO_INSTALL_EDITABLE"] = "0"
    code = compile(installer.read_text(encoding="utf-8"), str(installer), "exec")
    exec(code, namespace)
finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)
PY
