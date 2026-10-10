#!/bin/bash
# sophon_eval.sh /home/shu/kamico/observer/work/packages/o4s_sophon<NAME>.zip "TITLE"
# Sophon phase only: secret-scan the zip, upload it, wait for preparation, approve, wait until the team has no active
# evaluation, evaluate in the Sophon phase, wait for the run (and for the score step of a survey_complete run),
# then save the result, platform diagnostics and the Sophon boards under work/online/<NAME>_<batch4>/.
# Credentials are loaded here and never printed. At most 12 uploads per UTC day.
set -uo pipefail
ZIP="${1:-}"; TITLE="${2:-sophon probe}"
case "$ZIP" in /home/shu/kamico/observer/work/packages/o4s_sophon*.zip) ;; *) echo "zip must be work/packages/o4s_sophon*.zip" >&2; exit 2;; esac
[ -f "$ZIP" ] || { echo "no such zip" >&2; exit 2; }
NAME=$(basename "$ZIP" .zip)
LOG=/home/shu/kamico/observer/work/online/sophon_eval.log
STAMPS=/home/shu/kamico/observer/work/online/sophon_eval.stamps
today=$(date -u +%F)
n=$(grep -c "^$today" "$STAMPS" 2>/dev/null || true)
if [ "${n:-0}" -ge 12 ]; then echo "daily cap: 12 Sophon uploads already today" >&2; exit 3; fi
SOPHON=4c3f7330-6659-40c8-b563-ec15b3585a1b
cd /home/shu/kamico/observer/gosim-observer/formal_v4/platform_tools
set -a; source ~/.gosim_cred; source ~/.gosim_llm; set +a
python3 - "$ZIP" <<'PY' || { echo "secret scan failed: not uploaded" | tee -a "$LOG" >&2; exit 4; }
import os, re, sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
pats = [p.strip().lower() for p in open(os.path.expanduser('~/.gosim_scan_patterns')) if p.strip()] if os.path.exists(os.path.expanduser('~/.gosim_scan_patterns')) else []   # personal identifiers and key prefixes, kept outside the repo
vals = [os.environ.get(k, '') for k in ('GOSIM_PASSWORD', 'GOSIM_EMAIL', 'OPENAI_API_KEY')]
tok = re.compile(r'(sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|s26_[A-Za-z0-9]{10,}|eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+)')
bad = 0
for n in z.namelist():
    d = z.read(n).decode('utf-8', 'replace')
    bad += sum(1 for p in pats if p in d.lower()) + sum(1 for v in vals if v and v in d) + len(tok.findall(d))
sys.exit(1 if bad else 0)
PY
unset OPENAI_API_KEY OPENAI_BASE_URL OPENAI_MODEL
echo "$today $(date -u +%T) $NAME" >> "$STAMPS"
echo "$(date -u +%FT%TZ) upload $NAME" >> "$LOG"
out=$(timeout 600 python3 submit_tool.py upload --zip "$ZIP" --title "$TITLE" 2>&1)
rid=$(echo "$out" | grep -o '"revision_id": "[0-9a-f-]*"' | head -1 | cut -d'"' -f4)
[ -z "$rid" ] && { echo "upload failed: $(echo "$out" | tail -1 | cut -c1-200)" | tee -a "$LOG"; exit 5; }
echo "$NAME revision $rid" | tee -a "$LOG"
timeout 1900 python3 submit_tool.py wait --revision $rid 2>&1 | tail -1 | cut -c1-300 | tee -a "$LOG"
timeout 300 python3 submit_tool.py approve --revision $rid 2>&1 | tail -1 | cut -c1-200 | tee -a "$LOG"
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
bid=""
for i in $(seq 1 240); do
  if [ "$(active 2>/dev/null | tail -1)" = "0" ]; then
    out=$(timeout 120 python3 submit_tool.py evaluate --revision $rid --phase $SOPHON 2>&1)
    bid=$(echo "$out" | grep -o '"batch_id": "[0-9a-f-]*"' | cut -d'"' -f4)
    [ -n "$bid" ] && break
  fi
  sleep 60
done
[ -z "$bid" ] && { echo "$NAME: could not start (team busy for 4 h)" | tee -a "$LOG"; exit 6; }
echo "$NAME sophon batch $bid" | tee -a "$LOG"
while true; do
  timeout 120 python3 submit_tool.py status --batch $bid > /tmp/sophon_eval_st_$$.txt 2>&1
  grep -q -E '"(running|queued)"' /tmp/sophon_eval_st_$$.txt || break
  sleep 20
done
OUT=/home/shu/kamico/observer/work/online/${NAME}_${bid:0:4}
timeout 120 python3 - "$bid" "$OUT" <<'PY'
import json, os, sys, time
sys.dont_write_bytecode = True
sys.path.insert(0, '.')
from submit_tool import WriteClient
bid, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
c = WriteClient(); c.login(os.environ['GOSIM_EMAIL'], os.environ['GOSIM_PASSWORD'])
for wait in range(20):           # a survey_complete run gets a 'score' step about 1-2 minutes after the engine
    runs = [r for b in c.portal('list').get('batches') or [] if b['id'] == bid for r in b.get('observer_runs') or []]
    diag = {r['id']: c.portal('diagnostics', run_id=r['id']) or [] for r in runs}
    term = [((r.get('score_summary') or {}).get('termination_reason')) for r in runs]
    if all(any(x.get('kind') == 'score' for x in d) for d in diag.values()) or 'survey_complete' not in term:
        break
    time.sleep(30)
json.dump(diag, open(out + '/diagnostics.json', 'w'), indent=1)
boards = {}
for fn in ('sophon_board', 'sophon_totals', 'sophon_finishers'):
    try:
        boards[fn] = c._json('POST', '/rest/v1/rpc/' + fn, body={})
    except Exception as e:
        boards[fn] = 'ERR ' + str(e)[:100]
json.dump(boards, open(out + '/boards.json', 'w'), indent=1)
print('diagnostics', {k[:8]: [(x.get('kind'), x.get('status')) for x in v] for k, v in diag.items()}, 'termination', term)
PY
timeout 300 python3 submit_tool.py fetch --batch $bid --out "$OUT" 2>&1 | tail -1 | tee -a "$LOG"
rm -f /tmp/sophon_eval_st_$$.txt
echo "$(date -u +%FT%TZ) done $NAME -> $OUT" | tee -a "$LOG"
