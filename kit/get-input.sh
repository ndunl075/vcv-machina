#!/usr/bin/env bash
# Download the Machina De-ID input (188,722 files, about 139.7 GB) from the
# Builders mirror. No AWS account and no key needed.
#
#   bash get-input.sh --limit 100          # try the first 100 files
#   bash get-input.sh                      # everything, into ./input/
#   bash get-input.sh --prefix sources/gitlab/ --jobs 32
#   bash get-input.sh --aria2              # use aria2c instead of curl
#
# Run it again at any time: files already complete are skipped, and partial
# files are resumed. At the end it checks every selected file's size (and its
# MD5 with --md5, where the manifest has one) and exits non-zero on a mismatch.
# Works with bash 3.2+ (macOS), curl, xargs, awk and find.
set -euo pipefail

BASE="${MACHINA_INPUT_BASE:-https://machina-input.joinbuilders.org}"
DEST="./input"
PREFIX=""
LIMIT=0
JOBS=16
USE_ARIA2=0
CHECK_MD5=0

usage() {
  cat <<EOF
Download the Machina De-ID input from the Builders mirror into --dest.
Run it again to resume; it checks sizes at the end.

Options:
  --dest DIR     where files go (default ./input); paths match the manifest
  --prefix P     only paths starting with P, e.g. sources/github/
  --limit N      only the first N selected files (0 = all)
  --jobs N       parallel downloads (default 16)
  --aria2        download with aria2c -i instead of curl + xargs -P
  --md5          also check MD5s at the end (slower: reads every file)
  --base URL     mirror address (default $BASE)
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dest) DEST="$2"; shift 2 ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    --limit) LIMIT="$2"; shift 2 ;;
    --jobs) JOBS="$2"; shift 2 ;;
    --aria2) USE_ARIA2=1; shift ;;
    --md5) CHECK_MD5=1; shift ;;
    --base) BASE="${2%/}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
done

mkdir -p "$DEST"
DEST="$(cd "$DEST" && pwd)"
WORK="$DEST/.get-input"
mkdir -p "$WORK"
export LC_ALL=C

# 1. The manifest: path <TAB> bytes <TAB> md5 or blank <TAB> url path.
echo "Fetching the manifest from $BASE/manifest.tsv"
status=$(curl -fsS --retry 5 --retry-connrefused "$BASE/STATUS.txt" 2>/dev/null || true)
case "$status" in
  complete*) ;;
  *) echo "Note: the mirror is still filling (status: ${status:-unknown}). Files not there yet are reported at the end." ;;
esac
rm -f "$WORK/not-found.txt"
if ! curl -fsS --compressed --retry 5 --retry-connrefused -o "$WORK/manifest.tsv.part" "$BASE/manifest.tsv"; then
  echo "Could not fetch $BASE/manifest.tsv. If the mirror is still filling, run this again in a few minutes." >&2
  exit 1
fi
mv "$WORK/manifest.tsv.part" "$WORK/manifest.tsv"

awk -F'\t' -v p="$PREFIX" -v n="$LIMIT" '
  /^#/ { next }
  substr($1, 1, length(p)) == p { print; if (n > 0 && ++c >= n) exit }
' "$WORK/manifest.tsv" > "$WORK/selected.tsv"
TOTAL_FILES=$(wc -l < "$WORK/selected.tsv" | tr -d ' ')
TOTAL_BYTES=$(awk -F'\t' '{ s += $2 } END { printf "%.0f", s }' "$WORK/selected.tsv")
echo "Selected $TOTAL_FILES files, $TOTAL_BYTES bytes"
[ "$TOTAL_FILES" -gt 0 ] || { echo "Nothing matches --prefix '$PREFIX'." >&2; exit 1; }

# Sizes of what is already on disk: size <TAB> path relative to DEST.
local_sizes() {
  if find "$DEST" -maxdepth 0 -printf '' >/dev/null 2>&1; then
    (cd "$DEST" && find . -path ./.get-input -prune -o -type f -printf '%s\t%P\n')
  else
    (cd "$DEST" && find . -path ./.get-input -prune -o -type f -exec stat -f '%z	%N' {} + |
      awk -F'\t' -v OFS='\t' '{ sub(/^\.\//, "", $2); print }')
  fi
}

# 2. What still needs fetching (missing, or the wrong size).
local_sizes > "$WORK/local.tsv"
awk -F'\t' '
  FILENAME == ARGV[1] { have[$2] = $1; next }
  !($1 in have) || have[$1] != $2 { print }
' "$WORK/local.tsv" "$WORK/selected.tsv" > "$WORK/todo.tsv"

