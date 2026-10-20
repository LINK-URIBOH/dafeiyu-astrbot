param(
    [int]$Port = 8009,
    [string]$PhoneMcpDir = "D:\AI\PhoneMCP",
    [string]$AdbDir = "D:\leidian\LDPlayer14"
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

Write-Host "=== Dafeiyu phone service status ==="
Write-Host ("LDPlayer        : " + [bool](Get-Process -Name dnplayer -ErrorAction SilentlyContinue))
Write-Host ("PhoneMCP :$Port  : " + (Test-LocalPort -Port $Port))

$adb = Join-Path $AdbDir "adb.exe"
if (Test-Path -LiteralPath $adb) {
    $devices = & $adb devices 2>$null
    $deviceLine = ($devices | Where-Object { $_ -match "emulator-5554" } | Select-Object -First 1)
    Write-Host ("ADB device      : " + ($deviceLine -replace "\s+", " "))
} else {
    Write-Host "ADB device      : adb.exe not found"
}

$tunnel = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and $_.CommandLine -match "start_reverse_tunnel\.ps1"
}
Write-Host ("Tunnel script   : " + [bool]$tunnel)

$mcp = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and
    $_.CommandLine -match "main\.py\s+serve" -and
    $_.CommandLine -match "--port\s+$Port"
}
Write-Host ("PhoneMCP process: " + [bool]$mcp)
Write-Host ("Log directory   : " + (Join-Path $PhoneMcpDir "logs"))
