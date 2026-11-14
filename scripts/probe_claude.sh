#!/usr/bin/env bash
# Measure claude -p start-up overhead (full vs lean) and 4 parallel lean calls.
set -u
OUT="$(cd "$(dirname "$0")/.." && pwd)/logs/probe_claude.log"
T=$(mktemp -d); cd "$T"
LEAN=(--strict-mcp-config --mcp-config '{"mcpServers":{}}' --tools "" --setting-sources "" --no-session-persistence --disable-slash-commands --max-turns 1 --output-format json)
run() { local label="$1"; shift; local s=$(date +%s%N); local r; r=$(claude -p "Reply with exactly: OK" "$@" 2>&1 | tail -c 300 | tr '\n' ' '); local e=$(( ($(date +%s%N)-s)/1000000 )); echo "$label ms=$e :: $r" >>"$OUT"; }
echo "=== $(date -Is)" >>"$OUT"
run full --max-turns 1 --output-format json
run lean_default "${LEAN[@]}"
run lean_haiku "${LEAN[@]}" --model haiku
run lean_sonnet "${LEAN[@]}" --model sonnet
run lean_opus "${LEAN[@]}" --model opus
for i in 1 2 3 4; do run "par$i" "${LEAN[@]}" --model haiku & done; wait
echo "=== done" >>"$OUT"
