#!/bin/bash
# hand_in.sh 'SOPHON{...}' : hand one flag to the Sophon desk (flag box only).
# Loads the platform credentials internally and never prints them; at most 6 hand-ins per hour.
set -uo pipefail
flag="${1:-}"
if ! [[ "$flag" =~ ^SOPHON\{[^{}]{1,200}\}$ ]]; then echo "usage: hand_in.sh 'SOPHON{...}'" >&2; exit 2; fi
LOG=/home/shu/kamico/observer/work/online/sophon_flags.log
STAMPS=/home/shu/kamico/observer/work/online/sophon_flags.stamps
now=$(date -u +%s)
recent=$(awk -v t=$((now - 3600)) '$1 >= t' "$STAMPS" 2>/dev/null | wc -l)
if [ "$recent" -ge 6 ]; then echo "rate limit: 6 hand-ins in the last hour" >&2; exit 3; fi
echo "$now" >> "$STAMPS"
set -a; source ~/.gosim_cred; set +a
out=$(timeout 120 python3 /home/shu/kamico/observer/work/sophon_desk/hand_in.py "$flag" 2>&1 | tail -1)
echo "$(date -u +%FT%TZ) $out" | tee -a "$LOG"
