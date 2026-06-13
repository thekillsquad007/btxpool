# BTX Pool

Production-ready self-hosted mining pool for [BTX](https://github.com/btxchain/btx) (MatMul PoW). **PPLNS** payouts, per-wallet worker dashboard, and Stratum compatible with [amdbtx](https://github.com/thekillsquad007/amdbtx) (AMD) and [btx-nvidia-miner](https://github.com/thekillsquad007/btx-nvidia-miner) (NVIDIA).

## Features

- **PPLNS payments** — rewards split by share work in the last N difficulty window
- **1% pool fee** (configurable) — retained by operator; credited miners receive 99%
- **Automatic payouts** — every 24 hours by default, minimum **5 BTX**
- **Per-wallet dashboard** — `/wallet/btx1z...` shows balance, workers, credits, payout history
- **Stratum v1** — `mining.subscribe`, `mining.authorize`, `mining.notify`, `mining.submit`, `mining.set_difficulty`
- **MatMul jobs** — seeds, epsilon_bits, share targets (amdbtx protocol)
- **btxd integration** — `getblocktemplate`, `getmatmulchallenge`, `submitblock`, `sendtoaddress`
- **Vardiff** — automatic per-miner difficulty tuning
- **SQLite ledger** — shares, PPLNS rounds, balances, payouts

## Requirements

1. **Synced BTX node** (`btxd` v0.32.7+) with RPC **and wallet** enabled
2. **Python 3.10+**
3. **CPU solver** for share verification (build once from amdbtx)
4. **Node.js 18+** (to build the frontend)

## Quick start

### 1. Set up btxd with wallet

BTX stores chain data in **`~/.bitcoin`** by default.

```bash
bash scripts/setup-btxd-wallet.sh btx1zYOUR_POOL_ADDRESS
btxd -datadir=$HOME/.bitcoin -daemon
btx-cli -datadir=$HOME/.bitcoin getblockchaininfo
# "initialblockdownload": false  →  ready to mine
```

Ensure `server=1` in `~/.btx/btx.conf`. The pool hot wallet (`pool_address`) must be importable in the node wallet for payouts.

### 2. Build the CPU solver (pool server)

```bash
git clone https://github.com/thekillsquad007/amdbtx.git
cd amdbtx
bash build_solver.sh
# Binary: amdbtx-private-solver/build/btx-gbt-solve-hip
```

### 3. Configure the pool

```bash
cd btxpool
cp config.example.yaml config.yaml
# Edit pool_address, dev_fee_address, rpc credentials, solver_path
```

Key payment settings:

| Key | Default | Description |
|-----|---------|-------------|
| `payment_mode` | `pplns` | Payment scheme |
| `pool_fee_percent` | `1.0` | Fee deducted from block rewards before PPLNS |
| `dev_fee_address` | — | Operator fee address (can match `pool_address`) |
| `payout_interval_hours` | `24` | Hours between payout runs |
| `min_payout_sats` | `500000000` | Minimum payout (5 BTX) |
| `coinbase_maturity` | `100` | Confirmations before balance is payable |

### 4. Install and run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cd frontend && npm install && npm run build && cd ..

btxpool -c config.yaml
```

Stratum **:3333**, dashboard **:8080** (local), or **Vercel** for public dashboard — see [docs/VERCEL_DEPLOY.md](docs/VERCEL_DEPLOY.md).

### 5. Connect miners

Miners authorize with their **payout wallet** as the Stratum username. Worker name is optional (`address.worker`).

**amdbtx** (`~/.amdbtx-miner/config.yaml`):

```yaml
mining_mode: "pool"
pool_host: "192.168.1.100"
pool_port: 3333
payout_address: "btx1z...YOUR_ADDRESS"
worker_name: "rig-1"
```

**btx-nvidia-miner**:

```bash
btx-miner --pool stratum+tcp://192.168.1.100:3333 \
  --user btx1z...YOUR_ADDRESS.rig01 --pass x --devices all
```

### 6. Miner wallet dashboard

Open **http://YOUR_IP:8080** and enter your `btx1z...` address, or go directly to:

**http://YOUR_IP:8080/wallet/btx1z...YOUR_ADDRESS**

Shows payable balance, immature credits, workers, PPLNS history, and payouts.

## How PPLNS works

1. Block found → pool submits to `btxd`, reward lands in `pool_address`
2. PPLNS engine walks recent shares until window work ≥ `network_difficulty × multiplier`
3. Each wallet receives `(share_work / window_work) × reward × (1 - fee%)`
4. Credits start **immature** until `coinbase_maturity` confirmations
5. Mature balance is paid on the 24h schedule if ≥ 5 BTX

## Architecture

```
┌──────────────┐   Stratum :3333   ┌──────────────┐    RPC     ┌──────┐
│ amdbtx       │ ────────────────► │   btxpool    │ ─────────► │ btxd │
│ btx-nvidia   │                   │ PPLNS+payout │  (wallet)  └──────┘
└──────────────┘                   └──────────────┘
                                         │ HTTP :8080
                                         ▼
                                   Pool + wallet UI
```

## API endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/pool` | Pool + chain + payment settings |
| `GET /api/miners` | All workers |
| `GET /api/wallet/{address}` | Per-wallet balance, workers, credits |
| `GET /api/payouts` | Payout history (`?address=`) |
| `GET /api/rounds` | PPLNS rounds |
| `GET /api/shares` | Recent shares |
| `GET /api/blocks` | Blocks found |

## Testing payouts

Set `payout_dry_run: true` in `config.yaml` to simulate payouts without sending coins.

```bash
pytest tests/
```

## One-shot deploy

```bash
bash scripts/deploy.sh --address btx1z...YOUR_ADDRESS --fee-percent 1
```

## License

GPL-3.0-or-later
