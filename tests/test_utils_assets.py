"""Tests for shared RGB asset helpers."""

from __future__ import annotations

import hashlib

from kaleido_cli.utils.assets import sha256_file


def test_sha256_file_streams_expected_digest(tmp_path):
    content = b"kaleido-asset" * 100
    media = tmp_path / "asset.bin"
    media.write_bytes(content)

    assert sha256_file(str(media)) == hashlib.sha256(content).hexdigest()


def test_sha256_file_accepts_missing_optional_path():
    assert sha256_file(None) is None
