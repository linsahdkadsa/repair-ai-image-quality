# Runner for Windows PowerShell. First use creates ..\runtime (private venv).
#   run.ps1 [repair args] | run.ps1 demaze IN OUT | run.ps1 color SRC EDIT OUT | run.ps1 selftest | run.ps1 controller ... | run.ps1 transplant ...
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$root = Split-Path $here -Parent
$rt = Join-Path $root "runtime"
$py = $env:REPAIR_AI_IMAGE_PYTHON
if (-not $py) {
    $py = Join-Path $rt "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $py)) {
        $base = (Get-Command python -ErrorAction SilentlyContinue).Source
        if (-not $base) { $base = (Get-Command py -ErrorAction SilentlyContinue).Source }
        if (-not $base) { throw "需要 Python 3.9+（未找到 python）" }
        Write-Host "首次运行：创建运行环境 $rt ..."
        & $base -m venv $rt
    }
}
& $py -c "import cv2, numpy, PIL" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "安装依赖（numpy / Pillow / OpenCV）..."
    & $py -m pip install --disable-pip-version-check -q -r (Join-Path $here "requirements.txt")
}
$env:PYTHONUTF8 = "1"
$target = "repair.py"
$rest = $args
if ($args.Count -gt 0) {
    switch ($args[0]) {
        "demaze"   { $target = "gpt_demaze.py" }
        "color"    { $target = "color_match.py" }
        "selftest" { $target = "selftest.py" }
        "controller" { $target = "controller.py" }
        "transplant" { $target = "part_transplant.py" }
    }
    if ($target -ne "repair.py") {
        $rest = if ($args.Count -gt 1) { $args[1..($args.Count - 1)] } else { @() }
    }
}
& $py (Join-Path $here $target) @rest
exit $LASTEXITCODE
