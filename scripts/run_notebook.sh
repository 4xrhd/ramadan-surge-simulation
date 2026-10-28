#!/usr/bin/env bash
# Rebuild, execute top to bottom in a fresh kernel (Restart and Run All), export HTML.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
PY="$ROOT/.venv/bin/python"
NB="$ROOT/outputs/ramadan_surge_simulation.ipynb"

"$PY" "$HERE/build_notebook.py"
"$PY" -m nbconvert --to notebook --execute --inplace \
  --ExecutePreprocessor.timeout=1800 --ExecutePreprocessor.kernel_name=ramadan-surge "$NB"
"$PY" -m nbconvert --to html "$NB" --output ramadan_surge_simulation.html
echo "OK: executed and exported $NB"
