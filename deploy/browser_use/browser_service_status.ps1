param(
    [int]$Port = 8010,
    [string]$RuntimeDir = "D:\AI\BrowserUse"
)

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

Write-Host "=== Dafeiyu browser service status ==="
Write-Host ("BrowserMCP :$Port : " + (Test-LocalPort -Port $Port))

$server = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and $_.CommandLine -match "browser_mcp_server\.py"
}
Write-Host ("BrowserMCP proc  : " + [bool]$server)

$tunnel = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and
    $_.CommandLine -match "start_reverse_tunnel\.ps1" -and
    $_.CommandLine -match "-Port\s+$Port"
}
Write-Host ("Tunnel script    : " + [bool]$tunnel)

$sshTunnel = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -match "^ssh(\.exe)?$" -and $_.CommandLine -match "-R\s+$Port"
}
Write-Host ("SSH -R $Port       : " + [bool]$sshTunnel)

$chrome = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match "browser-use-user-data-dir" }
Write-Host ("Browser Chrome   : " + [bool]$chrome)
Write-Host ("Log directory    : " + (Join-Path $RuntimeDir "logs"))
