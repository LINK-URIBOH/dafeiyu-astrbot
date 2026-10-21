param([string]$RuntimeDir = "D:\AI\BiliActivity")
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$state = Join-Path $RuntimeDir "state"
$service = Join-Path $PSScriptRoot "service.py"
$tunnel = Join-Path $PSScriptRoot "tunnel.ps1"
foreach ($entry in @(@('service.pid', $service), @('tunnel.pid', $tunnel))) {
    $pidFile = Join-Path $RuntimeDir $entry[0]
    if (-not (Test-Path -LiteralPath $pidFile)) { continue }
    $ownedId = [int](Get-Content -LiteralPath $pidFile -Raw).Trim()
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$ownedId"
    if ($process -and $process.CommandLine -and $process.CommandLine.Contains($entry[1])) {
        # /T only stops the owned service/tunnel process tree (including its ssh child).
        & taskkill.exe /PID $ownedId /T /F | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not stop owned process $ownedId" }
    }
    Remove-Item -LiteralPath $pidFile
}
Write-Output "Bilibili companion stopped. PhoneMCP, emulator and existing SSH tunnel 8009 were not stopped."
