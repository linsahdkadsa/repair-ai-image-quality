#!/usr/bin/env bash
# Runner for macOS / Linux. First use creates ../runtime (a private venv with
# numpy, Pillow, OpenCV), later runs reuse it.
#   run.sh [repair args]            -> repair.py (one-click)
#   run.sh demaze IN OUT [args]     -> gpt_demaze.py
#   run.sh color SRC EDIT OUT [...] -> color_match.py
#   run.sh selftest                 -> selftest.py
#   run.sh controller plan|run ...  -> controller.py (GPT maze wash + fusion)
#   run.sh transplant grid|prep|finish ... -> part_transplant.py (product detail from a real photo)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
RT="$ROOT/runtime"
PY="${REPAIR_AI_IMAGE_PYTHON:-}"
if [ -z "$PY" ]; then
  if [ ! -x "$RT/bin/python" ]; then
    BASE="$(command -v python3 || command -v python || true)"
    if [ -z "$BASE" ]; then echo "需要 Python 3.9+（未找到 python3）" >&2; exit 1; fi
    echo "首次运行：创建运行环境 $RT ..." >&2
    "$BASE" -m venv "$RT"
  fi
  PY="$RT/bin/python"
fi
if ! "$PY" -c "import cv2, numpy, PIL" >/dev/null 2>&1; then
  echo "安装依赖（numpy / Pillow / OpenCV）..." >&2
  "$PY" -m pip install --disable-pip-version-check -q -r "$HERE/requirements.txt"
fi
case "${1:-}" in
  demaze)   shift; exec "$PY" "$HERE/gpt_demaze.py" "$@" ;;
  color)    shift; exec "$PY" "$HERE/color_match.py" "$@" ;;
  selftest) shift; exec "$PY" "$HERE/selftest.py" "$@" ;;
  controller) shift; exec "$PY" "$HERE/controller.py" "$@" ;;
  transplant) shift; exec "$PY" "$HERE/part_transplant.py" "$@" ;;
  *)        exec "$PY" "$HERE/repair.py" "$@" ;;
esac
