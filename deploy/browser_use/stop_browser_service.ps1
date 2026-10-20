param(
    [int]$Port = 8010,
    [string]$RuntimeDir = "D:\AI\BrowserUse"
)

$ErrorActionPreference = "Stop"
$logDir = Join-Path $RuntimeDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "service.log"
$profileDir = Join-Path $RuntimeDir "chrome-profile"

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
    Write-Host $line
}

Write-Log "=== stop_browser_service begin ==="

$targets = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessId -ne $PID -and
    $_.CommandLine -and (
        $_.CommandLine -match "browser_mcp_server\.py" -or
        ($_.CommandLine -match "start_reverse_tunnel\.ps1" -and $_.CommandLine -match "-Port\s+$Port") -or
        ($_.Name -match "^ssh(\.exe)?$" -and $_.CommandLine -match "-R\s+$Port")
    )
}

foreach ($p in $targets) {
    Write-Log "Stopping PID $($p.ProcessId): $($p.Name)"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}

# 兜底：杀掉仍占用本地端口的进程
$conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conn) {
    if ($c.OwningProcess -ne $PID) {
        Write-Log "Stopping port owner PID $($c.OwningProcess)"
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

# 清理 Browser Use 留下的 Chrome（只认它的临时 profile，不动用户主 Chrome）
$chrome = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -and (
            $_.CommandLine -match "browser-use-user-data-dir" -or
            $_.CommandLine -match [regex]::Escape($profileDir)
        )
    }
foreach ($p in $chrome) {
    Write-Log "Stopping leftover Chrome PID $($p.ProcessId)"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}

Write-Log "=== stop_browser_service done ==="
