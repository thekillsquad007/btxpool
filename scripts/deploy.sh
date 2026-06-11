#!/usr/bin/env bash
# One-shot deploy: install deps, build UI, write config, start pool.
# Usage:
#   bash scripts/deploy.sh --address btx1z...YOUR_ADDRESS
#   bash scripts/deploy.sh --address btx1z... --solver-path /path/to/btx-gbt-solve-hip
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

POOL_ADDRESS=""
DEV_ADDRESS="btx1z0069dewdztkwnrxx97lt9c5paynh0nynegqxq2kgykh0ct8xaggq0953gx"
FEE_PERCENT="1.0"
SOLVER_PATH=""
RPC_URL="http://127.0.0.1:19334"
RPC_USER=""
RPC_PASSWORD=""
START=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --address|-a) POOL_ADDRESS="$2"; shift 2 ;;
    --dev-address) DEV_ADDRESS="$2"; shift 2 ;;
    --fee-percent) FEE_PERCENT="$2"; shift 2 ;;
    --solver-path|-s) SOLVER_PATH="$2"; shift 2 ;;
    --rpc-url) RPC_URL="$2"; shift 2 ;;
    --rpc-user) RPC_USER="$2"; shift 2 ;;
    --rpc-password) RPC_PASSWORD="$2"; shift 2 ;;
    --no-start) START=0; shift ;;
    -h|--help)
      echo "Usage: bash scripts/deploy.sh --address btx1z... [--solver-path PATH] [--rpc-url URL] [--no-start]"
      exit 0
      ;;
    btx1*) POOL_ADDRESS="$1"; shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

if [[ -z "$POOL_ADDRESS" ]]; then
  echo "Error: --address btx1z... is required"
  exit 1
fi

if [[ -z "$SOLVER_PATH" ]]; then
  for candidate in \
    "$HOME/.amdbtx-miner/bin/btx-gbt-solve-hip" \
    "$HOME/.amdbtx-miner/bin/btx-gbt-solve" \
    "$HOME/amdbtx/amdbtx-private-solver/build/btx-gbt-solve-hip" \
    "$ROOT/../amdbtx/amdbtx-private-solver/build/btx-gbt-solve-hip"; do
    if [[ -f "$candidate" ]]; then
      SOLVER_PATH="$candidate"
      break
    fi
  done
fi

echo "[1/4] Python environment..."
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -e .

echo "[2/4] Frontend..."
if command -v npm >/dev/null 2>&1; then
  (cd frontend && npm install -q && npm run build -s)
else
  echo "  npm not found — skipping UI build (API still works on :8080)"
fi

echo "[3/4] config.yaml..."
cat > config.yaml <<EOF
pool_name: "BTX Family Pool"
stratum_host: "0.0.0.0"
stratum_port: 3333
api_host: "0.0.0.0"
api_port: 8080
rpc_url: "$RPC_URL"
EOF

if [[ -n "$RPC_USER" && -n "$RPC_PASSWORD" ]]; then
  cat >> config.yaml <<EOF
rpc_user: "$RPC_USER"
rpc_password: "$RPC_PASSWORD"
EOF
fi

cat >> config.yaml <<EOF
pool_address: "$POOL_ADDRESS"
payment_mode: "pplns"
pool_fee_percent: $FEE_PERCENT
dev_fee_address: "$DEV_ADDRESS"
payout_interval_hours: 24
min_payout_sats: 500000000
payout_enabled: true
default_difficulty: 0.001
solver_path: "$SOLVER_PATH"
solver_backend: "cpu"
database_path: "data/pool.db"
log_level: "INFO"
EOF

mkdir -p data

echo "[4/4] Ready."
echo "  Stratum :3333"
echo "  Dashboard :8080"
echo "  Pool address: $POOL_ADDRESS"
if [[ -n "$SOLVER_PATH" ]]; then
  echo "  Solver: $SOLVER_PATH"
else
  echo "  Solver: not found — build amdbtx (bash build_solver.sh) and set solver_path in config.yaml"
fi

if [[ "$START" -eq 1 ]]; then
  echo "Starting pool..."
  exec .venv/bin/btxpool -c config.yaml
fi