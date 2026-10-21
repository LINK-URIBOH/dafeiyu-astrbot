param(
    [Parameter(Mandatory = $true)][string]$Server,
    [string]$User = "root",
    [string]$Key = "$env:USERPROFILE\.ssh\ecs_dafeiyu",
    [int]$SshPort = 22,
    [int]$Port = 8010
)
$ErrorActionPreference = "Stop"
if ($Server -notmatch '^[A-Za-z0-9._-]+$' -or $User -notmatch '^[A-Za-z0-9._-]+$') {
    throw "Invalid SSH host or user"
}
while ($true) {
    & ssh.exe -N -i $Key -p $SshPort -o BatchMode=yes -o ExitOnForwardFailure=yes `
        -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o ConnectTimeout=15 `
        -R "${Port}:127.0.0.1:${Port}" -- "$User@$Server"
    Write-Output "Bilibili tunnel disconnected; retry in 3 seconds."
    Start-Sleep -Seconds 3
}
