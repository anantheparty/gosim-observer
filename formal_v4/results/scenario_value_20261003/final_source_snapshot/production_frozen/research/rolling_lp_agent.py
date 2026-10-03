#!/usr/bin/env python3
"""Local experimental rolling coverage entrypoint; keeps stable package separate."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import traceback

os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from policy import Policy
from research.rolling_coverage import RollingCoveragePlanner


class RollingPolicy(Policy):
    def __init__(self,initial):
        if Path(__file__).resolve().parents[1].joinpath('remote_runtime.json').exists():
            raise ValueError('rolling prototype requires an isolated CPU project without remote_runtime.json')
        super().__init__(initial)
        cfg=self.config.get('rolling',{})
        self.planner=RollingCoveragePlanner(initial,**cfg)

    def summary(self):
        return {**super().summary(),'rolling':self.planner.rolling_summary()}


def main():
    policy=None
    for line in sys.stdin:
        if not line.strip():continue
        message=json.loads(line);kind=message.get('message_type')
        if kind=='initialize':policy=RollingPolicy(message['payload'])
        elif kind=='decision_request':
            try:action=policy.decide(message['payload']) if policy else {'action':'wait','duration_seconds':900}
            except Exception:
                traceback.print_exc(file=sys.stderr);action={'action':'wait','duration_seconds':900}
            if policy and policy.config.get('rolling_trace',False) and action.get('action')=='observe':
                record=json.dumps({'rolling_trace':{'now_utc':message['payload']['now_utc'],'action':action,
                    'prediction':policy.planner.last_prediction,'model':policy.planner.last_model_summary,
                    'current_best_science':float(policy.scores.sum()),'required_missing':int((policy.factor_lower<policy.planner.req_threshold)[policy.planner.required].sum())}},
                    separators=(',',':'))
                trace_path=policy.config.get('rolling_trace_path')
                if trace_path:
                    with Path(trace_path).open('a') as sink:sink.write(record+'\n')
                else:print(record,file=sys.stderr,flush=True)
            print(json.dumps({'protocol_version':'participant-agent-protocol-v4','message_type':'decision_response',
                'decision_sequence':message['decision_sequence'],**action},separators=(',',':'),allow_nan=False),flush=True)
        elif kind=='finish':
            if policy:print(json.dumps(policy.summary(),separators=(',',':')),file=sys.stderr,flush=True)
            break


if __name__=='__main__':main()
