"""Shared RGB asset issuance helpers."""

from __future__ import annotations

import hashlib

import typer

from kaleido_cli.output import is_interactive


def resolve_asset_metadata(
    description: str | None,
    file_path: str | None,
) -> tuple[str | None, str | None]:
    """Resolve optional issuance description and media path prompts."""
    if not is_interactive():
        return description, file_path

    raw_description = typer.prompt("[OPTIONAL] Description (Enter to skip)", default="")
    if raw_description.strip():
        description = raw_description.strip()

    raw_file_path = typer.prompt("[OPTIONAL] Media file path (Enter to skip)", default="")
    if raw_file_path.strip():
        file_path = raw_file_path.strip()

    return description, file_path


def sha256_file(file_path: str | None) -> str | None:
    """Return a file's SHA-256 digest without loading the whole file into memory."""
    if not file_path:
        return None

    digest = hashlib.sha256()
    with open(file_path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
