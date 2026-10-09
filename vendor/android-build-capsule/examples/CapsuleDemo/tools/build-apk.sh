#!/usr/bin/env bash
set -euo pipefail
project_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
: "${ABC_CAPSULE_ROOT:?Use abc.py run-project to supply the Capsule environment}"
: "${ANDROID_SDK_ROOT:?SDK environment is missing}"
# Exercise the javac/jar compatibility shims supplied to preservation builders.
javac -version
jar --version
output="$project_root/.local-builds/demo_$(date -u +%Y%m%d_%H%M%S)"
python3 "$ABC_CAPSULE_ROOT/abc.py" build --sdk "$ANDROID_SDK_ROOT" \
  --project "$project_root" --output "$output" --debug-sign
