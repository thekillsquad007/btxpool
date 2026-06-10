# BTX Pool

Self-hosted mining pool for [BTX](https://github.com/btxchain/btx) (MatMul PoW). Connect all your rigs through a single Stratum endpoint, compatible with the [amdbtx](https://github.com/thekillsquad007/amdbtx) AMD GPU miner.

## Features

- **Stratum v1** — `mining.subscribe`, `mining.authorize`, `mining.notify`, `mining.submit`, `mining.set_difficulty`, `mining.set_canonical_name`
- **MatMul jobs** — seeds, epsilon_bits, share targets (amdbtx `pre_hash_block_tier_v18` protocol)
- **btxd integration** — `getblocktemplate`, `getmatmulchallenge`, `submitblock`
- **Web dashboard** — live miners, shares, blocks, connection instructions
- **SQLite stats** — per-miner share tracking
- **Vardiff** — automatic per-miner difficulty tuning

## Requirements

1. **Synced BTX node** (`btxd` v0.32.3+) with RPC enabled
2. **Python 3.10+**
3. **CPU solver** for share verification (build once from amdbtx)
4. **Node.js 18+** (only to build the frontend)

## Quick start

### 1. Wait for btxd to sync

```bash
btx-cli getblockchaininfo
# "initialblockdownload": false  →  ready to mine
```

Ensure `server=1` in `~/.btx/btx.conf` and RPC is reachable.

### 2. Build the CPU solver (pool server)

```bash
git clone https://github.com/thekillsquad007/amdbtx.git
cd amdbtx
bash build_solver.sh
# Binary: amdbtx-private-solver/build/btx-gbt-solve-hip
```

The pool uses `--backend cpu` for share verification (no GPU required on the pool host).

### 3. Configure the pool

```bash
cd btxpool
cp config.example.yaml config.yaml
# Edit pool_address, rpc credentials, solver_path
```

### 4. Install and run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Build dashboard (optional — API works without it)
cd frontend && npm install && npm run build && cd ..

# Start pool (Stratum :3333, API/dashboard :8080)
btxpool -c config.yaml
```

### 5. Connect miners

**amdbtx** (`~/.amdbtx-miner/config.yaml`):

```yaml
mining_mode: "pool"
pool_host: "192.168.1.100"   # your pool server IP
pool_port: 3333
payout_address: "btx1z...YOUR_ADDRESS"
worker_name: "rig-1"
```

Or point any Stratum client at `stratum+tcp://YOUR_IP:3333` with username = your `btx1z...` address.

Open **http://YOUR_IP:8080** for the dashboard.

## Architecture

```
┌─────────────┐     Stratum :3333     ┌──────────────┐     RPC      ┌──────┐
│  amdbtx     │ ────────────────────► │   btxpool    │ ───────────► │ btxd │
│  (GPU rigs) │                       │  Stratum+API │              └──────┘
└─────────────┘                       └──────────────┘
                                            │
                                      HTTP :8080
                                            ▼
                                      Dashboard
```

- Pool builds block templates with coinbase paid to `pool_address`
- Miners authorize with their payout address (tracked for stats)
- Shares verified by recomputing MatMul digest via CPU solver
- Blocks submitted via `submitblock` when a share meets network difficulty

## Configuration reference

| Key | Default | Description |
|-----|---------|-------------|
| `pool_address` | — | BTX address receiving block rewards |
| `stratum_port` | 3333 | Stratum listen port |
| `api_port` | 8080 | Dashboard + REST API |
| `default_difficulty` | 0.01 | Initial share difficulty |
| `solver_path` | — | Path to `btx-gbt-solve-hip` binary |
| `solver_backend` | cpu | Solver backend for verification |

Environment overrides: `BTXPOOL_POOL_ADDRESS`, `BTXPOOL_CONFIG`, etc.

## API endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/pool` | Pool + chain status |
| `GET /api/miners` | Connected miners |
| `GET /api/shares` | Recent accepted shares |
| `GET /api/blocks` | Blocks found by pool |
| `GET /api/job` | Current mining job |

## Development

```bash
# Frontend dev server (proxies API to :8080)
cd frontend && npm run dev

# Pool in another terminal
btxpool -c config.yaml
```

## License

GPL-3.0-or-later