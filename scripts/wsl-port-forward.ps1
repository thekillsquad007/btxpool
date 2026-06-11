# Run in PowerShell AS ADMINISTRATOR on the Windows host.
# Forwards LAN / Netbird traffic on :3333 and :8080 into WSL where btxpool runs.
# Re-run after WSL restarts (WSL IP can change).

param(
    [string]$LanIp = "192.168.1.16"
)

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$isAdmin = Test-IsAdmin
if (-not $isAdmin) {
    Write-Host "NOTE: Not running as Administrator." -ForegroundColor Yellow
    Write-Host "      Portproxy may fail; firewall rules will be skipped." -ForegroundColor Yellow
    Write-Host "      Right-click PowerShell -> Run as administrator, then re-run this script." -ForegroundColor Yellow
    Write-Host ""
}

$wslIp = (wsl hostname -I 2>$null).Trim().Split(" ")[0]
if (-not $wslIp) { throw "Could not read WSL IP. Is WSL running?" }

$ports = @(3333, 8080)

Write-Host "WSL IP: $wslIp"

foreach ($p in $ports) {
    netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$p 2>$null | Out-Null
    $null = netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=$p connectaddress=$wslIp connectport=$p 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] portproxy :$p" -ForegroundColor Red
    } else {
        Write-Host "[OK]   Forwarded 0.0.0.0:$p -> ${wslIp}:$p" -ForegroundColor Green
    }
}

if ($isAdmin) {
    foreach ($p in $ports) {
        $rule = "BTX Pool TCP $p"
        Remove-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue
        New-NetFirewallRule -DisplayName $rule -Direction Inbound -LocalPort $p -Protocol TCP -Action Allow -ErrorAction Stop | Out-Null
        Write-Host "[OK]   Firewall rule: $rule" -ForegroundColor Green
    }
} else {
    Write-Host "[SKIP] Firewall rules (requires Administrator)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Miners on LAN:  stratum+tcp://${LanIp}:3333"
Write-Host "Dashboard:      http://${LanIp}:8080"
Write-Host "Netbird mesh:   stratum+tcp://NETBIRD_PEER_IP:3333"
Write-Host "Netbird public: stratum+tcp://btx.eu1.netbird.services:46449"
Write-Host ""
netsh interface portproxy show all