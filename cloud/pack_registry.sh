#!/usr/bin/env bash
# Pack the private registry and seed into ONE encrypted file for the CI shards.
#   bash cloud/pack_registry.sh <passphrase-file> [out-file]     (default out: $WORK/cloudtest/registry.enc)
# registry.sqlite is copied with sqlite3's online backup (a consistent snapshot even if a WAL file exists); seed.bin is copied as is.
# The plain copies live in a 0700 temp dir that is removed on exit. The result holds the ORIGINAL identifiers: never commit or publish
# the plain files; the encrypted file is only as safe as the passphrase. Unpack side: run_shard.sh with DEID_REG_BLOB + DEID_REG_PASS
# (openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -md sha256, then tar -x).
set -euo pipefail
PASSFILE=${1:?usage: pack_registry.sh <passphrase-file> [out-file]}
WORK=${DEID_WORK:-/Volumes/vcvmachina/work}
OUT=${2:-$WORK/cloudtest/registry.enc}
[ -s "$PASSFILE" ] || { echo "passphrase file is missing or empty" >&2; exit 2; }
[ -s "$WORK/registry.sqlite" ] && [ -s "$WORK/seed.bin" ] || { echo "no registry.sqlite / seed.bin in $WORK" >&2; exit 2; }
T=$(mktemp -d); chmod 700 "$T"; trap 'rm -rf "$T"' EXIT
# immutable=1: read the file without creating -wal/-shm next to the original; safe because nothing writes the registry after the harvest.
sqlite3 "file:$WORK/registry.sqlite?immutable=1" ".backup '$T/registry.sqlite'"
[ "$(sqlite3 "$T/registry.sqlite" 'PRAGMA integrity_check;')" = ok ] || { echo "registry copy failed its integrity check" >&2; exit 3; }
sqlite3 "$T/registry.sqlite" 'PRAGMA journal_mode=DELETE;' >/dev/null     # one self-contained file
cp "$WORK/seed.bin" "$T/seed.bin"
mkdir -p "$(dirname "$OUT")"
tar -C "$T" -cf - registry.sqlite seed.bin | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -salt -pass "file:$PASSFILE" -out "$OUT"
# round trip check
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 -pass "file:$PASSFILE" -in "$OUT" | tar -tf - | sort | tr '\n' ' ' | grep -q '^registry.sqlite seed.bin $'
echo "wrote $OUT ($(wc -c < "$OUT") bytes); identities: $(sqlite3 "$T/registry.sqlite" 'select count(*) from identity')"
