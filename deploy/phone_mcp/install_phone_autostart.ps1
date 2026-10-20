param(
    [Parameter(Mandatory = $true)]
    [string]$Server,
    [string]$User = "root",
    [string]$Key = "$env:USERPROFILE\.ssh\ecs_dafeiyu",
    [string]$PhoneMcpDir = "D:\AI\PhoneMCP",
    [string]$TaskName = "DafeiyuPhoneService"
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$startScript = Join-Path $scriptDir "start_phone_service.ps1"
$cmdPath = Join-Path $PhoneMcpDir "start_phone_service.cmd"

if (-not (Test-Path -LiteralPath $startScript)) {
    throw "start script not found: $startScript"
}
New-Item -ItemType Directory -Force -Path $PhoneMcpDir | Out-Null

$content = @"
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$startScript" -Server $Server -User $User -Key "$Key" -RestartBot
"@
Set-Content -LiteralPath $cmdPath -Value $content -Encoding ASCII

& schtasks.exe /Create /TN $TaskName /TR "`"$cmdPath`"" /SC ONLOGON /F
if ($LASTEXITCODE -eq 0) {
    & schtasks.exe /Query /TN $TaskName /V /FO LIST
    Write-Host ""
    Write-Host "Autostart installed as scheduled task."
    Write-Host "Task   : $TaskName (runs at logon)"
    Write-Host "Wrapper: $cmdPath"
    Write-Host "Test   : schtasks /Run /TN $TaskName"
} else {
    # Creating an ONLOGON task may require administrator rights.
    # Fall back to the per-user Startup folder, which works unelevated.
    $startup = [Environment]::GetFolderPath("Startup")
    $startupCmd = Join-Path $startup "DafeiyuPhoneService.cmd"
    $fallback = @"
@echo off
start "" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$startScript" -Server $Server -User $User -Key "$Key" -RestartBot
exit
"@
    Set-Content -LiteralPath $startupCmd -Value $fallback -Encoding ASCII
    Write-Host ""
    Write-Host "schtasks failed (exit $LASTEXITCODE); installed in the Startup folder instead."
    Write-Host "Startup entry: $startupCmd"
    Write-Host "It runs minimized at logon. No administrator rights needed."
}
