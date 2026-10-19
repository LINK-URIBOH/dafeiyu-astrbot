param(
    [string]$PhoneMcpDir = "D:\AI\PhoneMCP",
    [string]$AdbDir = "D:\leidian\LDPlayer14",
    [string]$ListenHost = "127.0.0.1",
    [int]$Port = 8009
)

$ErrorActionPreference = "Stop"

$python = Join-Path $PhoneMcpDir "venv\Scripts\python.exe"
$source = Join-Path $PhoneMcpDir "src"
if (-not (Test-Path $python)) {
    throw "Python venv not found: $python`nCreate it first: python -m venv $PhoneMcpDir\venv"
}
if (-not (Test-Path (Join-Path $source "main.py"))) {
    throw "PhoneMCP source not found: $source"
}

# Reuse LDPlayer's adb so emulator-5554 is visible.
$env:Path = "$AdbDir;" + $env:Path

Set-Location $source
& $python main.py serve --transport sse --host $ListenHost --port $Port --path /Phone
