#!/usr/bin/env python3
"""Complete native seasons for the constructive sweep + preserved CPUPhase."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time
BASE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('candidate_geometry_experiment',BASE/'research/candidate_geometry_experiment.py')
ex=importlib.util.module_from_spec(spec);sys.modules[spec.name]=ex;spec.loader.exec_module(ex)
spec=importlib.util.spec_from_file_location('research.candidate_geometry_union',BASE/'research/candidate_geometry_union.py')
un=importlib.util.module_from_spec(spec);sys.modules[spec.name]=un;spec.loader.exec_module(un)

def run(card):
    ex.policy.SpatialPlanner=un.CandidateGeometryUnionPlanner
    initial=ex.V4Workflow(ex.OFFICIAL/'local-cards'/card).initialize_payload(900)
    p=ex.policy.Policy(initial);assert p.remote is None
    raw=ex.OUT/'union'/card;raw.mkdir(parents=True,exist_ok=True)
    begin=time.perf_counter();calls=0
    def decide(snapshot):
        nonlocal calls
        action=p.decide(snapshot);calls+=1
        if calls%250==0:
            print(json.dumps(dict(event='progress',card=card,mode='union',calls=calls,observe=snapshot['observe_action_index'],
                                  now=snapshot['now_utc'],seconds=time.perf_counter()-begin)),flush=True)
        return action
    report=ex.run_scenario(ex.OFFICIAL/'local-cards'/card/'config/v4_scenario.json',lambda _:decide,raw)
    result=dict(card=card,mode='union',seconds=time.perf_counter()-begin,total=report['total'],components=report['components'],
                counts=report['counts'],termination=report['termination'],policy_summary=p.summary(),source_sha256=ex.manifest(),
                geometry_summary=p.planner.geometry_summary,phase_summary=p.planner.phase.cpu_phase_summary)
    (raw/'experiment_summary.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--card',choices=['L1','L2','L3','L4'],required=True)
    run(parser.parse_args().card)
