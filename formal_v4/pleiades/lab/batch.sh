#!/bin/bash
# usage: batch.sh <name> <pkgdir> <cards...> -- [env KEY=VAL ...]
NAME=$1; PKG=$2; shift 2
CARDS=(); while [ $# -gt 0 ] && [ "$1" != "--" ]; do CARDS+=("$1"); shift; done
[ "$1" == "--" ] && shift
ENVS=(); for kv in "$@"; do ENVS+=(--env "$kv"); done
for c in "${CARDS[@]}"; do
  mkdir -p /home/shu/kamico/observer/work/runs/$NAME/$c
  nohup python3 /home/shu/kamico/observer/work/harness.py --card $c --agent-dir $PKG --factory harness_entry:make --out /home/shu/kamico/observer/work/runs/$NAME/$c ${HARNESS_ARGS} "${ENVS[@]}" > /home/shu/kamico/observer/work/runs/$NAME/$c/log.txt 2>&1 &
done
