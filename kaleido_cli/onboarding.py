"""First-run onboarding helpers for Kaleido CLI."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import typer

from .config import load_config, save_config
from .docker_manager import DEFAULT_SPAWN_DIR, SpawnConfig, SpawnManager
from .output import print_error, print_info, print_panel, print_success


class SetupMode(str, Enum):
    market = "market"
    local = "local"


def _value_or_prompt(
    value: Any,
    label: str,
    default: Any,
    *,
    use_defaults: bool,
    type_: Any | None = None,
) -> Any:
    if value is not None:
        return value
    if use_defaults:
        return default
    prompt_kwargs: dict[str, Any] = {"default": default}
    if type_ is not None:
        prompt_kwargs["type"] = type_
    return typer.prompt(label, **prompt_kwargs)


def _confirm_or_default(
    value: bool | None,
    label: str,
    default: bool,
    *,
    use_defaults: bool,
) -> bool:
    if value is not None:
        return value
    if use_defaults:
        return default
    return typer.confirm(label, default=default)


def run_setup(
    *,
    mode: SetupMode | None,
    defaults: bool,
    api_url: str | None,
    network: str | None,
    node_url: str | None,
    create_node: bool | None,
    spawn_dir: str | None,
    env_name: str | None,
    node_count: int | None,
    start: bool | None,
) -> None:
    """Run the guided first-run setup flow."""
    config = load_config()

    print_panel(
        "Kaleido Setup",
        "Choose a market-only setup or configure a local RGB Lightning Node.\n"
        "Your answers are saved to ~/.kaleido/config.json.",
    )

    resolved_mode = mode
    if resolved_mode is None:
        if create_node or node_url is not None:
            resolved_mode = SetupMode.local
        elif defaults:
            resolved_mode = SetupMode.market
        else:
            wants_local = typer.confirm(
                "Do you want to manage a local RGB Lightning Node with Docker?",
                default=True,
            )
            resolved_mode = SetupMode.local if wants_local else SetupMode.market

    config.api_url = _value_or_prompt(
        api_url,
        "Kaleidoswap API URL",
        config.api_url,
        use_defaults=defaults,
    )
    config.network = _value_or_prompt(
        network,
        "Bitcoin network",
        config.network,
        use_defaults=defaults,
    )

    created_env_name: str | None = None
    created_env_started = False

    if resolved_mode is SetupMode.local:
        create_now_default = node_url is None
        should_create_node = _confirm_or_default(
            create_node,
            "Create a local Docker node environment now?",
            create_now_default,
            use_defaults=defaults,
        )

        if should_create_node:
            base_dir_input = _value_or_prompt(
                spawn_dir,
                "Base directory for node environments",
                config.spawn_dir or str(DEFAULT_SPAWN_DIR),
                use_defaults=defaults,
            )
            base_dir = Path(base_dir_input).expanduser().resolve()
            resolved_env_name: str = _value_or_prompt(
                env_name,
                "Environment name",
                "default",
                use_defaults=defaults,
            )
            created_env_name = resolved_env_name
            count = _value_or_prompt(
                node_count,
                "How many RGB Lightning Nodes?",
                1,
                use_defaults=defaults,
                type_=int,
            )
            created_env_started = _confirm_or_default(
                start,
                "Start the node environment now?",
                True,
                use_defaults=defaults,
            )
            env_dir = base_dir / resolved_env_name
            if (env_dir / "docker-compose.yml").exists():
                if defaults:
                    print_error(
                        f"Environment '{resolved_env_name}' already exists at {env_dir}. "
                        "Choose a different --env-name or reuse it with 'kaleido node use'."
                    )
                    raise typer.Exit(1)
                overwrite = typer.confirm(
                    f"Environment '{resolved_env_name}' already exists at {env_dir}. Overwrite?",
                    default=False,
                )
                if not overwrite:
                    print_info("Aborted.")
                    raise typer.Exit(0)

            config.spawn_dir = str(base_dir)
            save_config(config)

            manager = SpawnManager(
                SpawnConfig(
                    name=resolved_env_name,
                    count=count,
                    network=config.network,
                    disable_authentication=True,
                    spawn_base_dir=str(base_dir),
                )
            )
            rc = manager.spawn(start=created_env_started)
            if rc != 0:
                raise typer.Exit(rc)

            config.node_url = manager.node_urls()[0]
            save_config(config)
            print_success(f"Active node-url → {config.node_url}")
        else:
            config.node_url = _value_or_prompt(
                node_url,
                "RGB Lightning Node URL",
                config.node_url,
                use_defaults=defaults,
            )
            if spawn_dir is not None:
                config.spawn_dir = str(Path(spawn_dir).expanduser().resolve())
            save_config(config)
    else:
        if spawn_dir is not None:
            config.spawn_dir = str(Path(spawn_dir).expanduser().resolve())
        if node_url is not None:
            config.node_url = node_url
        save_config(config)

    print_success("Setup complete.")

    if resolved_mode is SetupMode.local:
        if created_env_name and created_env_started:
            print_panel(
                "Next Steps",
                "1. kaleido node init\n"
                "2. kaleido node unlock\n"
                "3. kaleido node info\n"
                "4. kaleido wallet address",
                style="green",
            )
        elif created_env_name:
            print_panel(
                "Next Steps",
                f"1. kaleido node up {created_env_name}\n"
                f"2. kaleido node use {created_env_name}\n"
                f"3. kaleido node init\n"
                f"4. kaleido node unlock",
                style="green",
            )
        else:
            print_panel(
                "Next Steps",
                "1. kaleido node info\n2. kaleido node unlock\n3. kaleido wallet balance",
                style="green",
            )
    else:
        print_panel(
            "Next Steps",
            "1. kaleido market pairs\n"
            "2. kaleido market assets\n"
            "3. kaleido market quote BTC/USDT --from-amount 100000",
            style="green",
        )

    print_info("Re-run 'kaleido setup' at any time to change the defaults.")
