#!/bin/bash
# End-to-end smoke test on a synthetic corpus (invented names only). Usage: tests/run_fixture.sh [python]
set -euo pipefail
PY=${1:-python3.12}
T=$(mktemp -d)
mkdir -p "$T/in" "$T/out" "$T/work"
$PY "$(dirname "$0")/make_fixture.py" "$T/in"
export DEID_INPUT="$T/in" DEID_OUT="$T/out" DEID_WORK="$T/work"
cd "$(dirname "$0")/.."
$PY -W ignore run.py harvest --procs 2
$PY -W ignore run.py apply --procs 2
$PY -W ignore verify.py --procs 2 --full
echo "fixture dir: $T"
