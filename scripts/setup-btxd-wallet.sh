#!/usr/bin/env bash
# Install and configure a local btxd node with wallet enabled for pool payouts.
# Usage: bash scripts/setup-btxd-wallet.sh [pool_address]
set -euo pipefail

POOL_ADDRESS="${1:-}"
BTX_VERSION="${BTX_VERSION:-0.32.5}"
# BTX default datadir on Linux is ~/.bitcoin (not ~/.btx)
INSTALL_DIR="${BTX_INSTALL_DIR:-$HOME/.bitcoin}"
CONF="$INSTALL_DIR/btx.conf"

echo "=== BTX node setup (wallet enabled) ==="

if ! command -v btxd >/dev/null 2>&1; then
  echo "btxd not found. Install from https://github.com/btxchain/btx/releases (v${BTX_VERSION})"
  echo "  Example (Linux amd64):"
  echo "    curl -LO https://github.com/btxchain/btx/releases/download/v${BTX_VERSION}/btx-${BTX_VERSION}-x86_64-linux-gnu.tar.gz"
  echo "    tar xzf btx-${BTX_VERSION}-x86_64-linux-gnu.tar.gz"
  echo "    sudo install -m 755 btx-${BTX_VERSION}/bin/btxd btx-${BTX_VERSION}/bin/btx-cli /usr/local/bin/"
  exit 1
fi

mkdir -p "$INSTALL_DIR"
if [[ ! -f "$CONF" ]]; then
  cat > "$CONF" <<EOF
server=1
rpcuser=miner
rpcpassword=miner
rpcallowip=127.0.0.1
rpcbind=127.0.0.1
rpcport=19334
txindex=1
EOF
  echo "Created $CONF"
else
  echo "Using existing $CONF"
fi

if ! grep -q '^server=1' "$CONF" 2>/dev/null; then
  echo "server=1" >> "$CONF"
fi

echo ""
echo "Start the node (first run syncs the chain — can take hours):"
echo "  btxd -datadir=$INSTALL_DIR -daemon"
echo ""
echo "Check sync:"
echo "  btx-cli -datadir=$INSTALL_DIR getblockchaininfo"
echo ""

if [[ -n "$POOL_ADDRESS" ]]; then
  echo "After sync, import the pool wallet address:"
  echo "  btx-cli -datadir=$INSTALL_DIR createwallet pool 2>/dev/null || true"
  echo "  btx-cli -datadir=$INSTALL_DIR -rpcwallet=pool getnewaddress"
  echo "  # Or import existing:"
  echo "  btx-cli -datadir=$INSTALL_DIR -rpcwallet=pool importaddress $POOL_ADDRESS '' false"
  echo ""
  echo "Verify RPC + wallet:"
  echo "  btx-cli -datadir=$INSTALL_DIR -rpcwallet=pool getbalance"
fi

echo "Point btxpool config.yaml at:"
echo "  rpc_url: \"http://127.0.0.1:19334\""
echo "  rpc_user: \"miner\""
echo "  rpc_password: \"miner\""
echo "  pool_address: \"$POOL_ADDRESS\""