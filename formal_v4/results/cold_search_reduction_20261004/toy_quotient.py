#!/usr/bin/env python3
"""Tiny finite ledger family, exact count of payoff transposition classes.

This is an algebraic ledger family; it does not enumerate legal physical schedules.
"""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np

OUT=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location("audit",OUT/"audit.py")
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
now=datetime(2026,1,1,tzinfo=timezone.utc)
cfg={"required":{"observed_factor_threshold":.5,"penalty_per_missing":50},
     "uniformity":{"observed_factor_threshold":.5,"weight":200,"ra_band_width_deg":10}}
targets=[dict(target_id=f"r{i}",ra_deg=0. if i<4 else 20.,required=True) for i in range(8)]
targets += [dict(target_id="l0",ra_deg=0.,required=True),dict(target_id="l1",ra_deg=20.,required=True)]
request=dict(request_id="q",issued_at_utc=now-timedelta(seconds=900),deadline_utc=now+timedelta(seconds=3600),
             target_ids=["r0","r1","r4","r5","l0","l1"],minimum_completed=3,
             completion_factor_threshold=.5,completion_reward=100.)
retired=np.array([True]*8+[False]*2)
classes={}
max_error=0.
cases=0
for mask in range(256):
    history=m.BestLedger()
    for i in range(8):
        if mask & (1<<i):
            start=now-timedelta(seconds=600-i*60)
            history.record(i,f"r{i}",1.,1.,start,start+timedelta(seconds=60))
    st=m.summary(history,targets,cfg,[request],now,retired)
    key=(st["fixed_science"],st["fixed_missing"],tuple(st["fixed_obs"]),st["request_constant"],
         tuple(c for q,d,c in st["active"]))
    curve=[]
    for g0 in (0.,.49,.5,1.):
        for g1 in (0.,.49,.5,1.):
            future=m.BestLedger()
            future.entries=list(history.entries)
            for j,g in enumerate((g0,g1)):
                future.record(8+j,f"l{j}",g,g,now+timedelta(seconds=60*j),now+timedelta(seconds=60*(j+1)))
            exact=m.terminal(future,targets,cfg,[request])["payoff"]
            value=m.state_terminal(m.summary(future,targets,cfg,[request],now,retired),cfg)
            max_error=max(max_error,abs(exact-value))
            curve.append(exact)
            cases+=1
    old=classes.get(key)
    if old is not None:
        assert curve == old
    else:
        classes[key]=curve
assert max_error < 1e-10
result=dict(scope="Synthetic finite ledgers only; retired-target premise imposed, no legal season action search.",
            histories=256,payoff_transposition_classes=len(classes),reduction=1-len(classes)/256,
            future_cases_per_history=16,official_settlements=cases,max_error=max_error,
            observe_index_preserved=8,remaining_loss_assumed=False)
(OUT/"toy_quotient.json").write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps(result,indent=2))
