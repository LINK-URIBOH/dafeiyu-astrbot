param(
    [int]$Port = 8009,
    [string]$PhoneMcpDir = "D:\AI\PhoneMCP",
    [switch]$StopEmulator
)

$ErrorActionPreference = "Stop"
$logDir = Join-Path $PhoneMcpDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "service.log"

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
    Write-Host $line
}

Write-Log "=== stop_phone_service begin ==="

$targets = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessId -ne $PID -and
    $_.CommandLine -and (
        $_.CommandLine -match "start_reverse_tunnel\.ps1" -or
        ($_.Name -match "^ssh(\.exe)?$" -and $_.CommandLine -match "-R\s+$Port") -or
        ($_.CommandLine -match "main\.py\s+serve" -and $_.CommandLine -match "--port\s+$Port")
    )
}

foreach ($p in $targets) {
    Write-Log "Stopping PID $($p.ProcessId): $($p.Name)"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}

# Fallback: kill whatever still owns the local port.
$conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conn) {
    if ($c.OwningProcess -ne $PID) {
        Write-Log "Stopping port owner PID $($c.OwningProcess)"
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

if ($StopEmulator) {
    Write-Log "Stopping LDPlayer processes"
    Get-Process -Name dnplayer, Ld9BoxHeadless, Ld9BoxSVC -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

Write-Log "=== stop_phone_service done ==="
