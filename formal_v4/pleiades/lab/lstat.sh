#!/bin/bash
# lstat.sh <name> : summary of local runs
cd /home/shu/kamico/observer/work/runs/$1 || exit
for c in *; do if [ -f $c/summary.json ]; then python3 -c "
import json;d=json.load(open('$c/summary.json'));p=d.get('policy',{})
print('$c',round(d['total'],1),'sci',round(d['sum_best_scores'],1),'req',d['required_missing'],'rep',d['report_settlement'],p.get('reports'),p.get('correct_reports'),'rq',d['observation_request_reward'],'cpu',d['policy_cpu'],d['termination'][:8],'obs',d['observe_actions'])"; else echo "$c running"; fi; done
