#!/usr/bin/env bash
# Process one shard on a fresh Linux machine:  bash cloud/run_shard.sh <shard-id>
# fetch the shard's input from the public mirror -> `run.py apply` with the private registry -> self-check -> upload -> clean up.
# Everything the tools print goes to a private log inside the work dir; this script prints only counts and timings
# (lines starting "[shard N]"), because the logs of a public CI repo are public.
#
# Environment (all optional unless marked):
#   DEID_REG_DIR                 directory with registry.sqlite and seed.bin, OR
#   DEID_REG_BLOB + DEID_REG_PASS  encrypted file made by pack_registry.sh and its passphrase           (one of the two is required)
#   MACHINA_DEST | UPLOAD_DEST   gs://bucket/teams/<id>/attempt-N/                                        (required unless NO_UPLOAD=1)
#   MACHINA_UPLOAD_TOKEN | UPLOAD_TOKEN   bearer token                                                    (required unless NO_UPLOAD=1)
#   NO_UPLOAD=1      stop after the self-check (local proof)       KEEP=1  keep the work dir (and its private log) afterwards
#   SHARD_TMP        work area (default $RUNNER_TEMP/shard-<id> or /tmp/shard-<id>)   RESULT_DIR (default <repo>/cloud-result)
#   DEID_PY          python with requirements.lock already installed (skips the venv)   PROCS (4)   UPLOAD_WORKERS (64)   FETCH_JOBS (32)
#   MACHINA_INPUT_BASE   mirror address
set -uo pipefail
SID=${1:?usage: run_shard.sh <shard-id>}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
TMP=${SHARD_TMP:-${RUNNER_TEMP:-/tmp}/shard-$SID}
RESULT_DIR=${RESULT_DIR:-$ROOT/cloud-result}
mkdir -p "$TMP" "$RESULT_DIR"
LOG=$TMP/private.log
exec 3>&1
exec >>"$LOG" 2>&1
T0=$(date +%s)
say() { echo "[shard $SID] $*" >&3; }
secs() { echo $(( $(date +%s) - $1 )); }

UP=skipped; RC=1; T_FETCH=0; T_APPLY=0; T_UP=0; T_SETUP=0
finish() {
  local rc=$?
  [ "$rc" -ne 0 ] && RC=$rc || RC=0
  python3 - "$SID" "$RC" "$UP" "$(secs "$T0")" "$T_SETUP" "$T_FETCH" "$T_APPLY" "$T_UP" "$TMP" "$RESULT_DIR" <<'PY' >&3 2>/dev/null
import json, os, sys
sid, rc, up, total, ts, tf, ta, tu, tmp, rdir = sys.argv[1:]
r = {}
try:
    r = json.load(open(os.path.join(tmp, "result.json")))
except Exception:
    pass
r.update({"shard": int(sid), "exit_code": int(rc), "upload": up, "seconds": int(total), "seconds_setup": int(ts), "seconds_fetch": int(tf), "seconds_apply": int(ta), "seconds_upload": int(tu)})
r.setdefault("failures", -1)
json.dump(r, open(os.path.join(rdir, f"shard-{sid}.json"), "w"))
print(f"[shard {sid}] result: exit {rc}, upload {up}, failures {r['failures']}, {total}s total (setup {ts}s, fetch {tf}s, apply {ta}s, upload {tu}s)")
PY
  if [ "${KEEP:-0}" = 1 ]; then say "kept $TMP"; else
    rm -rf "$TMP/in" "$TMP/out" "$TMP/work" "$TMP/reg" "$TMP/venv" "$TMP/manifest.tsv" "$TMP/filelist.txt"
    [ "$rc" -eq 0 ] && rm -f "$LOG" "$TMP"/upload.log
  fi
  exit "$rc"
}
trap finish EXIT

FREE_GB=$(df -Pk "$TMP" | awk 'NR==2{printf "%d", $4/1048576}')
say "start: $(nproc) cpus, $(awk '/MemTotal/{printf "%d", $2/1048576}' /proc/meminfo 2>/dev/null) GB ram, $FREE_GB GB free"
[ "$FREE_GB" -ge "${MIN_FREE_GB:-9}" ] || { say "not enough free disk"; exit 10; }

# ---- 1. tools
TS=$(date +%s)
if [ -n "${DEID_PY:-}" ]; then PY=$DEID_PY; else
  PY=$TMP/venv/bin/python
  "${PYTHON:-python3.12}" -m venv "$TMP/venv" && "$PY" -m pip install -q --no-input --disable-pip-version-check --no-cache-dir -r "$ROOT/pipeline/requirements.lock" || { say "dependency install failed"; exit 11; }
