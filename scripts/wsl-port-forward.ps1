# Run in PowerShell AS ADMINISTRATOR on the Windows host.
# Forwards Stratum and the LAN-only dashboard into WSL where btxpool runs.
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

$ports = @(3333, 8080, 19335)

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
    $stratumRule = "BTX Pool TCP 3333"
    Remove-NetFirewallRule -DisplayName $stratumRule -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName $stratumRule -Direction Inbound `
        -LocalPort 3333 -Protocol TCP -Action Allow -Profile Any `
        -ErrorAction Stop | Out-Null
    Write-Host "[OK]   Public firewall rule: $stratumRule" -ForegroundColor Green

    $apiRule = "BTX Pool TCP 8080"
    Remove-NetFirewallRule -DisplayName $apiRule -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName $apiRule -Direction Inbound `
        -LocalPort 8080 -Protocol TCP -Action Allow -Profile Private `
        -RemoteAddress LocalSubnet -ErrorAction Stop | Out-Null
    Write-Host "[OK]   LAN-only firewall rule: $apiRule" -ForegroundColor Green

    $nodeRule = "BTX Node TCP 19335"
    Remove-NetFirewallRule -DisplayName $nodeRule -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName $nodeRule -Direction Inbound `
        -LocalPort 19335 -Protocol TCP -Action Allow -Profile Any `
        -ErrorAction Stop | Out-Null
    Write-Host "[OK]   Public node rule: $nodeRule" -ForegroundColor Green

    $legacyHttpsRule = "BTX Pool HTTPS TCP 80 443"
    Remove-NetFirewallRule -DisplayName $legacyHttpsRule -ErrorAction SilentlyContinue
    $httpsRule = "BTX Pool HTTPS TCP 8443"
    Remove-NetFirewallRule -DisplayName $httpsRule -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName $httpsRule -Direction Inbound `
        -LocalPort 8443 -Protocol TCP -Action Allow -Profile Any `
        -ErrorAction Stop | Out-Null
    Write-Host "[OK]   Public HTTPS rule: $httpsRule" -ForegroundColor Green
} else {
    Write-Host "[SKIP] Firewall rules (requires Administrator)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Miners on LAN:  stratum+tcp://${LanIp}:3333"
Write-Host "Dashboard (LAN only): http://${LanIp}:8080"
Write-Host "Dashboard (public):   https://btxfamilypool.duckdns.org:8443"
Write-Host "Netbird mesh:   stratum+tcp://NETBIRD_PEER_IP:3333"
Write-Host "Netbird public: stratum+tcp://btx.eu1.netbird.services:46449"
Write-Host ""
netsh interface portproxy show all
