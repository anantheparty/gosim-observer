#!/usr/bin/env bash
# Agent-level check: run the first N decisions of local cards with the final agent (c48) twice, once with the
# C kernel and once with the Rust kernel dropped in its place (libkern.so; the loader in agent/policy.py tries
# libkern_linux_x86_64.so first, then libkern.so), and compare every action.
# Needs the lab harness: lab/tools/eqtest.py runs the official v4 engine in-process with an ample CPU budget
# (charge x 0.01), so the search sizes do not depend on timing. No model key is set, so the duty-log reader
# and the strategist use their rule fallbacks.
# usage: N=400 CARDS="HE1 HH1 FA2 FM1" PY=python3 ./test_agent_equiv.sh
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
AG="$HERE/../agent"
EQ="$HERE/../lab/tools/eqtest.py"
N=${N:-400}
CARDS=${CARDS:-"HE1 HH1 FA2 FM1"}
PY=${PY:-python3}
W=$(mktemp -d /tmp/kern_eq.XXXX)
cp -r "$AG" "$W/pkgC"
cp -r "$AG" "$W/pkgR"
rm -f "$W/pkgR/libkern_linux_x86_64.so"
cp "$HERE/target/release/libkern.so" "$W/pkgR/libkern.so"
for c in $CARDS; do
  for k in C R; do
    ( env -u OPENAI_API_KEY "$PY" "$EQ" "$c" "$W/pkg$k" "$N" '{}' "$W/$c.$k.jsonl" > "$W/$c.$k.log" 2>&1 ) &
  done
done
wait
fail=0
for c in $CARDS; do
  a=$(sha256sum < "$W/$c.C.jsonl" | cut -c1-16)
  b=$(sha256sum < "$W/$c.R.jsonl" | cut -c1-16)
  n=$(wc -l < "$W/$c.C.jsonl")
  tc=$(tail -1 "$W/$c.C.log"); tr=$(tail -1 "$W/$c.R.log")
  if [ "$a" = "$b" ] && [ "$n" -gt 0 ]; then
    echo "$c: $n decisions, identical actions ($a)"
  else
    echo "$c: DIFFERENT ($a vs $b, $n lines)"; fail=1
  fi
  echo "   C    $tc"
  echo "   Rust $tr"
done
echo "work dir: $W"
exit $fail
