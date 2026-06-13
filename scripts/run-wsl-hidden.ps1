param(
    [Parameter(Mandatory = $true)]
    [string]$Distribution,
    [Parameter(Mandatory = $true)]
    [string]$Repo,
    [Parameter(Mandatory = $true)]
    [string]$Script
)

$ErrorActionPreference = "Stop"
$wsl = (Get-Command wsl.exe).Source
$arguments = @(
    "-d",
    $Distribution,
    "--",
    "bash",
    "$Repo/scripts/$Script"
)

$process = Start-Process `
    -FilePath $wsl `
    -ArgumentList $arguments `
    -WindowStyle Hidden `
    -Wait `
    -PassThru
exit $process.ExitCode
