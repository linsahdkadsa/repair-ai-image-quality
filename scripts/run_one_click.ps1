param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Source,

    [Parameter(Mandatory = $true, Position = 1)]
    [string]$Output,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"
$skillRoot = Split-Path $PSScriptRoot -Parent
$runtimePython = Join-Path $skillRoot "runtime\Scripts\python.exe"
$script = Join-Path $PSScriptRoot "one_click_denoise.py"
$candidates = @()

if ($env:REPAIR_AI_IMAGE_PYTHON) {
    $candidates += $env:REPAIR_AI_IMAGE_PYTHON
}
$candidates += $runtimePython

$selected = $null
foreach ($candidate in $candidates) {
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        continue
    }
    & $candidate -c "import cv2, numpy, PIL" 2>$null
    if ($LASTEXITCODE -eq 0) {
        $selected = $candidate
        break
    }
}

if (-not $selected) {
    throw "Full denoise runtime is missing. Run setup_runtime.ps1 once, or set REPAIR_AI_IMAGE_PYTHON to a Python executable with requirements.txt installed."
}

$env:PYTHONUTF8 = "1"
& $selected $script $Source $Output @RemainingArgs
exit $LASTEXITCODE
