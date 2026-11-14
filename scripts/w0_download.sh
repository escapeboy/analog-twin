#!/usr/bin/env bash
# W0: resumable downloads, small files first, max 3 parallel.
# Usage: scripts/w0_download.sh <list-file>   (lines: "<subdir> <url>")
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RAW="$ROOT/data/raw"
LOG="$ROOT/logs/w0_download.log"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
export RAW LOG UA

fetch() {
  sub="$1"; url="$2"
  mkdir -p "$RAW/$sub"
  out="$RAW/$sub/$(basename "${url%%\?*}")"
  for attempt in 1 2 3 4 5; do
    stats=$(curl -sS -L -A "$UA" -C - --retry 3 --retry-delay 5 --connect-timeout 30 \
      -o "$out" -w '%{http_code} %{size_download} %{speed_download} %{time_total}' "$url" 2>>"$LOG")
    rc=$?
    code=${stats%% *}
    # 416 = already complete when resuming
    if [ $rc -eq 0 ] && { [ "$code" = 200 ] || [ "$code" = 206 ] || [ "$code" = 416 ]; }; then
      echo "$(date -Is) OK   $sub $(basename "$out") http=$stats size=$(stat -c %s "$out")" >>"$LOG"
      return 0
    fi
    echo "$(date -Is) RETRY$attempt $sub $url rc=$rc stats=$stats" >>"$LOG"
    sleep 10
  done
  echo "$(date -Is) FAIL $sub $url" >>"$LOG"
}
export -f fetch

grep -vE '^\s*(#|$)' "$1" | xargs -P 3 -L 1 bash -c 'fetch "$0" "$1"'
echo "$(date -Is) DONE list $1" >>"$LOG"
