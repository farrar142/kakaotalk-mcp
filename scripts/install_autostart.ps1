# Registers run_server.ps1 to start (hidden) when this user logs on.
# Uses the per-user Startup folder, so no admin rights are needed and the server
# runs inside the interactive desktop session (required for UI automation).
#   powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1 [-Uninstall]
param([switch]$Uninstall)

$startup = [Environment]::GetFolderPath("Startup")
$lnk = Join-Path $startup "kakaotalk-mcp.lnk"

if ($Uninstall) {
    Remove-Item $lnk -ErrorAction SilentlyContinue
    Write-Output "Removed $lnk"
    exit 0
}

$script = Join-Path $PSScriptRoot "run_server.ps1"
$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($lnk)
$sc.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$sc.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""
$sc.WorkingDirectory = Split-Path $PSScriptRoot
$sc.WindowStyle = 7  # minimized
$sc.Save()
Write-Output "Created $lnk"
