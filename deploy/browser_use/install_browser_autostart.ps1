param(
    [Parameter(Mandatory = $true)]
    [string]$Server,
    [string]$User = "root",
    [string]$Key = "$env:USERPROFILE\.ssh\ecs_dafeiyu",
    [string]$RuntimeDir = "D:\AI\BrowserUse",
    [string]$TaskName = "DafeiyuBrowserService",
    [switch]$RestartBot
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$startScript = Join-Path $scriptDir "start_browser_service.ps1"
$cmdPath = Join-Path $RuntimeDir "start_browser_service.cmd"

if (-not (Test-Path -LiteralPath $startScript)) {
    throw "start script not found: $startScript"
}
New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

$extra = if ($RestartBot) { " -RestartBot" } else { "" }
$content = @"
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$startScript" -Server $Server -User $User -Key "$Key"$extra
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
    # ONLOGON 任务可能需要管理员权限；没有就退回当前用户的启动文件夹。
    $startup = [Environment]::GetFolderPath("Startup")
    $startupCmd = Join-Path $startup "DafeiyuBrowserService.cmd"
    $fallback = @"
@echo off
start "" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$startScript" -Server $Server -User $User -Key "$Key"$extra
exit
"@
    Set-Content -LiteralPath $startupCmd -Value $fallback -Encoding ASCII
    Write-Host ""
    Write-Host "schtasks failed (exit $LASTEXITCODE); installed in the Startup folder instead."
    Write-Host "Startup entry: $startupCmd"
}
