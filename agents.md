# BTX Pool — Agent Handoff

Self-hosted BTX MatMul mining pool with PPLNS payouts. Repo: `thekillsquad007/btxpool` on GitHub.

## Current state (2026-06-11)

| Item | Status |
|------|--------|
| Git `main` | `4376cc0` — PPLNS + Vercel dashboard deploy |
| `btxd` | **Stopped** (was started on `~/.bitcoin` during setup; do not leave running unless operator intends it) |
| `btxpool` | Not running |
| Chain sync | `~/.bitcoin` ~53GB blocks, was half-synced / verifying at last check |
| Payouts | `payout_dry_run: true` in local `config.yaml` — no real sends until disabled |
| Pool blocks found | 0 (small pool, high variance) |

## Architecture (important)

**Cannot run full pool on Vercel.** Split deployment:

```
Miners ──Stratum :3333──► Pool host (WSL / home PC)
                              ├── btxpool (Python): API :8080, Stratum, PPLNS, payouts
                              └── btxd RPC :19334 (wallet enabled)

Vercel (optional) ──HTTPS──► Dashboard UI only (frontend/)
         POOL_API_ORIGIN proxies /api → pool host :8080
```

| Component | Location |
|-----------|----------|
| Stratum, share verify, PPLNS, SQLite | `pool/` on pool machine |
| Dashboard (production) | Vercel — root dir `frontend/` |
| `btxd` + wallet | Pool machine, datadir **`~/.bitcoin`** |

See `docs/VERCEL_DEPLOY.md` for Vercel env vars (`POOL_API_ORIGIN`).

## Key paths

| Path | Purpose |
|------|---------|
| `/mnt/e/Business/btxpool/` | Repo (WSL) |
| `config.yaml` | Live config (**gitignored**) |
| `config.example.yaml` | Template |
| `data/pool.db` | SQLite (**gitignored**) |
| `pool/pplns.py` | PPLNS crediting + maturity poller |
| `pool/payouts.py` | 24h payout worker |
| `frontend/` | React dashboard → Vercel |
| `~/.bitcoin/` | **Canonical** btxd datadir (~53GB chain) |
| `~/.bitcoin/btx.conf` | RPC: `miner`/`miner`, `server=1`, `txindex=1` |
| `~/.local/btx/bin/btxd` | Installed btxd v0.32.9 |
| `~/.amdbtx-miner/bin/btx-gbt-solve-hip` | CPU share verifier (from amdbtx) |

**Do not use `~/.btx`** for production — that was a fresh empty chain started by mistake during setup; stopped and abandoned.

## Operator wallet

- Pool / dev fee address: `btx1z0069dewdztkwnrxx97lt9c5paynh0nynegqxq2kgykh0ct8xaggq0953gx`
- Fee: **1%** via PPLNS (`pool_fee_percent: 1.0`)
- Payouts: every **24h**, min **5 BTX** (`min_payout_sats: 500000000`)
- Same address for `pool_address` and `dev_fee_address` → fee stays in hot wallet (no coinbase split)

## Payment flow (PPLNS)

1. Block accepted → `PplnsEngine.credit_block()` in `pool/pplns.py`
2. Window = `network_difficulty × pplns_window_multiplier` (sum of share difficulties)
3. Credits per **wallet address** → `miner_balances.immature_sats`
4. Maturity thread (60s) moves to `balance_sats` after `coinbase_maturity` (100) confs
5. `PayoutWorker` every 24h → `sendtoaddress` if balance ≥ min

## Miners

| Client | Repo |
|--------|------|
| AMD | https://github.com/thekillsquad007/amdbtx |
| NVIDIA | https://github.com/thekillsquad007/btx-nvidia-miner |

- Stratum username = `btx1z...` payout address (optional `.worker`)
- **Nonce/s inflation fix** in `41f8115` — prefer share-work hashrate; btx-nvidia-miner may still over-report metrics

## Common commands

```bash
# Node (only when operator wants it running)
~/.local/btx/bin/btxd -datadir=$HOME/.bitcoin -daemon
~/.local/btx/bin/btx-cli -datadir=$HOME/.bitcoin getblockchaininfo
~/.local/btx/bin/btx-cli -datadir=$HOME/.bitcoin stop

# Pool
cd /mnt/e/Business/btxpool
source .venv/bin/activate
btxpool -c config.yaml

# Frontend / Vercel
cd frontend && npm run build
# Vercel: root=frontend, env POOL_API_ORIGIN=https://tunnel-to-pool:8080

# Tests
pytest tests/
```

## Config notes (`config.yaml`)

- `rpc_url: http://127.0.0.1:19334` — local node (was `192.168.1.15` before)
- `payout_dry_run: true` — **flip to `false` only when** node synced, wallet funded, `sendtoaddress` tested
- `solver_path` + `solver_runtime_ld_path` required for share validation

## API endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/pool` | Pool + chain + payment settings |
| `GET /api/wallet/{address}` | Per-wallet balance, workers, credits |
| `GET /api/miners` | All workers |
| `GET /api/payouts` | Payout history |

Wallet UI: `/wallet/btx1z...` (SPA on Vercel or pool :8080).

## Open / follow-up work

1. **Finish `~/.bitcoin` sync** — pool mines only when `initialblockdownload: false`
2. **Import pool address** into wallet: `btx-cli -datadir=$HOME/.bitcoin -rpcwallet=pool importaddress ...`
3. **Expose API** for Vercel — Cloudflare Tunnel or port forward to :8080; set `POOL_API_ORIGIN` on Vercel
4. **Expose Stratum :3333** for public miners (separate from Vercel)
5. **Disable `payout_dry_run`** after wallet + maturity tested
6. Optional: push amdbtx metrics fixes to GitHub; fix btx-nvidia-miner nonce/s reporting

## Docs in repo

- `README.md` — operator + miner quick start
- `docs/PRODUCTION_PLAN.md` — original PPLNS implementation plan
- `docs/VERCEL_DEPLOY.md` — dashboard-only Vercel setup
- `scripts/setup-btxd-wallet.sh` — node + wallet bootstrap
- `scripts/deploy.sh` — one-shot local deploy

## Git

- Remote: `origin` → `https://github.com/thekillsquad007/btxpool.git`
- Branch: `main`
- Do not commit: `config.yaml`, `data/`, `*.db`, `frontend/node_modules/`, `frontend/dist/`

## WSL / networking

- Pool often runs in WSL; miners on LAN use Windows host IP for Stratum
- Scripts: `scripts/wsl-port-forward.ps1`, `scripts/netbird-stratum.ps1` (Windows side)
