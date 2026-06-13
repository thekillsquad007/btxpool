param(
    [string]$InstallDir = "$env:LOCALAPPDATA\btxpool\caddy",
    [string]$Config = (Join-Path $PSScriptRoot "..\Caddyfile")
)

$ErrorActionPreference = "Stop"
$caddy = Join-Path $InstallDir "caddy.exe"
$tokenFile = Join-Path $InstallDir "duckdns-token"
$logDir = Join-Path $env:LOCALAPPDATA "btxpool\logs"
$stdoutLog = Join-Path $logDir "caddy.log"
$stderrLog = Join-Path $logDir "caddy-error.log"

if (-not (Test-Path -LiteralPath $caddy)) {
    throw "Caddy is not installed at $caddy"
}
if (-not (Test-Path -LiteralPath $tokenFile)) {
    throw "DuckDNS token is not installed at $tokenFile"
}

$env:DUCKDNS_API_TOKEN = (Get-Content -LiteralPath $tokenFile -Raw).Trim()
if (-not $env:DUCKDNS_API_TOKEN) {
    throw "DuckDNS token file is empty"
}

$running = Get-CimInstance Win32_Process -Filter "Name = 'caddy.exe'" |
    Where-Object { $_.ExecutablePath -eq $caddy }
if ($running) {
    exit 0
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Start-Process `
    -FilePath $caddy `
    -ArgumentList @("run", "--config", $Config, "--adapter", "caddyfile") `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog
