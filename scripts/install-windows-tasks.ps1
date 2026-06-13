param(
    [string]$Distribution = "Ubuntu-24.04",
    [string]$Repo = "/mnt/e/Business/btxpool"
)

$ErrorActionPreference = "Stop"
$powershell = (Get-Command powershell.exe).Source
$launcher = Join-Path $PSScriptRoot "run-wsl-hidden.ps1"

function Set-BtxTask {
    param(
        [string]$Name,
        [string]$Script,
        [Microsoft.Management.Infrastructure.CimInstance]$Trigger
    )

    $arguments = @(
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle", "Hidden",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$launcher`"",
        "-Distribution", "`"$Distribution`"",
        "-Repo", "`"$Repo`"",
        "-Script", "`"$Script`""
    ) -join " "
    $action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments
    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -Hidden `
        -StartWhenAvailable
    Register-ScheduledTask `
        -TaskName $Name `
        -Action $action `
        -Trigger $Trigger `
        -Settings $settings `
        -Description "BTX Family Pool production operation" `
        -Force | Out-Null
}

function Set-CloudflaredTask {
    param(
        [Microsoft.Management.Infrastructure.CimInstance]$Trigger
    )

    $script = Join-Path $PSScriptRoot "start-cloudflared-hidden.ps1"
    $arguments = @(
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle", "Hidden",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$script`""
    ) -join " "
    $action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments
    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -Hidden `
        -StartWhenAvailable
    Register-ScheduledTask `
        -TaskName "BTX Pool Cloudflare Tunnel" `
        -Action $action `
        -Trigger $Trigger `
        -Settings $settings `
        -Description "BTX Family Pool Cloudflare Tunnel" `
        -Force | Out-Null
}

$startupCheck = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
$hourly = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Hours 1)
$daily = New-ScheduledTaskTrigger -Daily -At 3am
$everyFiveMinutes = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)

Set-BtxTask "BTX Pool Start" `
    "supervise-wsl.sh" $startupCheck
Set-BtxTask "BTX Pool Health" `
    "health-check.sh" $everyFiveMinutes
Set-BtxTask "BTX Pool Ledger Backup" `
    "backup-db.sh" $hourly
Set-BtxTask "BTX Pool Wallet Backup" `
    "backup-wallet.sh" $daily
Set-BtxTask "BTX Pool Peer Check" `
    "ensure-peers.sh" $everyFiveMinutes
$tunnelToken = Join-Path $env:LOCALAPPDATA "btxpool\cloudflared\tunnel-token"
if (Test-Path -LiteralPath $tunnelToken) {
    Set-CloudflaredTask $everyFiveMinutes
    Unregister-ScheduledTask -TaskName "BTX Pool HTTPS" `
        -Confirm:$false -ErrorAction SilentlyContinue
} else {
    Write-Warning "Cloudflare tunnel token is missing: $tunnelToken"
    Write-Warning "The Cloudflare tunnel task was not installed."
}

Get-ScheduledTask -TaskName "BTX Pool *" |
    Select-Object TaskName, State |
    Sort-Object TaskName
