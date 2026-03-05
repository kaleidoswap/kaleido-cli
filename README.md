# Kaleido CLI

A command-line interface for managing RGB Lightning Nodes and interacting with the [Kaleidoswap](https://kaleidoswap.com) protocol.

## Overview

`kaleido` covers two main areas:

- **RGB Lightning Node (RLN)** — spin up Docker-based node environments, manage your BTC wallet, RGB assets, Lightning channels, peers, and payments.
- **Kaleidoswap API** — query market data (assets, trading pairs, quotes) and execute atomic RGB+Lightning swaps.

---

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) **or** pip
- Docker & Docker Compose (required for `node` commands)

---

## Installation

### Using `uv` (recommended)

```bash
git clone https://github.com/kaleidoswap/kaleido-cli
cd kaleido-cli

# Install globally so the `kaleido` command is available system-wide
make install
```

The `--editable` flag means local code changes take effect immediately without reinstalling.

### Using pip

```bash
pip install .
```

### Makefile targets

| Command          | Description                        |
|------------------|------------------------------------|
| `make install`   | Install CLI globally via `uv tool` |
| `make uninstall` | Remove the global installation     |
| `make reinstall` | Uninstall then reinstall           |

---

## Initial Configuration

Configuration is stored in `~/.kaleido/config.json` and created automatically on first use.

```bash
kaleido config show                              # view current config
kaleido config set api-url https://api.kaleidoswap.com
kaleido config set network signet
kaleido config reset                             # reset to defaults
```

Override per-command with flags or environment variables:

```bash
kaleido --node-url http://localhost:3001 wallet balance
kaleido --api-url https://api.kaleidoswap.com market pairs

export KALEIDO_NODE_URL=http://localhost:3001
export KALEIDO_API_URL=https://api.kaleidoswap.com
```

Valid config keys: `api-url`, `node-url`, `network`, `spawn-dir`

---

## Node Environments

The CLI uses a **named environment** model. Each environment is an isolated Docker Compose setup with its own compose file and data volumes stored under a base directory (default: `~/.kaleido/spawn/`).

```
~/.kaleido/spawn/
├── mainenv/
│   ├── docker-compose.yml
│   └── volumes/
│       └── dataldk0/
└── testenv/
    ├── docker-compose.yml
    └── volumes/
        ├── dataldk0/
        └── dataldk1/
```

### Creating an environment

```bash
kaleido node create
# or give it a name directly:
kaleido node create testenv
```

The wizard prompts for:

1. **Base directory** — where all environments are stored (saved to config as `spawn-dir`)
2. **Environment name** — becomes a subdirectory under the base dir
3. **Node count** — number of RGB Lightning Nodes to spin up
4. **Network** — `regtest`, `signet`, or `mainnet`
5. **Full infra stack** — optionally include bitcoind, electrs, and RGB proxy
   - If yes: RPC username, password (auto-generated if left blank), and ports for each service
6. **Node ports** — base daemon API port (3001+) and LDK peer port (9735+)
7. **Start now** — whether to bring containers up immediately

### Managing environments

```bash
kaleido node list                   # list all environments with their node URLs
kaleido node up     <name>          # start containers (docker compose up -d)
kaleido node stop   <name>          # stop containers (data preserved)
kaleido node down   <name>          # stop and remove containers
kaleido node ps     <name>          # show container status
kaleido node logs   <name>          # stream all logs
kaleido node logs   <name> --service bitcoind   # filter by service
kaleido node clean  <name>          # delete all data volumes (irreversible)
```

`<name>` can be omitted when only one environment exists — it is auto-detected.

### Switching between nodes

Use `kaleido node use` to point the active `node-url` at any node in any environment:

```bash
kaleido node use testenv            # use node 1 of 'testenv' (port 3001)
kaleido node use testenv --node 2   # use node 2 of 'testenv' (port 3002)
```

`kaleido node list` marks the currently active node with `●`:

```
Environments in ~/.kaleido/spawn:

  testenv  →  ~/.kaleido/spawn/testenv
    ● node 1: http://localhost:3001
    ○ node 2: http://localhost:3002
```

### First-time node setup

After creating and starting an environment:

```bash
kaleido node use testenv            # set the active node URL
kaleido node init                   # initialise the wallet (once per node)
kaleido node unlock                 # unlock the wallet (after every restart)
kaleido node status                 # confirm the node is reachable
```

---

## Command Reference

All commands accept `--json` for machine-readable output:

```bash
kaleido --json market pairs
```

### `node` — Node lifecycle