fi
"$PY" -c "import pikepdf, fitz, lxml, ahocorasick_rs, fontTools, ezdxf, olefile, PIL" || { say "dependency import failed"; exit 11; }

# ---- 2. private registry + seed into a writable work dir (the pipeline opens the registry in WAL mode)
mkdir -p "$TMP/work" "$TMP/in" "$TMP/out/corpus"
chmod 700 "$TMP/work"
REG=${DEID_REG_DIR:-}
if [ -z "$REG" ]; then
  [ -n "${DEID_REG_BLOB:-}" ] && [ -n "${DEID_REG_PASS:-}" ] || { say "no registry: set DEID_REG_DIR or DEID_REG_BLOB+DEID_REG_PASS"; exit 12; }
  mkdir -p "$TMP/reg"; chmod 700 "$TMP/reg"
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -pass env:DEID_REG_PASS -in "$DEID_REG_BLOB" | tar -x -C "$TMP/reg" || { say "registry decrypt failed"; exit 12; }
  REG=$TMP/reg
fi
[ -s "$REG/registry.sqlite" ] && [ -s "$REG/seed.bin" ] || { say "registry.sqlite / seed.bin missing"; exit 12; }
cp "$REG/registry.sqlite" "$REG/seed.bin" "$TMP/work/"; chmod 600 "$TMP/work/seed.bin"
T_SETUP=$(secs "$TS")

export DEID_WORK=$TMP/work DEID_INPUT=$TMP/in DEID_OUT=$TMP/out/corpus DEID_FILELIST=$TMP/filelist.txt SHARD_TMP=$TMP
export DEID_USE_LIST=1 DEID_LEGALIZE=1 DEID_REQUIRE_SEED=1 PYTHONDONTWRITEBYTECODE=1

# ---- 3. input
TS=$(date +%s)
"$PY" -I "$ROOT/cloud/shard_tool.py" prepare "$SID" >&3 || { T_FETCH=$(secs "$TS"); say "fetch failed"; exit 20; }
T_FETCH=$(secs "$TS")

# ---- 4. apply
TS=$(date +%s)
"$PY" -W ignore "$ROOT/pipeline/run.py" apply --procs "${PROCS:-4}" > "$TMP/apply.log" 2>&1
ARC=$?
T_APPLY=$(secs "$TS")
say "apply: exit $ARC, $(tail -n 1 "$TMP/apply.log" | sed -E 's/^(apply done: [0-9]+ files, [0-9.]+ GB in [0-9]+s).*/\1/; t; s/.*/(no summary line)/')"
[ "$ARC" -eq 0 ] || exit 30

# ---- 5. self-check
"$PY" -I "$ROOT/cloud/shard_tool.py" check "$SID" >&3 || exit 40
rm -rf "$TMP/in"    # the input is no longer needed; frees disk for the upload

# ---- 6. upload
if [ "${NO_UPLOAD:-0}" = 1 ]; then UP=skipped; say "upload skipped (NO_UPLOAD=1)"; else
  export MACHINA_UPLOAD_TOKEN=${MACHINA_UPLOAD_TOKEN:-${UPLOAD_TOKEN:-}}
  DEST=${MACHINA_DEST:-${UPLOAD_DEST:-}}
  [ -n "$MACHINA_UPLOAD_TOKEN" ] && [ -n "$DEST" ] || { say "no upload token or destination"; UP=missing-config; exit 50; }
  TS=$(date +%s)
  python3 "$ROOT/kit/upload.py" --dest "$DEST" --corpus "$TMP/out/corpus" --workers "${UPLOAD_WORKERS:-64}" > "$TMP/upload.log" 2>&1
  URC=$?
  T_UP=$(secs "$TS")
  say "upload: exit $URC, $(grep -m1 -oE 'Found [0-9]+ files \([0-9]+ already uploaded, [0-9]+ to upload\)' "$TMP/upload.log" || echo 'no listing line')"
  if [ "$URC" -ne 0 ] || ! grep -q 'Done!' "$TMP/upload.log"; then
    if grep -q 'token ran out' "$TMP/upload.log"; then UP=token-expired; say "upload token expired: set a new token and run this shard again"; exit 51; fi
    UP=failed; exit 52
  fi
  UP=done
fi
exit 0
