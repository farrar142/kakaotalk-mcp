# Prints the UI Automation tree of every KakaoTalk window, structure only:
# control type, class, automation id, size, supported patterns and the *length*
# of each Name — never the text itself (room names and messages stay private).
# Run it after a KakaoTalk update to see whether the message list
# (EVA_VH_ListControl_Dblclk) has started exposing items. See docs/accessibility.md.
#   powershell -ExecutionPolicy Bypass -File scripts\probe_accessibility.ps1 [-Depth 7]
param([int]$Depth = 7, [int]$MaxSiblings = 15)

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A = [System.Windows.Automation.AutomationElement]
$proc = Get-Process KakaoTalk -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $proc) { throw "KakaoTalk is not running" }

$cond = New-Object System.Windows.Automation.PropertyCondition($A::ProcessIdProperty, $proc.Id)
$windows = $A::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, $cond)
$walker = [System.Windows.Automation.TreeWalker]::RawViewWalker

function Dump($e, $d) {
    if ($d -gt $Depth) { return }
    $c = $e.Current
    $pats = ($e.GetSupportedPatterns() | ForEach-Object { $_.ProgrammaticName -replace 'PatternIdentifiers.Pattern', '' }) -join ','
    "{0}{1} | cls={2} | aid={3} | nameLen={4} | {5}x{6} | {7}" -f ('  ' * $d), $c.ControlType.ProgrammaticName,
        $c.ClassName, $c.AutomationId, $c.Name.Length, [int]$c.BoundingRectangle.Width, [int]$c.BoundingRectangle.Height, $pats
    $child = $walker.GetFirstChild($e); $n = 0
    while ($child -ne $null -and $n -lt $MaxSiblings) { Dump $child ($d + 1); $child = $walker.GetNextSibling($child); $n++ }
    $rest = 0; while ($child -ne $null) { $rest++; $child = $walker.GetNextSibling($child) }
    if ($rest) { "{0}... +{1} more" -f ('  ' * ($d + 1)), $rest }
}

"KakaoTalk pid $($proc.Id), version $($proc.MainModule.FileVersionInfo.FileVersion)"
foreach ($w in $windows) { "=== window cls=$($w.Current.ClassName)"; Dump $w 0 }
