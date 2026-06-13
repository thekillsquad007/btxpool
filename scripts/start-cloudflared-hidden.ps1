param(
    [string]$InstallDir = "$env:LOCALAPPDATA\btxpool\cloudflared"
)

$ErrorActionPreference = "Stop"
$cloudflared = Join-Path $InstallDir "cloudflared.exe"
$tokenFile = Join-Path $InstallDir "tunnel-token"
$logDir = Join-Path $env:LOCALAPPDATA "btxpool\logs"
$logFile = Join-Path $logDir "cloudflared.log"

if (-not (Test-Path -LiteralPath $cloudflared)) {
    throw "cloudflared is not installed at $cloudflared"
}
if (-not (Test-Path -LiteralPath $tokenFile)) {
    throw "Cloudflare tunnel token is not installed at $tokenFile"
}
if (-not (Get-Content -LiteralPath $tokenFile -Raw).Trim()) {
    throw "Cloudflare tunnel token file is empty"
}

$running = Get-CimInstance Win32_Process -Filter "Name = 'cloudflared.exe'" |
    Where-Object {
        $_.ExecutablePath -eq $cloudflared -and
        $_.CommandLine -match "tunnel.+run"
    }
if ($running) {
    exit 0
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Start-Process `
    -FilePath $cloudflared `
    -ArgumentList @(
        "tunnel",
        "--no-autoupdate",
        "--protocol", "quic",
        "--logfile", $logFile,
        "--loglevel", "info",
        "run",
        "--token-file", $tokenFile
    ) `
    -WindowStyle Hidden
