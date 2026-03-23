#!/usr/bin/env python3
"""Cross-platform bootstrap installer for Kaleido CLI."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PACKAGE_URL = "git+https://github.com/kaleidoswap/kaleido-cli.git"


def _run(cmd: list[str]) -> int:
    print(f"==> {' '.join(cmd)}")
    return subprocess.run(cmd).returncode


def main() -> int:
    if sys.version_info < (3, 10):
        print("Kaleido CLI requires Python 3.10 or newer.")
        return 1

    repo_root = Path(__file__).resolve().parent
    is_repo_checkout = (repo_root / "pyproject.toml").exists()
    install_target = str(repo_root) if is_repo_checkout else PACKAGE_URL

    if shutil.which("uv"):
        cmd = ["uv", "tool", "install", "--force", install_target]
        if is_repo_checkout:
            cmd.insert(3, "--editable")
        rc = _run(cmd)
    else:
        cmd = [sys.executable, "-m", "pip", "install", "--user", "--upgrade", install_target]
        rc = _run(cmd)

    if rc != 0:
        return rc

    print("\nKaleido CLI installed.")
    print("Next step: run 'kaleido setup'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
