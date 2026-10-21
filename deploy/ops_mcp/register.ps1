$ErrorActionPreference = "Stop"

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Server = Join-Path $Here "server.py"

$Candidates = @(
    "C:\Users\ACER\AppData\Local\Python\pythoncore-3.14-64\python.exe",
    "C:\Users\ACER\miniconda3\python.exe"
)
$Python = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Python) {
    $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $Python) {
    throw "python.exe not found"
}
if (-not (Test-Path $Server)) {
    throw "server.py not found: $Server"
}

$SshHost = $env:DAFEIYU_SSH_HOST
$HostFile = Join-Path $HOME ".dafeiyu-admin\host"
if (-not $SshHost -and (Test-Path $HostFile)) {
    $SshHost = (Get-Content $HostFile -TotalCount 1).Trim()
}
if (-not $SshHost) {
    throw "SSH host not set. Use DAFEIYU_SSH_HOST=root@host or write it to $HostFile"
}

Write-Host "Python: $Python"
Write-Host "Server: $Server"
Write-Host "Host:   $SshHost"

# 幂等：先移除旧注册（不存在时忽略）
& claude mcp remove dafeiyu-admin 2>$null | Out-Null

& claude mcp add --scope user dafeiyu-admin --env "DAFEIYU_SSH_HOST=$SshHost" -- $Python $Server
if ($LASTEXITCODE -ne 0) {
    throw "claude mcp add failed, exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Registered. Open a new Claude Code session to load it. Current status:"
& claude mcp list
