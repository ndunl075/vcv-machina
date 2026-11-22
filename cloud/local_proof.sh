#!/usr/bin/env bash
# Run one shard in a Linux container on a Mac WITHOUT uploading, then byte-compare with an earlier full run.
#   bash cloud/local_proof.sh <shard-id> <platform linux/arm64|linux/amd64> <work-dir> [plan.json]
# needs: docker, the encrypted registry blob ($BLOB), its passphrase file ($PASSFILE), the earlier corpus ($REF).
# (the container cannot see /Volumes, so the blob goes in with `docker cp` and the output comes out with `docker cp`)
set -euo pipefail
SID=$1; PLAT=${2:-linux/arm64}; W=$3; PLAN=${4:-}
REPO=$(cd "$(dirname "$0")/.." && pwd)
BLOB=${BLOB:-/Volumes/vcvmachina/work/cloudtest/registry.enc}
PASSFILE=${PASSFILE:-/Volumes/vcvmachina/work/cloudtest/testpass.txt}
REF=${REF:-/Volumes/vcvmachina/out/attempt-1/corpus}
N=cloudproof-$SID-${PLAT##*/}
mkdir -p "$W"; docker rm -f "$N" >/dev/null 2>&1 || true
docker create --name "$N" --platform "$PLAT" --cpus 4 --memory 16g -v "$REPO:/r:ro" \
  -e DEID_REG_BLOB=/tmp/registry.enc -e DEID_REG_PASS="$(cat "$PASSFILE")" -e NO_UPLOAD=1 -e KEEP=1 -e SHARD_TMP=/tmp/shard -e RESULT_DIR=/tmp/res \
  ${PLAN:+-e SHARDS_JSON=/tmp/plan.json} python:3.12-slim \
  bash -c 'apt-get update -qq >/dev/null && apt-get install -y -qq openssl >/dev/null && bash /r/cloud/run_shard.sh '"$SID" >/dev/null
docker cp "$BLOB" "$N:/tmp/registry.enc"
[ -n "$PLAN" ] && docker cp "$PLAN" "$N:/tmp/plan.json"
S=$(date +%s)
docker start -a "$N" | tee "$W/shard-$SID-${PLAT##*/}.counts.txt" || true
echo "container wall seconds: $(( $(date +%s) - S ))"
rm -rf "$W/out-$SID-${PLAT##*/}"; docker cp "$N:/tmp/shard/out/corpus" "$W/out-$SID-${PLAT##*/}"
docker cp "$N:/tmp/res" "$W/res-$SID-${PLAT##*/}" || true
python3 "$REPO/cloud/compare_out.py" "$W/out-$SID-${PLAT##*/}" "$REF" "$W/diff-$SID-${PLAT##*/}.txt"
