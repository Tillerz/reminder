# Plays a pre-rendered reminder WAV by name. Called by Windows Task Scheduler.
# Usage: powershell.exe -NoProfile -WindowStyle Hidden -File play.ps1 -Name lunch
param(
    [Parameter(Mandatory = $true)]
    [string]$Name
)

$wavPath = Join-Path $PSScriptRoot "wav\$Name.wav"

if (-not (Test-Path $wavPath)) {
    Write-Error "No such reminder WAV: $wavPath"
    exit 1
}

$player = New-Object System.Media.SoundPlayer $wavPath
$player.PlaySync()