| Command                                   | Description                                         |
|-------------------------------------------|-----------------------------------------------------|
| `kaleido node create [name]`              | Wizard: configure and generate a named environment  |
| `kaleido node list`                       | List all environments with node URLs                |
| `kaleido node use <name> [--node N]`      | Set node-url to node N in an environment            |
| `kaleido node up <name>`                  | Start containers (docker compose up -d)             |
| `kaleido node stop <name>`                | Stop containers (data preserved)                    |
| `kaleido node down <name>`                | Stop and remove containers + networks               |
| `kaleido node ps <name>`                  | Show container status                               |
| `kaleido node logs <name> [--service S]`  | Stream logs (optionally filtered by service)        |
| `kaleido node clean <name>`               | Delete all data volumes (irreversible)              |
| `kaleido node init`                       | Initialise node wallet (once after first start)     |
| `kaleido node unlock`                     | Unlock wallet (after every restart)                 |
| `kaleido node lock`                       | Lock the wallet                                     |
| `kaleido node status`                     | Check node health                                   |
| `kaleido node info`                       | Show detailed node + network info                   |

### `wallet` — BTC wallet

| Command                                  | Description                        |
|------------------------------------------|------------------------------------|
| `kaleido wallet address`                 | Get a new on-chain deposit address |
| `kaleido wallet balance`                 | Show BTC balance                   |
| `kaleido wallet send <amount> <address>` | Send on-chain BTC (sats)           |

### `asset` — RGB assets

| Command                              | Description                            |
|--------------------------------------|----------------------------------------|
| `kaleido asset list`                 | List all RGB assets held by the node   |
| `kaleido asset balance <asset-id>`   | Show balance for a specific RGB asset  |
| `kaleido asset metadata <asset-id>`  | Show metadata for a specific RGB asset |

### `channel` — Lightning channels

| Command                               | Description                      |
|---------------------------------------|----------------------------------|
| `kaleido channel list`                | List all Lightning channels      |
| `kaleido channel open <peer>`         | Open a new channel               |
| `kaleido channel close <channel-id>`  | Close a channel                  |

### `peer` — Peer connections

| Command                            | Description               |
|------------------------------------|---------------------------|
| `kaleido peer list`                | List connected peers      |
| `kaleido peer connect <peer>`      | Connect to a peer         |
| `kaleido peer disconnect <pubkey>` | Disconnect from a peer    |

### `payment` — Lightning payments

| Command                          | Description                             |
|----------------------------------|-----------------------------------------|
| `kaleido payment invoice`        | Create a BOLT11 invoice (BTC or RGB+LN) |
| `kaleido payment send <invoice>` | Pay a BOLT11 invoice                    |
| `kaleido payment list`           | List payment history                    |

### `market` — Kaleidoswap market data

| Command                           | Description                           |
|-----------------------------------|---------------------------------------|
| `kaleido market assets`           | List all tradeable assets             |
| `kaleido market pairs`            | List all available trading pairs      |
| `kaleido market quote <pair>`     | Get a swap quote for a trading pair   |

```bash
# Send BTC via Lightning, receive USDT via RGB Lightning
kaleido market quote BTC/USDT --from-amount 100000 --from-layer BTC_LN --to-layer RGB_LN
```

### `swap` — Atomic swaps

| Command                     | Description                                 |
|-----------------------------|---------------------------------------------|
| `kaleido swap quote <pair>` | Get a swap quote (alias for `market quote`) |
| `kaleido swap history`      | List past swaps                             |
| `kaleido swap status <id>`  | Check the status of a specific swap         |

### `config` — CLI configuration

| Command                            | Description                     |
|------------------------------------|---------------------------------|
| `kaleido config show`              | Display current configuration   |
| `kaleido config set <key> <value>` | Set a configuration value       |
| `kaleido config reset`             | Reset configuration to defaults |
| `kaleido config path`              | Print the config file path      |

---

## Quick Start

```bash
# 1. Install
make install

# 2. Create a local regtest environment with full infra
kaleido node create testenv
#   → wizard: choose base dir, node count, ports, bitcoind creds, etc.
#   → answer "yes" to "Start containers now?"

# 3. Point the CLI at the new node
kaleido node use testenv

# 4. Initialise and unlock the wallet
kaleido node init
kaleido node unlock

# 5. Check the node is healthy
kaleido node status

# 6. Fund the wallet (regtest: mine blocks externally or use faucet)
kaleido wallet address

# 7. Browse available trading pairs
kaleido market pairs

# 8. Get a swap quote
kaleido market quote BTC/USDT --from-amount 100000
```

### Working with multiple nodes

```bash
# Create a second environment on different ports
kaleido node create stagingenv

# See all environments and which node is active
kaleido node list

# Switch to node 2 in the staging environment
kaleido node use stagingenv --node 2
kaleido node unlock
kaleido wallet balance
```
