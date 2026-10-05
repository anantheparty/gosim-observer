#!/bin/bash
# usage: dockertest.sh <zip> <card-name-in-local-cards or abs path> -> runs the package in python:3.12-slim with the official runner
ZIP=$1; CARD=$2
D=/home/shu/kamico/observer/work/dtest/$(basename $ZIP .zip)_$(basename $CARD)
mkdir -p /home/shu/kamico/observer/work/dtest; docker run --rm -v /home/shu/kamico/observer/work/dtest:/d python:3.12-slim rm -rf /d/$(basename $D) 2>/dev/null; rm -rf $D 2>/dev/null
mkdir -p $D/agent $D/out
python3 -c "import zipfile,sys;zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" $ZIP $D/agent
EX=/home/shu/kamico/observer/gosim-observer/formal_v4/upstream/gosim-observer-examples
case $CARD in /*) CM="-v $CARD:/card:ro"; CP=/card;; *) CM=""; CP=/ex/local-cards/$CARD;; esac
docker run --rm --network host -e HTTPS_PROXY=http://127.0.0.1:7890 -e HTTP_PROXY=http://127.0.0.1:7890 -v $D/agent:/agent -v $EX:/ex:ro $CM -v $D/out:/out python:3.12-slim bash -c "cd /agent && python3 -m pip install --no-cache-dir --disable-pip-version-check --target .deps -r requirements.txt -q 2>&1 | tail -1; cd /ex/runner && python3 run_local.py --card $CP --agent 'python3 -u agent.py' --agent-cwd /agent --out /out/run --quiet; chown -R 1000:1000 /out /agent" 2>&1 | tail -3
python3 -c "
import json,sys
r=json.load(open(sys.argv[1]+'/out/run/score_report.json'))
w=json.load(open(sys.argv[1]+'/out/run/workflow_result.json'))
print('TOTAL',r['total'],r['components'],'term',w.get('termination_reason'),'accounted',w.get('accounted_wallclock_seconds'))" $D
