#!/usr/bin/env python3
"""Standalone same-source baseline/hierarchical filter participant."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import traceback

os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'runs/cold_neural_value_20261003/production_frozen'
sys.path.insert(0,str(SOURCE))
from policy import Policy
from research.geometry import parse_utc
from generator_forecast_model import HierarchicalClock

PARAMS={'night_variance':.03,'slot_variance':.015,'measurement_variance':.04}

class ForecastPolicy(Policy):
    def __init__(self, initial):
        super().__init__(initial)
        self.belief_clock=HierarchicalClock(self.planner.nights,self.slot_seconds,
            initial_time=initial['survey']['start_utc'],**PARAMS)

    def _ingest_result(self,snapshot):
        report=(snapshot.get('last_result') or {}).get('action')=='report'
        super()._ingest_result(snapshot)
        if report:
            self.belief_clock.reset(parse_utc(snapshot['now_utc']))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--mode',choices=['baseline','hierarchical'],required=True)
    mode=ap.parse_args().mode
    policy=None
    for line in sys.stdin:
        if not line.strip():continue
        m=json.loads(line);kind=m.get('message_type')
        if kind=='initialize':
            policy=(Policy if mode=='baseline' else ForecastPolicy)(m['payload'])
        elif kind=='decision_request':
            try:action=policy.decide(m['payload'])
            except Exception:
                traceback.print_exc(file=sys.stderr);raise
            print(json.dumps({'protocol_version':'participant-agent-protocol-v4',
                'message_type':'decision_response','decision_sequence':m['decision_sequence'],**action},
                separators=(',',':'),allow_nan=False),flush=True)
        elif kind=='finish':
            print(json.dumps(policy.summary()),file=sys.stderr,flush=True);break
    if policy and policy.remote:policy.remote.close()

if __name__=='__main__':main()
