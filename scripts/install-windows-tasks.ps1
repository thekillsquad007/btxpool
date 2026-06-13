param(
    [string]$Distribution = "Ubuntu-24.04",
    [string]$Repo = "/mnt/e/Business/btxpool"
)

$ErrorActionPreference = "Stop"
$wsl = (Get-Command wsl.exe).Source

function Set-BtxTask {
    param(
        [string]$Name,
        [string]$Arguments,
        [Microsoft.Management.Infrastructure.CimInstance]$Trigger
    )

    $action = New-ScheduledTaskAction -Execute $wsl -Argument $Arguments
    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -StartWhenAvailable
    Register-ScheduledTask `
        -TaskName $Name `
        -Action $action `
        -Trigger $Trigger `
        -Settings $settings `
        -Description "BTX Family Pool production operation" `
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
    "-d $Distribution -- bash $Repo/scripts/supervise-wsl.sh" $startupCheck
Set-BtxTask "BTX Pool Health" `
    "-d $Distribution -- bash $Repo/scripts/health-check.sh" $everyFiveMinutes
Set-BtxTask "BTX Pool Ledger Backup" `
    "-d $Distribution -- bash $Repo/scripts/backup-db.sh" $hourly
Set-BtxTask "BTX Pool Wallet Backup" `
    "-d $Distribution -- bash $Repo/scripts/backup-wallet.sh" $daily
Set-BtxTask "BTX Pool Peer Check" `
    "-d $Distribution -- bash $Repo/scripts/ensure-peers.sh" $everyFiveMinutes

Get-ScheduledTask -TaskName "BTX Pool *" |
    Select-Object TaskName, State |
    Sort-Object TaskName
