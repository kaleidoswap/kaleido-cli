#!/usr/bin/env python3
"""Cross-platform bootstrap installer for Kaleido CLI."""

from __future__ import annotations

import os
import shutil
import site
import stat
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import urllib.request
import venv
from pathlib import Path

PACKAGE_NAME = "kaleido-cli"
ARCHIVE_REPO = "https://github.com/kaleidoswap/kaleido-cli/archive/refs/heads"
INSTALL_REF = os.environ.get("KALEIDO_INSTALL_REF", "master")
PIP_ZIPAPP_URL = "https://bootstrap.pypa.io/pip/pip.pyz"


def _say(message: str) -> None:
    print(f"==> {message}")


def _run(cmd: list[str]) -> int:
    _say(" ".join(cmd))
    return subprocess.run(cmd).returncode


def _user_data_dir() -> Path:
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if root:
            return Path(root) / "kaleido-cli"
        return Path.home() / "AppData" / "Local" / "kaleido-cli"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "kaleido-cli"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "kaleido-cli"


def _user_bin_dir() -> Path:
    user_base = site.getuserbase()
    scripts_path = sysconfig.get_path("scripts", vars={"base": user_base, "platbase": user_base})
    return Path(scripts_path).resolve()


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _download_source_archive() -> tuple[Path, Path]:
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"{PACKAGE_NAME}-"))
    archive_url = f"{ARCHIVE_REPO}/{INSTALL_REF}.tar.gz"
    archive_path = tmp_dir / f"{PACKAGE_NAME}.tar.gz"

    _say(f"downloading {archive_url}")
    urllib.request.urlretrieve(archive_url, archive_path)

    _say(f"extracting {archive_path}")
    with tarfile.open(archive_path, "r:gz") as archive:
        archive.extractall(tmp_dir)

    roots = [path for path in tmp_dir.iterdir() if path.is_dir() and path.name.startswith(f"{PACKAGE_NAME}-")]
    if not roots:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError("Failed to unpack the Kaleido CLI source archive.")

    return roots[0], tmp_dir


def _create_venv(venv_dir: Path, install_dir: Path) -> list[str]:
    try:
        venv.EnvBuilder(with_pip=True, upgrade_deps=False).create(venv_dir)
        return [str(_venv_python(venv_dir)), "-m", "pip"]
    except Exception as exc:
        print(f"Could not create a venv with bundled pip: {exc}", file=sys.stderr)
        print("Retrying with a standalone pip bootstrap inside the Kaleido venv.", file=sys.stderr)

    shutil.rmtree(venv_dir, ignore_errors=True)
    venv.EnvBuilder(with_pip=False).create(venv_dir)

    pip_zipapp = install_dir / "pip.pyz"
    _say(f"downloading {PIP_ZIPAPP_URL}")
    urllib.request.urlretrieve(PIP_ZIPAPP_URL, pip_zipapp)
    return [str(_venv_python(venv_dir)), str(pip_zipapp)]


def _install_with_venv(install_target: str, editable: bool) -> int:
    install_dir = Path(os.environ.get("KALEIDO_INSTALL_DIR", _user_data_dir()))
    venv_dir = install_dir / "venv"
    bin_dir = _user_bin_dir()

    _say(f"creating isolated Python environment at {venv_dir}")
    install_dir.mkdir(parents=True, exist_ok=True)
    try:
        pip_runner = _create_venv(venv_dir, install_dir)
    except Exception as exc:
        print(f"Failed to create a virtual environment: {exc}", file=sys.stderr)
        print(
            "Please install a Python build that includes the standard 'venv' module, "
            "then rerun this installer.",
            file=sys.stderr,
        )
        return 1

    pip_cmd = [*pip_runner, "install", "--upgrade"]
    if editable:
        pip_cmd.append("--editable")
    pip_cmd.append(install_target)

    rc = _run(pip_cmd)
    if rc != 0:
        return rc

    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_launcher(bin_dir, _venv_python(venv_dir))
    print(f"Installed executable: {bin_dir / _launcher_name()}")
    return 0


def _launcher_name() -> str:
    return "kaleido.cmd" if sys.platform == "win32" else "kaleido"


def _write_launcher(bin_dir: Path, python: Path) -> None:
    launcher = bin_dir / _launcher_name()
    if sys.platform == "win32":
        launcher.write_text(f'@echo off\r\n"{python}" -m kaleido_cli %*\r\n', encoding="utf-8")
        return

    launcher.write_text(f'#!/bin/sh\nexec "{python}" -m kaleido_cli "$@"\n', encoding="utf-8")
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main() -> int:
    if sys.version_info < (3, 10):
        print("Kaleido CLI requires Python 3.10 or newer.")
        return 1

    script_file = globals().get("__file__")
    repo_root = Path(script_file).resolve().parent if script_file else Path.cwd()
    temp_dir: Path | None = None

    try:
        is_repo_checkout = script_file is not None and (repo_root / "pyproject.toml").exists()
        if is_repo_checkout:
            install_target = str(repo_root)
            editable = os.environ.get("KALEIDO_INSTALL_EDITABLE", "1") != "0"
        else:
            source_root, temp_dir = _download_source_archive()
            install_target = str(source_root)
            editable = False

        if shutil.which("uv"):
            cmd = ["uv", "tool", "install", "--force", install_target]
            if editable:
                cmd.insert(3, "--editable")
            rc = _run(cmd)
        else:
            rc = _install_with_venv(install_target, editable=editable)
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)

    if rc != 0:
        return rc

    print("\nKaleido CLI installed.")
    print("Next step: run 'kaleido setup'")

    if shutil.which("kaleido") is None:
        print(f"If 'kaleido' is not found yet, add {_user_bin_dir()} to your PATH and restart your shell.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
