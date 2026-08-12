param(
    [Parameter(Mandatory = $true)]
    [string]$Python
)

$ErrorActionPreference = "Stop"
$skillRoot = Split-Path $PSScriptRoot -Parent
$runtimeRoot = Join-Path $skillRoot "runtime"
$runtimePython = Join-Path $runtimeRoot "Scripts\python.exe"
$requirements = Join-Path $PSScriptRoot "requirements.txt"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python executable does not exist: $Python"
}

if (-not (Test-Path -LiteralPath $runtimePython -PathType Leaf)) {
    & $Python -m venv $runtimeRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create runtime at $runtimeRoot"
    }
}

& $runtimePython -m pip install --disable-pip-version-check --requirement $requirements
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install the denoise runtime requirements"
}

& $runtimePython -c "import cv2, numpy, PIL; print('runtime-ok', cv2.__version__, numpy.__version__, PIL.__version__)"
if ($LASTEXITCODE -ne 0) {
    throw "Runtime import check failed"
}

Write-Output $runtimePython
