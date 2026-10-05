#!/bin/bash
# usage: runcard.sh <card-name-or-path> <agent-dir> <out-dir> [cpus] [entry]
CARD=$1; AGENT=$2; OUT=$3; CPUS=${4:-0,1}; ENTRY=${5:-"python3 -u agent.py"}
EX=/home/shu/kamico/observer/gosim-observer/formal_v4/upstream/gosim-observer-examples
[ -d "$CARD" ] || CARD=$EX/local-cards/$CARD
mkdir -p "$OUT"
cd $EX/runner && taskset -c $CPUS python3 run_local.py --card "$CARD" --agent "$ENTRY" --agent-cwd "$AGENT" --out "$OUT" --quiet > "$OUT/summary.json" 2> "$OUT/runner.err"
