"""Tests for Docker compose generation."""

from __future__ import annotations

import yaml

from kaleido_cli.docker_manager import SpawnConfig, SpawnManager


def test_spawn_manager_writes_mutinynet_as_rln_signetcustom(tmp_path):
    manager = SpawnManager(
        SpawnConfig(
            name="mutiny",
            spawn_base_dir=str(tmp_path),
            network="mutinynet",
        )
    )

    compose_path = manager.generate_compose()
    compose = yaml.safe_load(compose_path.read_text())
    node = compose["services"]["rgb_node_1"]

    assert "--network signetcustom" in node["command"]
    assert node["environment"]["NETWORK"] == "${NETWORK:-signetcustom}"
