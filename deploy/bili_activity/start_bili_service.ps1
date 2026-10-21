param(
    [Parameter(Mandatory = $true)][string]$Server,
    [string]$User = "root",
    [string]$Key = "$env:USERPROFILE\.ssh\ecs_dafeiyu",
    [int]$SshPort = 22,
    [string]$RuntimeDir = "D:\AI\BiliActivity",
    [string]$Adb = "D:\leidian\LDPlayer14\adb.exe",
    [string]$PythonCommand = "python",
    [string]$DockerGateway = "172.18.0.1",
    [string]$DeployRoot = "/opt/dafeiyu",
    [switch]$SkipInstall,
    [switch]$NoCloudProxy
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ($Server -notmatch '^[A-Za-z0-9._-]+$' -or $User -notmatch '^[A-Za-z0-9._-]+$') {
    throw "Invalid SSH host or user"
}
if ($DockerGateway -notmatch '^\d{1,3}(\.\d{1,3}){3}$' -or $DeployRoot -notmatch '^/[A-Za-z0-9_./-]+$') {
    throw "Invalid Docker gateway or deployment root"
}
if ($SshPort -lt 1 -or $SshPort -gt 65535) { throw "Invalid SSH port" }
if (-not (Test-Path -LiteralPath $Key)) { throw "SSH key file is missing: $Key" }
if (-not (Test-Path -LiteralPath $Adb)) { throw "ADB is missing: $Adb" }
$source = $PSScriptRoot
$state = Join-Path $RuntimeDir "state"
$logs = Join-Path $RuntimeDir "logs"
New-Item -ItemType Directory -Force -Path $RuntimeDir, $state, $logs | Out-Null
$venv = Join-Path $RuntimeDir ".venv"
$python = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    & $PythonCommand -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "Creating Python venv failed" }
}
& $python -c "import sys; assert sys.version_info >= (3, 12), 'Python 3.12+ required'"
if ($LASTEXITCODE -ne 0) { throw "Unsupported Python runtime" }
if (-not $SkipInstall) {
    & $python -m pip install --disable-pip-version-check -r (Join-Path $source "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
    & $python -m pip check
    if ($LASTEXITCODE -ne 0) { throw "Dependency validation failed" }
}
& $Adb -s emulator-5554 get-state
if ($LASTEXITCODE -ne 0) { throw "emulator-5554 is offline; start the existing phone service first" }

function Find-Owned([string]$Script, [string]$Marker) {
    @(Get-CimInstance Win32_Process | Where-Object {
        $_.ProcessId -ne $PID -and $_.CommandLine -and
        $_.CommandLine.Contains($Script) -and $_.CommandLine.Contains($Marker)
    })
}
function Quote-Arg([string]$Value) {
    if ($Value.Contains('"')) { throw "Argument contains unsupported quote" }
    '"' + $Value.TrimEnd('\') + '"'
}

$service = Join-Path $source "service.py"
if ((Find-Owned $service $state).Count -eq 0) {
    $arguments = @('-u', (Quote-Arg $service), '--state-dir', (Quote-Arg $state),
        '--host', '127.0.0.1', '--port', '8010', '--adb-path', (Quote-Arg $Adb),
        '--device-id', 'emulator-5554', '--allowed-host', "${DockerGateway}:*")
    $process = Start-Process -FilePath $python -ArgumentList $arguments -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logs "service.stdout.log") `
        -RedirectStandardError (Join-Path $logs "service.stderr.log")
    $process.Id | Set-Content -LiteralPath (Join-Path $RuntimeDir "service.pid") -Encoding Ascii
}
$tunnel = Join-Path $source "tunnel.ps1"
if ((Find-Owned $tunnel $Server).Count -eq 0) {
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Quote-Arg $tunnel),
        '-Server', $Server, '-User', $User, '-Key', (Quote-Arg $Key), '-SshPort', $SshPort, '-Port', 8010)
    $process = Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logs "tunnel.stdout.log") `
        -RedirectStandardError (Join-Path $logs "tunnel.stderr.log")
    $process.Id | Set-Content -LiteralPath (Join-Path $RuntimeDir "tunnel.pid") -Encoding Ascii
}
if (-not $NoCloudProxy) {
    & ssh.exe -i $Key -p $SshPort -o BatchMode=yes -o ConnectTimeout=15 -- "$User@$Server" `
        "bash $DeployRoot/tools/bili_activity/cloud_service.sh start $DockerGateway"
    if ($LASTEXITCODE -ne 0) { throw "Cloud companion proxy did not start; inspect existing SSH access and staged files" }
}
Write-Output "Bilibili service and its separate SSH tunnel launched. Use status_bili_service.ps1 for MCP readiness."
Write-Output "Existing PhoneMCP 8009, emulator, AstrBot and scheduled tasks were left running."
