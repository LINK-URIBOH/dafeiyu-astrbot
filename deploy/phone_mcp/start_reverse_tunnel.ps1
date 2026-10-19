param(
    [Parameter(Mandatory = $true)]
    [string]$Server,
    [string]$User = "root",
    [string]$Key = "$env:USERPROFILE\.ssh\ecs_dafeiyu",
    [int]$Port = 8009
)

# Keep the reverse tunnel alive across network resets.
# The tunnel exposes the local PhoneMCP (127.0.0.1:$Port) on the cloud host's
# 127.0.0.1:$Port.  phone_mcp_proxy.py then bridges the Docker gateway to it.
while ($true) {
    ssh -i $Key -N `
        -o BatchMode=yes `
        -o ExitOnForwardFailure=yes `
        -o ServerAliveInterval=15 `
        -o ServerAliveCountMax=3 `
        -o ConnectTimeout=15 `
        -R "${Port}:127.0.0.1:${Port}" `
        "$User@$Server"

    Write-Host "[tunnel] disconnected $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), retrying in 3s"
    Start-Sleep -Seconds 3
}
