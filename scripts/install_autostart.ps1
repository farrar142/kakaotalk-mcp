# Registers the MCP server supervisor to start when this user logs on.
# Uses the per-user Startup folder, so no admin rights are needed and the server
# runs inside the interactive desktop session (required for UI automation).
# The shortcut runs pythonw.exe directly: no console window is created, so the
# logon-time console/terminal hand-off can't stall it.
#   powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1 [-Uninstall]
param(
    [switch]$Uninstall,
    [string]$Pythonw = "$env:USERPROFILE\.venvs\kakao-mcp\Scripts\pythonw.exe",
    [string]$ListenHost = "0.0.0.0",
    [int]$Port = 8765
)

$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "kakaotalk-mcp.lnk"

if ($Uninstall) {
    Remove-Item $lnk -ErrorAction SilentlyContinue
    Write-Output "Removed $lnk"
    exit 0
}

if (-not (Test-Path $Pythonw)) { throw "pythonw.exe not found: $Pythonw" }

$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($lnk)
$sc.TargetPath = $Pythonw
$sc.Arguments = "-m kakao_mcp.supervisor --transport streamable-http --host $ListenHost --port $Port"
$sc.WorkingDirectory = Split-Path $PSScriptRoot
$sc.Save()
Write-Output "Created $lnk"
