#!/bin/bash
# upload o4s_sophon3, wait for preparation, approve, evaluate in the Sophon phase
cd /home/shu/kamico/observer/gosim-observer/formal_v4/platform_tools
set -a; source ~/.gosim_cred; set +a
LOG=/home/shu/kamico/observer/work/online/submit_sophon3.log
out=$(timeout 600 python3 submit_tool.py upload --zip /home/shu/kamico/observer/work/packages/o4s_sophon3.zip --title "o4s sophon3 probe (jupiter dive)" 2>&1)
echo "$out" | tail -3 >> $LOG
rid=$(echo "$out" | grep -o '"revision_id": "[0-9a-f-]*"' | head -1 | cut -d'"' -f4)
[ -z "$rid" ] && { echo "no revision" >> $LOG; exit 1; }
echo "revision $rid" >> $LOG
timeout 1900 python3 submit_tool.py wait --revision $rid 2>&1 | tail -2 >> $LOG
timeout 300 python3 submit_tool.py approve --revision $rid 2>&1 | tail -2 >> $LOG
timeout 300 python3 submit_tool.py evaluate --revision $rid --phase 4c3f7330-6659-40c8-b563-ec15b3585a1b 2>&1 | tail -2 >> $LOG
echo done >> $LOG
