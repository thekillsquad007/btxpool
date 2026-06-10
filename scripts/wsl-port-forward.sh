#!/usr/bin/env bash
# Forward Windows LAN ports into WSL (run from WSL; needs Admin PowerShell).
set -euo pipefail

WSL_IP="$(hostname -I | awk '{print $1}')"
WIN_IP="${WIN_IP:-192.168.1.16}"

echo "WSL IP: $WSL_IP"
echo "Windows LAN IP: $WIN_IP"
echo ""
echo "Run this in PowerShell AS ADMINISTRATOR on Windows:"
echo ""
cat <<EOF
powershell -ExecutionPolicy Bypass -File "$(wslpath -w "$(dirname "$0")/wsl-port-forward.ps1")"
EOF
echo ""
echo "Or permanently fix with mirrored networking in C:\\Users\\YOUR_USER\\.wslconfig:"
echo ""
cat <<'EOF'
[wsl2]
networkingMode=mirrored
EOF
echo ""
echo "Then: wsl --shutdown   (and reopen WSL)"