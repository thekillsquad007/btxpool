# Expose btxpool Stratum (TCP :3333) through Netbird for remote miners.
# Run on the WINDOWS HOST (where Netbird runs), in PowerShell AS ADMINISTRATOR.
#
# Prerequisite: pool runs in WSL — forward Windows :3333 into WSL first:
#   .\scripts\wsl-port-forward.ps1
#
# Option A — permanent (recommended): NetBird Dashboard
#   Networks > Reverse proxy > Add service
#   Mode: TCP
#   Domain: btx.eu1.netbird.services (or your custom domain)
#   External port: 46449  (or 3333 if your cluster allows it)
#   Target: this Windows peer
#   Target port: 3333
#   Status must be "active" (not HTTP — Stratum is raw TCP)
#
# Option B — quick test (ephemeral; stops when this window closes):
#   netbird expose --protocol tcp --with-external-port 46449 3333
#   Or with custom domain (if configured in Netbird):
#   netbird expose --protocol tcp --with-custom-domain btx.eu1.netbird.services --with-external-port 46449 3333
#
# Remote miner (public internet, no Netbird client on rig):
#   btx-miner --pool stratum+tcp://btx.eu1.netbird.services:46449 --user btx1z....worker --pass x
#
# Remote miner (on same Netbird mesh — install netbird on the rig):
#   btx-miner --pool stratum+tcp://100.119.5.72:3333 --user btx1z....worker --pass x

$ErrorActionPreference = "Stop"

Write-Host "=== BTX pool Stratum / Netbird checklist ===" -ForegroundColor Cyan
Write-Host ""

# 1. WSL port forward
$wslIp = (wsl hostname -I 2>$null).Trim().Split(" ")[0]
if (-not $wslIp) {
    Write-Host "[FAIL] WSL not running. Start WSL and btxpool first." -ForegroundColor Red
    exit 1
}
Write-Host "[OK]   WSL IP: $wslIp"

$proxy = netsh interface portproxy show v4tov4 2>$null | Select-String ":3333"
if ($proxy) {
    Write-Host "[OK]   Portproxy for :3333 exists"
    Write-Host "       $proxy"
} else {
    Write-Host "[WARN] No portproxy for :3333. Run: .\scripts\wsl-port-forward.ps1" -ForegroundColor Yellow
}

# 2. Local listen test (Windows side)
try {
    $tcp = New-Object System.Net.Sockets.TcpClient
    $tcp.Connect("127.0.0.1", 3333)
    $tcp.Close()
    Write-Host "[OK]   TCP 127.0.0.1:3333 accepts connections"
} catch {
    Write-Host "[FAIL] Nothing listening on Windows :3333 (portproxy missing or pool down?)" -ForegroundColor Red
}

# 3. Netbird status
$nb = Get-Command netbird -ErrorAction SilentlyContinue
if ($nb) {
    Write-Host ""
    Write-Host "Netbird status:" -ForegroundColor Cyan
    netbird status 2>$null
} else {
    Write-Host "[WARN] netbird CLI not in PATH on this host" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Why HTTPS dashboard works but Stratum fails:" -ForegroundColor Cyan
Write-Host "  Dashboard = Netbird HTTP reverse proxy (TLS on 443)"
Write-Host "  Stratum   = raw TCP — needs a separate TCP service on 46449 or mesh IP :3333"
Write-Host ""
Write-Host "Test from a remote machine:" -ForegroundColor Cyan
Write-Host "  nc -zv btx.eu1.netbird.services 46449    # must succeed before miners connect"
Write-Host "  nc -zv 100.119.5.72 3333                 # only if rig has Netbird client"
Write-Host ""
Write-Host "Start ephemeral TCP expose (keep this window open):" -ForegroundColor Cyan
Write-Host "  netbird expose --protocol tcp --with-external-port 46449 3333"