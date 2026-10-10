#!/bin/bash
# sophon_chain.sh REV : wait until the team has no active evaluation, start REV in the Sophon phase,
# wait for it to finish and fetch the result into work/online/sophon3_<batch4>
cd /home/shu/kamico/observer/gosim-observer/formal_v4/platform_tools
set -a; source ~/.gosim_cred; set +a
LOG=/home/shu/kamico/observer/work/online/submit_sophon3.log
SOPHON=4c3f7330-6659-40c8-b563-ec15b3585a1b
active() {
  timeout 120 python3 - <<'PY'
import os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, '.')
from submit_tool import WriteClient
c = WriteClient(); c.login(os.environ['GOSIM_EMAIL'], os.environ['GOSIM_PASSWORD'])
print(sum(1 for b in c.portal('list').get('batches') or [] if b.get('status') in ('queued', 'running')))
PY
}
while true; do
  n=$(active 2>/dev/null | tail -1)
  if [ "$n" = "0" ]; then
    out=$(timeout 120 python3 submit_tool.py evaluate --revision $1 --phase $SOPHON 2>&1)
    echo "$(date -u +%H:%M:%S) $(echo "$out" | tail -1 | cut -c1-200)" >> $LOG
    if echo "$out" | grep -q batch_id; then break; fi
  fi
  sleep 60
done
bid=$(echo "$out" | grep -o '"batch_id": "[0-9a-f-]*"' | cut -d'"' -f4)
echo "sophon batch $bid" >> $LOG
while true; do
  timeout 120 python3 submit_tool.py status --batch $bid > /tmp/sophon_st.txt 2>&1
  if ! grep -q -E "running|queued" /tmp/sophon_st.txt; then break; fi
  sleep 30
done
timeout 300 python3 submit_tool.py fetch --batch $bid --out /home/shu/kamico/observer/work/online/sophon3_${bid:0:4} >> $LOG 2>&1
echo "fetched sophon3_${bid:0:4}" >> $LOG
cat /tmp/sophon_st.txt | tail -5
