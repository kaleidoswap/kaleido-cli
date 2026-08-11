"""Tests for `kaleido node` CLI commands."""

from __future__ import annotations

from kaleido_cli.app import app
from kaleido_cli.config import (
    DEFAULT_BITCOIND_RPC_HOST,
    DEFAULT_BITCOIND_RPC_PASSWORD,
    DEFAULT_BITCOIND_RPC_PORT,
    DEFAULT_BITCOIND_RPC_USERNAME,
    DEFAULT_INDEXER_URL,
    DEFAULT_REGTEST_BITCOIND_RPC_HOST,
    DEFAULT_REGTEST_BITCOIND_RPC_PASSWORD,
    DEFAULT_REGTEST_BITCOIND_RPC_PORT,
    DEFAULT_REGTEST_BITCOIND_RPC_USERNAME,
    DEFAULT_REGTEST_INDEXER_URL,
)


def _unlock_request(mock_client):
    return mock_client.rln.unlock_wallet.await_args.args[0]


def _block_sync_config(req):
    assert req.ldk_chain_sync.mode == "BlockSync"
    return req.ldk_chain_sync.config


def test_node_unlock_interactive_signet_defaults(runner, mocker, mock_client):
    mocker.patch("kaleido_cli.commands.node.is_interactive", return_value=True)

    result = runner.invoke(app, ["node", "unlock"], input="walletpw\ns\nb\n\n\n")

    assert result.exit_code == 0
    req = _unlock_request(mock_client)
    assert req.password == "walletpw"
    config = _block_sync_config(req)
    assert config.bitcoind_rpc_username == DEFAULT_BITCOIND_RPC_USERNAME
    assert config.bitcoind_rpc_password == DEFAULT_BITCOIND_RPC_PASSWORD
    assert config.bitcoind_rpc_host == DEFAULT_BITCOIND_RPC_HOST
    assert config.bitcoind_rpc_port == DEFAULT_BITCOIND_RPC_PORT
    assert req.indexer_url == DEFAULT_INDEXER_URL


def test_node_unlock_interactive_regtest_defaults(runner, mocker, mock_client):
    mocker.patch("kaleido_cli.commands.node.is_interactive", return_value=True)

    result = runner.invoke(app, ["node", "unlock"], input="walletpw\nr\nb\n\n\n")

    assert result.exit_code == 0
    req = _unlock_request(mock_client)
    assert req.password == "walletpw"
    config = _block_sync_config(req)
    assert config.bitcoind_rpc_username == DEFAULT_REGTEST_BITCOIND_RPC_USERNAME
    assert config.bitcoind_rpc_password == DEFAULT_REGTEST_BITCOIND_RPC_PASSWORD
    assert config.bitcoind_rpc_host == DEFAULT_REGTEST_BITCOIND_RPC_HOST
    assert config.bitcoind_rpc_port == DEFAULT_REGTEST_BITCOIND_RPC_PORT
    assert req.indexer_url == DEFAULT_REGTEST_INDEXER_URL


def test_node_unlock_interactive_custom_services(runner, mocker, mock_client):
    mocker.patch("kaleido_cli.commands.node.is_interactive", return_value=True)

    result = runner.invoke(
        app,
        ["node", "unlock"],
        input=(
            "walletpw\n"
            "c\n"
            "b\n"
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
    config = _block_sync_config(req)
    assert config.bitcoind_rpc_username == "alice"
    assert config.bitcoind_rpc_password == "secret"
    assert config.bitcoind_rpc_host == "127.0.0.1"
    assert config.bitcoind_rpc_port == 18443
    assert req.indexer_url == "tcp://127.0.0.1:50001"
    assert req.announce_alias == "alias"
    assert req.announce_addresses == ["127.0.0.1:9735"]


def test_node_unlock_interactive_transaction_sync_skips_bitcoind(runner, mocker, mock_client):
    mocker.patch("kaleido_cli.commands.node.is_interactive", return_value=True)

    result = runner.invoke(
        app,
        ["node", "unlock"],
        input=("walletpw\nc\nt\ntcp://127.0.0.1:50001\nrpc://127.0.0.1:3000/json-rpc\n\n\n"),
    )

    assert result.exit_code == 0
    req = _unlock_request(mock_client)
    assert req.ldk_chain_sync.mode == "TransactionSync"
    assert req.ldk_chain_sync.config.indexer_url == "tcp://127.0.0.1:50001"
    assert req.indexer_url == "tcp://127.0.0.1:50001"


def test_node_unlock_non_interactive_transaction_sync(runner, mocker, mock_client):
    mocker.patch("kaleido_cli.commands.node.is_interactive", return_value=False)

    result = runner.invoke(
        app,
        [
            "node",
            "unlock",
            "--password",
            "walletpw",
            "--chain-sync",
            "transaction",
            "--indexer-url",
            "electrum.example.com:50001",
        ],
    )

    assert result.exit_code == 0
    req = _unlock_request(mock_client)
    assert req.ldk_chain_sync.mode == "TransactionSync"
    assert req.ldk_chain_sync.config.indexer_url == "electrum.example.com:50001"
