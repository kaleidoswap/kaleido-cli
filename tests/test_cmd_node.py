"""Tests for `kaleido node` CLI commands."""

from __future__ import annotations

from kaleido_cli.app import app
from kaleido_cli.config import (
    DEFAULT_BITCOIND_RPC_HOST,
    DEFAULT_BITCOIND_RPC_PASSWORD,
    DEFAULT_BITCOIND_RPC_PORT,
    DEFAULT_BITCOIND_RPC_USERNAME,
    DEFAULT_INDEXER_URL,
    DEFAULT_PROXY_ENDPOINT,
    DEFAULT_REGTEST_BITCOIND_RPC_HOST,
    DEFAULT_REGTEST_BITCOIND_RPC_PASSWORD,
    DEFAULT_REGTEST_BITCOIND_RPC_PORT,
    DEFAULT_REGTEST_BITCOIND_RPC_USERNAME,
    DEFAULT_REGTEST_INDEXER_URL,
    DEFAULT_REGTEST_PROXY_ENDPOINT,
)


def _unlock_request(mock_client):
    return mock_client.rln.unlock_wallet.await_args.args[0]


def test_node_unlock_interactive_signet_defaults(runner, mocker, mock_client):
    mocker.patch("kaleido_cli.commands.node.is_interactive", return_value=True)

    result = runner.invoke(app, ["node", "unlock"], input="walletpw\ns\n\n\n")

    assert result.exit_code == 0
    req = _unlock_request(mock_client)
    assert req.password == "walletpw"
    assert req.bitcoind_rpc_username == DEFAULT_BITCOIND_RPC_USERNAME
    assert req.bitcoind_rpc_password == DEFAULT_BITCOIND_RPC_PASSWORD
    assert req.bitcoind_rpc_host == DEFAULT_BITCOIND_RPC_HOST
    assert req.bitcoind_rpc_port == DEFAULT_BITCOIND_RPC_PORT
    assert req.indexer_url == DEFAULT_INDEXER_URL
    assert req.proxy_endpoint == DEFAULT_PROXY_ENDPOINT


def test_node_unlock_interactive_regtest_defaults(runner, mocker, mock_client):
    mocker.patch("kaleido_cli.commands.node.is_interactive", return_value=True)

    result = runner.invoke(app, ["node", "unlock"], input="walletpw\nr\n\n\n")

    assert result.exit_code == 0
    req = _unlock_request(mock_client)
    assert req.password == "walletpw"
    assert req.bitcoind_rpc_username == DEFAULT_REGTEST_BITCOIND_RPC_USERNAME
    assert req.bitcoind_rpc_password == DEFAULT_REGTEST_BITCOIND_RPC_PASSWORD
    assert req.bitcoind_rpc_host == DEFAULT_REGTEST_BITCOIND_RPC_HOST
    assert req.bitcoind_rpc_port == DEFAULT_REGTEST_BITCOIND_RPC_PORT
    assert req.indexer_url == DEFAULT_REGTEST_INDEXER_URL
    assert req.proxy_endpoint == DEFAULT_REGTEST_PROXY_ENDPOINT


def test_node_unlock_interactive_custom_services(runner, mocker, mock_client):
    mocker.patch("kaleido_cli.commands.node.is_interactive", return_value=True)

    result = runner.invoke(
        app,
        ["node", "unlock"],
        input=(
            "walletpw\n"
            "c\n"
            "alice\n"
            "secret\n"
            "127.0.0.1\n"
            "18443\n"
            "tcp://127.0.0.1:50001\n"
            "rpc://127.0.0.1:3000/json-rpc\n"
            "alias\n"
            "127.0.0.1:9735\n"
        ),
    )

    assert result.exit_code == 0
    req = _unlock_request(mock_client)
    assert req.password == "walletpw"
    assert req.bitcoind_rpc_username == "alice"
    assert req.bitcoind_rpc_password == "secret"
    assert req.bitcoind_rpc_host == "127.0.0.1"
    assert req.bitcoind_rpc_port == 18443
    assert req.indexer_url == "tcp://127.0.0.1:50001"
    assert req.proxy_endpoint == "rpc://127.0.0.1:3000/json-rpc"
    assert req.announce_alias == "alias"
    assert req.announce_addresses == ["127.0.0.1:9735"]
