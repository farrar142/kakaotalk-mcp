# Keeps the KakaoTalk MCP server running over HTTP in the logged-in desktop session.
# Started at logon by the shortcut that install_autostart.ps1 creates.
param(
    [string]$Python = "$env:USERPROFILE\.venvs\kakao-mcp\Scripts\python.exe",
    [string]$ListenHost = "0.0.0.0",
    [int]$Port = 8765
)

$logDir = Join-Path $env:LOCALAPPDATA "kakaotalk-mcp"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "server.log"

# Single instance per user session
$mutex = New-Object System.Threading.Mutex($false, "Local\kakaotalk-mcp-server")
if (-not $mutex.WaitOne(0)) { exit 0 }

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"
while ($true) {
    if ((Get-Item $log -ErrorAction SilentlyContinue).Length -gt 5MB) {
        Move-Item $log "$log.1" -Force
    }
    Add-Content -Path $log -Encoding UTF8 -Value "=== $(Get-Date -Format s) starting on ${ListenHost}:$Port"
    # cmd redirection keeps the server's UTF-8 output as-is in the log
    cmd /c "`"$Python`" -m kakao_mcp --transport streamable-http --host $ListenHost --port $Port >> `"$log`" 2>&1"
    Add-Content -Path $log -Encoding UTF8 -Value "=== $(Get-Date -Format s) exited with $LASTEXITCODE, restarting in 5s"
    Start-Sleep -Seconds 5
}
