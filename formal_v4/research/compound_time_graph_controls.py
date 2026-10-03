#!/usr/bin/env python3
"""Official held-out adjudication controls; never candidate selection."""
import csv,json,sys,hashlib
from pathlib import Path
sys.dont_write_bytecode=True
BASE=Path(__file__).resolve().parents[1];UP=BASE/'upstream/gosim-observer-examples';OUT=BASE/'results/compound_time_graph_20261004';sys.path.insert(0,str(UP))
from runner.challenge.v4_runner import run_scenario
TRACE={'L1':BASE/'results/geometry_native_20261003/protocol_gate_remaining/L1','L2':BASE/'results/geometry_native_20261003/protocol_gate_retry/L2'}
for card in ['L1','L2']:
 r=json.loads((OUT/f'{card}_result.json').read_text());tape=[json.loads(x) for x in (TRACE[card]/'actions.jsonl').read_text().splitlines()];n=r['prefix_actions'];remaining=r['horizon_seconds'];control=[]
 for action in tape[n:]:
  a=dict(action)
  if a['action']=='report':control.append(a);continue
  assert a['action']=='observe',a
  d=min(remaining,a['duration_seconds']);assert d>=60
  a['duration_seconds']=d;control.append(a);remaining-=d
  if remaining==0:break
 plan=tape[:n]+control;seq=0
 def decide(snapshot):
  global seq
  if seq>=len(plan):return None
  a=plan[seq];seq+=1;return a
 report=run_scenario(UP/'local-cards'/card/'config/v4_scenario.json',lambda _:decide,OUT/f'{card}_source_multifield')
 r['source_multifield_control']=dict(actions=control,official_micro_terminal=report['total'],official_components=report['components'],official_counts=report['counts'],final_action_clipped_to_public_slot_end=True,role='held-out historical native action tape, final duration clipped; no candidate-selection role')
 r['official_best_minus_source_multifield']=r['search']['best']['official_micro_terminal']-report['total'];(OUT/f'{card}_result.json').write_text(json.dumps(r,indent=2,allow_nan=False)+'\n');print(card,r['official_best_minus_source_multifield'],[a.get('duration_seconds',0) for a in control],report['components'])