# Files larger than the manifest says cannot be resumed: start them again.
awk -F'\t' '
  FILENAME == ARGV[1] { have[$2] = $1; next }
  ($1 in have) && have[$1] + 0 > $2 + 0 { print $1 }
' "$WORK/local.tsv" "$WORK/todo.tsv" | while IFS= read -r path; do rm -f "$DEST/$path"; done

TODO=$(wc -l < "$WORK/todo.tsv" | tr -d ' ')
echo "$TODO files to download ($((TOTAL_FILES - TODO)) already complete)"

if [ "$TODO" -gt 0 ]; then
  # Empty files need no download.
  awk -F'\t' '$2 == 0 { print $1 }' "$WORK/todo.tsv" | while IFS= read -r path; do
    mkdir -p "$DEST/$(dirname "$path")"; : > "$DEST/$path"
  done

  if [ "$USE_ARIA2" = 1 ]; then
    command -v aria2c >/dev/null || { echo "aria2c is not installed." >&2; exit 1; }
    awk -F'\t' -v b="$BASE" -v d="$DEST" '$2 > 0 {
      printf "%s/%s\n  dir=%s\n  out=%s\n", b, $4, d, $1
    }' "$WORK/todo.tsv" > "$WORK/aria2.txt"
    aria2c -i "$WORK/aria2.txt" -j "$JOBS" -x 1 -c \
      --auto-file-renaming=false --allow-overwrite=true \
      --max-tries=10 --retry-wait=5 --console-log-level=warn \
      --summary-interval=60 --file-allocation=none || ARIA_RC=$?
    if [ "${ARIA_RC:-0}" = 3 ]; then echo "aria2c: some files answered 404" > "$WORK/not-found.txt"; fi
  else
    fetch_one() {
      mkdir -p "$(dirname "$2")"
      code=$(curl -fsS --retry 10 --retry-connrefused --retry-delay 2 -C - \
        -w '%{http_code}' -o "$2" "$1" 2>/dev/null) && return 0
      if [ "$code" = 200 ] || [ "$code" = 416 ]; then
        # The server would not resume this file: fetch it again from the start.
        rm -f "$2"
        code=$(curl -fsS --retry 10 --retry-connrefused --retry-delay 2 \
          -w '%{http_code}' -o "$2" "$1" 2>/dev/null) && return 0
      fi
      if [ "$code" = 404 ]; then
        printf '%s\n' "$1" >> "$WORK/not-found.txt"
      else
        echo "failed (HTTP $code): $1" >&2
      fi
    }
    export -f fetch_one
    export WORK
    awk -F'\t' -v b="$BASE" -v d="$DEST" '$2 > 0 {
      printf "%s/%s%c%s/%s%c", b, $4, 0, d, $1, 0
    }' "$WORK/todo.tsv" | xargs -0 -n 2 -P "$JOBS" bash -c 'fetch_one "$1" "$2"' _ || true
  fi
fi

# 3. Check every selected file.
echo "Checking sizes"
local_sizes > "$WORK/local.tsv"
awk -F'\t' '
  FILENAME == ARGV[1] { have[$2] = $1; next }
  !($1 in have) { print "missing\t" $1; next }
  have[$1] != $2 { print "wrong size\t" $1 "\t" have[$1] " != " $2 }
' "$WORK/local.tsv" "$WORK/selected.tsv" > "$WORK/problems.tsv"

if [ "$CHECK_MD5" = 1 ]; then
  echo "Checking MD5s where the manifest has one"
  if command -v md5sum >/dev/null; then MD5="md5sum"; else MD5="md5 -r"; fi
  awk -F'\t' '$3 != "" { print $1 "\t" $3 }' "$WORK/selected.tsv" |
    while IFS="$(printf '\t')" read -r path sum; do
      [ -f "$DEST/$path" ] || continue
      got=$($MD5 < "$DEST/$path" | cut -d' ' -f1)
      [ "$got" = "$sum" ] || printf 'wrong md5\t%s\n' "$path" >> "$WORK/problems.tsv"
    done
fi

BAD=$(cut -f2 "$WORK/problems.tsv" | sort -u | wc -l | tr -d ' ')
if [ -s "$WORK/not-found.txt" ]; then
  echo "Some files are not on the mirror yet (HTTP 404): the mirror is still filling, run this again in a few minutes." >&2
  echo "$BAD of $TOTAL_FILES files are still missing; files already downloaded are kept." >&2
  exit 1
fi
if [ "$BAD" -gt 0 ]; then
  head -20 "$WORK/problems.tsv"
  echo "$BAD of $TOTAL_FILES files are not right yet (list: $WORK/problems.tsv). Run the same command again to resume." >&2
  exit 1
fi
echo "All $TOTAL_FILES files are complete in $DEST ($TOTAL_BYTES bytes)."
