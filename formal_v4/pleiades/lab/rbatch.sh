#!/bin/bash
# remote batch: rbatch.sh <name> <pkgdir-local> <cards...> -- [env KEY=VAL ...]   (runs on elevatia-wsl)
NAME=$1; PKG=$2; shift 2
CARDS=(); while [ $# -gt 0 ] && [ "$1" != "--" ]; do CARDS+=("$1"); shift; done
[ "$1" == "--" ] && shift
ENVS=""; for kv in "$@"; do ENVS="$ENVS --env '$kv'"; done
rsync -az -e "ssh -o BatchMode=yes" $PKG/ elevatia-wsl:obswork/pkgs/$NAME/
for c in "${CARDS[@]}"; do
ssh -n -o BatchMode=yes elevatia-wsl "cd ~/obswork && mkdir -p runs/$NAME/$c && { OBS_EX=\$HOME/obswork OBS_WORLDS=\$HOME/obswork/worlds nohup ~/gosim-gpu-venv-20260926/bin/python harness.py --card $c --agent-dir \$HOME/obswork/pkgs/$NAME --factory harness_entry:make --out runs/$NAME/$c ${HARNESS_ARGS} $ENVS > runs/$NAME/$c/log.txt 2>&1 < /dev/null & }"
done
