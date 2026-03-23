"""Global application context and state management."""

from __future__ import annotations

import typer
from kaleido_sdk import KaleidoClient

from .config import CliConfig
from .output import print_error


class _State:
    config: CliConfig = None  # type: ignore[assignment]
    node_url: str | None = None
    api_url: str | None = None


state = _State()


def get_client(*, require_node: bool = False) -> KaleidoClient:
    """Build a KaleidoClient from current state."""
    node_url = state.node_url or state.config.node_url or None
    api_url = state.api_url or state.config.api_url

    if require_node and not node_url:
        print_error("Node URL not configured.")
        print_error("Use --node-url or: kaleido config set node-url http://localhost:3001")
        raise typer.Exit(1)

    return KaleidoClient.create(
        base_url=api_url,
        node_url=node_url,
    )
