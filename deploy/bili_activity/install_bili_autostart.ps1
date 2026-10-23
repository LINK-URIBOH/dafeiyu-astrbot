param(
    [string]$Server = "139.159.250.199",
    [string]$User = "root",
    [string]$Key = "$env:USERPROFILE\.ssh\ecs_dafeiyu",
    [int]$SshPort = 22,
    [string]$RuntimeDir = "D:\AI\BiliActivity",
    [string]$Adb = "D:\leidian\LDPlayer14\adb.exe",
    [switch]$Remove
)
$ErrorActionPreference = "Stop"
$startup = [Environment]::GetFolderPath("Startup")
$target = Join-Path $startup "dafeiyu-bili.cmd"
if ($Remove) {
    Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
    Write-Output "Removed $target"
    exit 0
}
$script = Join-Path $RuntimeDir "src\start_bili_service.ps1"
if (-not (Test-Path -LiteralPath $script)) { throw "Start script missing: $script" }
$line = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{0}" -Server "{1}" -User "{2}" -Key "{3}" -SshPort {4} -Adb "{5}" -SkipInstall' -f `
    $script, $Server, $User, $Key, $SshPort, $Adb
Set-Content -LiteralPath $target -Value $line -Encoding Ascii
Write-Output "Installed $target"
Write-Output "It runs at the next user logon; PhoneMCP and the emulator must be started by their own service first."
