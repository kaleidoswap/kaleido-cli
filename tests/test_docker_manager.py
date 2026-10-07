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


def test_find_free_base_ports_skips_bound_and_reserved_ports(tmp_path, monkeypatch):
    import kaleido_cli.docker_manager as dm

    other = tmp_path / "other"
    other.mkdir()
    (other / dm.COMPOSE_FILE).write_text(
        yaml.dump({"services": {"rgb_node_1": {"ports": ["3002:3002", "9737:9737"]}}})
    )
    monkeypatch.setattr(dm, "port_in_use", lambda port: port in {3001, 9735})

    assert dm.find_free_base_ports(1, tmp_path) == (3003, 9736)
    assert dm.find_free_base_ports(1, tmp_path, exclude_env="other") == (3002, 9736)
    assert dm.find_free_base_ports(2, tmp_path) == (3003, 9739)


def test_port_in_use_detects_listening_socket():
    import socket

    from kaleido_cli.docker_manager import port_in_use

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("0.0.0.0", 0))
        sock.listen()
        assert port_in_use(sock.getsockname()[1])
