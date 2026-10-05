#!/bin/bash
# usage: dockertest2.sh <zip> <card dir (abs path)> [tag] -> runs the package in python:3.12-slim with the platform's
# current engine and fair clock (hackathon-survey26/examples/_local/runner: speed factor, wall cap, CPU metering)
ZIP=$1; CARD=$2; TAG=${3:-}
D=/home/shu/kamico/observer/work/dtest3/$(basename $ZIP .zip)_$(basename $CARD)$TAG
mkdir -p /home/shu/kamico/observer/work/dtest3; docker run --rm -v /home/shu/kamico/observer/work/dtest3:/d python:3.12-slim rm -rf /d/$(basename $D) 2>/dev/null; rm -rf $D 2>/dev/null
mkdir -p $D/agent $D/out
python3 -c "import zipfile,sys;zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" $ZIP $D/agent
RUN=/home/shu/kamico/observer/hackathon-survey26/examples/_local/runner
docker run --rm --cpus 2 --memory 2g --memory-swap 2g --network host -e HTTPS_PROXY=http://127.0.0.1:7890 -e HTTP_PROXY=http://127.0.0.1:7890 -v $D/agent:/agent -v $RUN:/runner:ro -v $CARD:/card:ro -v $D/out:/out python:3.12-slim bash -c "cd /agent && python3 -m pip install --no-cache-dir --disable-pip-version-check --target .deps -r requirements.txt -q 2>&1 | tail -1; cd /runner && PYTHONPATH=/agent/.deps python3 run_local.py --card /card --agent 'python3 -u agent.py' --agent-cwd /agent --out /out/run --quiet > /out/summary.json; cat /sys/fs/cgroup/memory.peak > /out/memory_peak.txt 2>/dev/null; chown -R 1000:1000 /out /agent" 2>&1 | tail -3
python3 -c "
import json,sys
s=json.load(open(sys.argv[1]+'/out/summary.json'))
print('TOTAL', s['total'], 'term', s['termination_reason'], 'req_miss', s['required_missing'], 'factor', s['speed_factor'])
print('clock', s['fair_clock'])" $D
echo "memory_peak_bytes $(cat $D/out/memory_peak.txt 2>/dev/null)"
