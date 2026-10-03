"""Public-only replay of short-exposure feasible sets; truth is validation only."""
from __future__ import annotations

import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
import bisect
import copy
from collections import defaultdict
import csv
import json
import math
from pathlib import Path
import sys
from datetime import timedelta

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'runs/geometry_native_20261003/release'
sys.path.insert(0,str(SOURCE))
sys.path.insert(1,str(ROOT/'research'))
import numpy as np
import policy
from research.geometry_native import load_library
from research.candidate_geometry_sweep import CandidateGeometryPlanner
load_library()
policy.SpatialPlanner=CandidateGeometryPlanner
from research.feedback_model import seasonal_quality
from research.geometry import local_sidereal_deg,parse_utc,format_utc
from band_identification_runtime import PublicSlotConstraint,contains


def csvrows(path):
    with path.open(newline='') as f:return list(csv.DictReader(f))


def public_initial(card):
    """Construct only fields present in actual initialize, using public files."""
    base=ROOT/'upstream/gosim-observer-examples/local-cards'/card
    scenario=json.loads((base/'config/v4_scenario.json').read_text())
    fiber=json.loads((base/'config/v4_fiber_config.json').read_text())
    scoring=json.loads((base/'config/v4_score_config.json').read_text())
    nights=csvrows(base/'public/v4_night_calendar.csv')
    nights=[{k:r[k] for k in ('night_id','night_date','observing_start_utc','observing_end_utc')}|{'slot_count':int(r['slot_count'])} for r in nights]
    columns=['target_id','ra_deg','dec_deg','target_class','feature_flux','science_weight','required']
    targets=csvrows(base/'public/targets.csv')
    rows=[[r[k] if k in ('target_id','target_class') else r[k].lower()=='true' if k=='required' else float(r[k]) for k in columns] for r in targets]
    field=fiber['field'];side=math.isqrt(field['n_fibers']);glass=math.sqrt(field['fiber_area_deg2']);pitch=glass+field['gap_deg']
    # Public slot_seconds is also recoverable from exact public night duration/count.
    slot_seconds=round((parse_utc(nights[0]['observing_end_utc'])-parse_utc(nights[0]['observing_start_utc'])).total_seconds()/nights[0]['slot_count'])
    initial=dict(site=scenario['site']|{'minimum_altitude_deg':scenario['minimum_altitude_deg']},
                 survey=dict(start_utc=nights[0]['observing_start_utc'],end_utc=nights[-1]['observing_end_utc'],slot_seconds=slot_seconds,nights=nights),
                 instrument=field|dict(grid_side=side,glass_side_deg=round(glass,6),pitch_deg=round(pitch,6),fov_side_deg=round(side*pitch,6),exposure=fiber['exposure']),
                 scoring=scoring,targets=dict(columns=columns,rows=rows),limits=dict(global_wallclock_seconds=900))
    return initial,base


