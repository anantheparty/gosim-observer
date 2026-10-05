#!/bin/bash
# rfetch.sh <name> [full] : copy remote run summaries (or full run dirs) into rruns/<name>
mkdir -p /home/shu/kamico/observer/work/rruns/$1
if [ "$2" == "full" ]; then
  rsync -az -e "ssh -o BatchMode=yes" --exclude log.txt elevatia-wsl:obswork/runs/$1/ /home/shu/kamico/observer/work/rruns/$1/
else
  rsync -az -e "ssh -o BatchMode=yes" --include='*/' --include='summary.json' --exclude='*' elevatia-wsl:obswork/runs/$1/ /home/shu/kamico/observer/work/rruns/$1/
fi
