param(
    [Parameter(Mandatory = $true)]
    [string]$Server,
    [string]$User = "root",
    [string]$Key = "$env:USERPROFILE\.ssh\ecs_dafeiyu",
    [string]$Python = "C:\Users\ACER\miniconda3\envs\browser-use\python.exe",
    [string]$RuntimeDir = "D:\AI\BrowserUse",
    [int]$Port = 8010,
    [switch]$NoCloudProxy,
    [switch]$RestartBot
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $RuntimeDir "logs"
$profileDir = Join-Path $RuntimeDir "chrome-profile"
New-Item -ItemType Directory -Force -Path $logDir, $profileDir | Out-Null
$logFile = Join-Path $logDir "service.log"

function Write-Log {
    param([string]$Message)
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
    Write-Host $line
}

function Test-LocalPort {
    param([int]$Port)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", $Port)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

Write-Log "=== start_browser_service begin (server=$Server port=$Port) ==="

# 0. 从 Claude Code 配置里取 DeepSeek key（不打印）
$settingsPath = Join-Path $env:USERPROFILE ".claude\settings.json"
if (Test-Path -LiteralPath $settingsPath) {
    $settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
    $token = $settings.env.ANTHROPIC_AUTH_TOKEN
    if ($token) {
        $env:DEEPSEEK_API_KEY = $token
        Write-Log "DeepSeek key loaded from settings.json"
    } else {
        Write-Log "WARN: ANTHROPIC_AUTH_TOKEN not found in settings.json"
    }
} else {
    Write-Log "WARN: settings.json not found: $settingsPath"
}
$env:PYTHONUTF8 = "1"
$env:BROWSER_PROFILE_DIR = $profileDir
$env:BROWSER_MCP_PORT = "$Port"

# 1. 本地 BrowserMCP（SSE）
if (Test-LocalPort -Port $Port) {
    Write-Log "BrowserMCP already listening on 127.0.0.1:$Port"
} else {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessId -ne $PID -and
        $_.CommandLine -and
        $_.CommandLine -match "browser_mcp_server\.py"
    } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

    $serverScript = Join-Path $scriptDir "browser_mcp_server.py"
    if (-not (Test-Path -LiteralPath $serverScript)) {
        throw "browser_mcp_server.py not found: $serverScript"
    }
    Write-Log "Starting BrowserMCP"
    Start-Process -FilePath $Python -ArgumentList @("`"$serverScript`"") -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "browser_mcp.out.log") `
        -RedirectStandardError (Join-Path $logDir "browser_mcp.err.log") | Out-Null

    $deadline = (Get-Date).AddSeconds(40)
    while ((Get-Date) -lt $deadline -and -not (Test-LocalPort -Port $Port)) {
        Start-Sleep -Seconds 1
    }
    if (Test-LocalPort -Port $Port) {
        Write-Log "BrowserMCP is up"
    } else {
        Write-Log "ERROR: BrowserMCP did not open port $Port; check $logDir"
    }
}

# 2. SSH 反向隧道（复用 phone_mcp 的脚本，按端口区分）
$tunnelScript = Join-Path (Split-Path -Parent $scriptDir) "phone_mcp\start_reverse_tunnel.ps1"
$tunnel = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessId -ne $PID -and
    $_.CommandLine -and
    $_.CommandLine -match "start_reverse_tunnel\.ps1" -and
    $_.CommandLine -match "-Port\s+$Port"
}
if ($tunnel) {
    Write-Log "Reverse tunnel for port $Port already running"
} else {
    Write-Log "Starting reverse tunnel for port $Port"
    Start-Process -FilePath "powershell.exe" -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$tunnelScript`"",
        "-Server", "`"$Server`"", "-User", "`"$User`"", "-Key", "`"$Key`"", "-Port", "$Port"
    ) -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "tunnel.out.log") `
        -RedirectStandardError (Join-Path $logDir "tunnel.err.log") | Out-Null
    Start-Sleep -Seconds 3
    Write-Log "Tunnel launcher started (reconnects every 3s)"
}

# 3. 云端 TCP 代理 + AstrBot MCP 注册（幂等）
if (-not $NoCloudProxy) {
    $remoteDir = "/opt/dafeiyu/tools"
    & ssh.exe -i $Key -o BatchMode=yes -o ConnectTimeout=10 "${User}@${Server}" "mkdir -p $remoteDir" 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Log "WARN: could not create $remoteDir on cloud (exit $LASTEXITCODE)"
    }

    foreach ($f in @("browser_mcp_proxy.py", "enable_astrbot_mcp.py")) {
        $local = Join-Path $scriptDir $f
        & scp.exe -i $Key -o BatchMode=yes -o ConnectTimeout=10 "$local" "${User}@${Server}:$remoteDir/$f" 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Log "WARN: scp $f failed (exit $LASTEXITCODE)"
        }
    }

    $remote = "pgrep -f browser_mcp_proxy.py >/dev/null || (cd $remoteDir && nohup python3 browser_mcp_proxy.py >> browser_mcp_proxy.log 2>&1 &)"
    try {
        & ssh.exe -i $Key -o BatchMode=yes -o ConnectTimeout=10 "${User}@${Server}" $remote 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Log "Cloud browser proxy check OK"
        } else {
            Write-Log "WARN: cloud proxy check failed (exit $LASTEXITCODE)"
        }
    } catch {
        Write-Log "WARN: cloud proxy check failed: $($_.Exception.Message)"
    }

    try {
        & ssh.exe -i $Key -o BatchMode=yes -o ConnectTimeout=10 "${User}@${Server}" "python3 $remoteDir/enable_astrbot_mcp.py" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Log "AstrBot MCP entry ensured"
        } else {
            Write-Log "WARN: AstrBot MCP entry update failed (exit $LASTEXITCODE)"
        }
    } catch {
        Write-Log "WARN: AstrBot MCP entry update failed: $($_.Exception.Message)"
    }
}

# 4. 可选：重启 AstrBot 刷新 SSE 会话
if ($RestartBot) {
    Write-Log "Restarting cloud AstrBot to refresh the MCP session"
    $remote = "cd /opt/dafeiyu && docker restart astrbot >/dev/null && sleep 30 && python3 heal_ws.py"
    try {
        & ssh.exe -i $Key -o BatchMode=yes -o ConnectTimeout=15 "${User}@${Server}" $remote 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Log "Cloud AstrBot restarted and WebSocket healed"
        } else {
            Write-Log "WARN: cloud AstrBot restart failed (exit $LASTEXITCODE)"
        }
    } catch {
        Write-Log "WARN: cloud AstrBot restart failed: $($_.Exception.Message)"
    }
}

Write-Log "=== start_browser_service done ==="
