# Run in PowerShell AS ADMINISTRATOR on the Windows host (192.168.1.16).
# Forwards LAN traffic on :3333 and :8080 into WSL where btxpool runs.
# Re-run after WSL restarts (WSL IP can change).

$ErrorActionPreference = "Stop"

$wslIp = (wsl hostname -I).Trim().Split(" ")[0]
if (-not $wslIp) { throw "Could not read WSL IP. Is WSL running?" }

$ports = @(3333, 8080)

Write-Host "WSL IP: $wslIp"

foreach ($p in $ports) {
    netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$p 2>$null
    netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=$p connectaddress=$wslIp connectport=$p
    Write-Host "Forwarded 0.0.0.0:$p -> ${wslIp}:$p"
}

foreach ($p in $ports) {
    $rule = "BTX Pool TCP $p"
    Remove-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName $rule -Direction Inbound -LocalPort $p -Protocol TCP -Action Allow | Out-Null
    Write-Host "Firewall rule: $rule"
}

Write-Host ""
Write-Host "Miners should connect to: stratum+tcp://192.168.1.16:3333"
Write-Host "Dashboard: http://192.168.1.16:8080"
Write-Host ""
netsh interface portproxy show all