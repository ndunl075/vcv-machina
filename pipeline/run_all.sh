#!/bin/bash
# One command for the whole run. Usage:  DEID_INPUT=... DEID_OUT=... DEID_WORK=... ./run_all.sh [procs]
# 1. harvest identities from every file (+ folder owners/repos)   2. rewrite every file into DEID_OUT   3. verify
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3.12}
P=${1:-2}
$PY -W ignore run.py harvest --procs "$P"
$PY -W ignore run.py apply --procs "$P"
$PY -W ignore verify.py --procs "$P"