def audit(card,trace):
    initial,base=public_initial(card);p=policy.Policy(initial);p.remote=None
    gate=PublicSlotConstraint(initial)
    bulletins=list(map(json.loads,(base/'public/v4_bulletins.jsonl').read_text().splitlines()))
    times=[parse_utc(b['issued_at_utc']) for b in bulletins]
    messages=list(map(json.loads,(trace/'messages.jsonl').read_text().splitlines()))
    reports={r['issued_at_utc']:r for r in messages if r.get('record_type')=='report_result'}
    actions=[a for a in map(json.loads,(trace/'actions.jsonl').read_text().splitlines()) if a['action']=='observe']
    obs=defaultdict(list)
    for row in csvrows(trace/'observations.csv'):
        # The actual return contains only these two fields. No factor/quality/mult.
        obs[int(row['observe_index'])].append(dict(target_id=row['target_id'],score=float(row['score'])))
    decisions=csvrows(trace/'decisions.csv');cursor=0;counts=defaultdict(int);changes=[];validations=[]
    for d in decisions:
        start,end=parse_utc(d['start_utc']),parse_utc(d['end_utc'])
        pos=bisect.bisect_right(times,start)-1;bulletin=bulletins[pos] if pos>=0 else None
        new=[]
        while cursor<len(messages) and parse_utc(messages[cursor]['issued_at_utc'])<=start:
            new.append(messages[cursor]);cursor+=1
        p._messages(dict(new_messages=new,latest_bulletin=bulletin,active_requests=[]))
        seasonal=seasonal_quality(start.timetuple().tm_yday,p.planner.q0)[0]
        priorc,priore=p.belief_clock.prior(p.C,p.E,start,seasonal)
        correction=gate.constrain(start,priorc,priore)
        if correction is not None:
            change=dict(observe_index=d['observe_index'],time=d['start_utc'],key=list(gate.key),
                                original_C=priorc,original_E=priore,projected_C=correction[0],projected_E=correction[1],
                                source_indices=gate.indices[:],programs=sorted(gate.programs))
            # This sole conflict is outside active request windows. At this time
            # public expired-request proofs and the score ledger reproduce source.
            active=[m for m in messages if m.get('record_type')=='observation_request' and parse_utc(m['issued_at_utc'])<=start<parse_utc(m['deadline_utc'])]
            if not active and d['action']=='observe':
                env=dict(p.config,quality_scale=priorc*priore*p.planner.q0,
                         program_band_quality_scale=priorc*p.planner.q0,
                         target_quality_scale=p._target_scale(start),use_bulletin_directional_prior=False)
                if p.calibrator:
                    estimate=p.calibrator.estimate;env['pointing_offset_alt_deg'],env['pointing_offset_az_deg']=estimate[:2]
                snap=dict(now_utc=d['start_utc'],latest_bulletin=bulletin,new_messages=[],active_requests=[])
                left,right=copy.deepcopy(p.planner),copy.deepcopy(p.planner)
                original=left.choose(snap,p.scores.copy(),p.factor_lower.copy(),env,[])
                adjusted=env|dict(quality_scale=correction[0]*correction[1]*p.planner.q0,
                                  program_band_quality_scale=correction[0]*p.planner.q0)
                projected=right.choose(snap,p.scores.copy(),p.factor_lower.copy(),adjusted,[])
                change.update(original_action=original,projected_action=projected,
                              action_changed=original!=projected,
                              original_matches_recorded_native=original==actions[int(d['observe_index'])],
                              point_state_science_sum=float(p.scores.sum()),
                              original_rate=left.stats.get('selected_exact_rate'),projected_rate=right.stats.get('selected_exact_rate'),
                              candidate_backend='locked Darwin native, NumPy '+np.__version__)
            changes.append(change)
        if d['action']=='report':
            gate.clear();p.pending={'action':{'action':'report'}}
            p._ingest_result(dict(now_utc=d['end_utc'],last_result={'action':'report',**reports[d['start_utc']]}));continue
        if d['action']!='observe':continue
        counts['observe']+=1;idx=np.array([p.planner.index[h['target_id']] for h in obs[int(d['observe_index'])]],int)
        duration=(end-start).total_seconds()
        H=p._geometric_H(start,duration,idx) if len(idx) else []
        hits=[dict(score=h['score'],weight=float(p.planner.weight[i]),flux=float(p.planner.flux[i]),H=float(hh)) for h,i,hh in zip(obs[int(d['observe_index'])],idx,H)]
        accepted=gate.ingest(start,end,d['program'],int(d['observe_index']),hits,bulletin)
        if accepted:
            validations.append(dict(observe_index=int(d['observe_index']),slot_id=bulletin['slot_id'],states=gate.states))
        lst=local_sidereal_deg(start,p.planner.lon);alt,az,_,_=p.planner._altaz(lst)
        p.pending=dict(action=actions[int(d['observe_index'])],
                       start=start,notices=bulletin['notices'] if bulletin else [],prior_C=priorc,prior_E=priore,
                       prediction={h['target_id']:dict(alt_deg=float(alt[i]),az_deg=float(az[i])) for h,i in zip(obs[int(d['observe_index'])],idx)})
        intervening=[b for b,t in zip(bulletins,times) if start<t<=end]
        p._ingest_result(dict(now_utc=d['end_utc'],last_result=dict(action='observe',observe_index=int(d['observe_index']),hits=obs[int(d['observe_index'])]),new_messages=intervening))
    # Truth is opened only here, after the complete public-only decision audit.
    truth={r['slot_id']:r for r in csvrows(base/'truth/v4_weather_truth.csv')}
    faults=[r for r in csvrows(base/'truth/v4_events.csv') if r['event_type']=='instrument_fault']
    repair_times=[parse_utc(r['issued_at_utc']) for r in reports.values() if r['correct']]
    valid=0
    for v in validations:
        row=truth[v['slot_id']];C=float(row['transparency'])*float(row['sky_quality'])/(float(row['seeing_arcsec'])*initial['scoring']['q0'])
        E=float(row['instrument_efficiency']);d=next(d for d in decisions if d['action']=='observe' and int(d['observe_index'])==v['observe_index']);t=parse_utc(d['start_utc'])
        for f in faults:
            a,b=parse_utc(f['actual_start_utc']),parse_utc(f['actual_end_utc'])
            if a<=t<b and any(a<=rt<=t<b for rt in repair_times):E=min(1.,E/float(f['instrument_efficiency_multiplier']))
        if not contains(v['states'],C,E):raise AssertionError(('truth exclusion',v['observe_index'],C,E))
        valid+=1
    return dict(card=card,trace=str(trace),stats=gate.stats,accepted_truth_states_retained=valid,
                candidate_state_conflicts=changes,pointfit_final_C=p.C,pointfit_final_E=p.E,
                public_score_ledger_sum=float(p.scores.sum()),counts=dict(counts),
                inference_reads_truth=False,validation_reads_truth=True)


def main():
    out=ROOT/'results/band_identification_20261004/stage2';out.mkdir(exist_ok=True)
    cases=[('L2',ROOT/'results/geometry_native_20261003/protocol_gate_retry/L2'),
           ('L2',ROOT/'results/objective_graph_20261004/program_pair/control/L2')]
    result=dict(rows=[audit(*c) for c in cases])
    (out/'public_short_audit.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
