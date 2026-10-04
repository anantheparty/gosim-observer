"""Historical public-score projection and reconstructed strong state.

No true factor/quality/program multiplier/valid flags enter this module.
No historical action parity is claimed. Future entries are not passed to actor.
"""
import csv,copy,hashlib,json,math,sys
from datetime import timedelta
from pathlib import Path
import numpy as np
OUT=Path(__file__).resolve().parent; ROOT=OUT.parents[2]
sys.path.insert(0,str(OUT/'baseline_package'))
from sparse_exact import install
install()
from research.agent_request_exact_cache import ExactCachedRequestPolicy
import wrapper
from research.spatial_candidates import parse_utc,local_sidereal
from research.feedback_model import seasonal_quality


def initial(card):
    root=ROOT/'formal_v4/upstream/gosim-observer-examples/local-cards'/card
    fiber=json.loads((root/'config/v4_fiber_config.json').read_text())
    scoring=json.loads((root/'config/v4_score_config.json').read_text())
    with (root/'public/targets.csv').open() as h:
        reader=csv.DictReader(h);columns=reader.fieldnames;rows=list(reader)
    with (root/'public/v4_night_calendar.csv').open() as h:nights=list(csv.DictReader(h))
    nf=fiber['field']['n_fibers'];glass=math.sqrt(fiber['field']['fiber_area_deg2']);pitch=glass+fiber['field']['gap_deg']
    return dict(site={**fiber['site'],'minimum_altitude_deg':30.},scoring=scoring,
        instrument={**fiber['field'],'grid_side':math.isqrt(nf),'glass_side_deg':glass,'pitch_deg':pitch,
                    'fov_side_deg':math.isqrt(nf)*pitch,'exposure':fiber['exposure']},
        targets={'columns':columns,'rows':[[r[k] for k in columns] for r in rows]},
        survey={'start_utc':nights[0]['observing_start_utc'],'end_utc':nights[-1]['observing_end_utc'],
                'slot_seconds':900,'nights':nights},limits={'global_wallclock_seconds':900})


def states(card, night_indices):
    init=initial(card);p=wrapper.wrapped(init)
    trace=ROOT/'formal_v4/results/sparse_fault_actual_20261004/seasons/fault_fast'/card
    decs=list(csv.DictReader((trace/'decisions.csv').open()))
    all_events=[json.loads(l) for l in (trace/'messages.jsonl').read_text().splitlines()]
    # A zero-time report returns at the next decision, including when the
    # timestamp equals the report's own start. Timestamp filtering alone would
    # deliver that result before the report. Match sequentially instead.
    report_results=iter(m for m in all_events if m['record_type']=='report_result')
    events=[m for m in all_events if m['record_type']!='report_result']
    actions=[json.loads(l) for l in (trace/'actions.jsonl').read_text().splitlines()]
    observes=[a for a in actions if a['action']=='observe']
    hits={}
    with (trace/'observations.csv').open() as h:
        for row in csv.DictReader(h):
            pub={'target_id':row['target_id'],'score':float(row['score'])}
            hits.setdefault(int(row['observe_index']),[]).append(pub)
    selected={}
    for n in night_indices:
        if n>=len(p.planner.nights):continue
        start,end=p.planner.nights[n]
        candidates=[k for k,r in enumerate(decs) if r['action']=='observe' and
                    start+timedelta(seconds=3600)<=parse_utc(r['start_utc'])<end]
        if candidates:selected[candidates[0]]=n
    cursor=0;last=None;latest_b=latest_f=None;issued={};prefix=hashlib.sha256();results=[]
    for k,r in enumerate(decs):
        now=parse_utc(r['start_utc']);messages=[]
        while cursor<len(events) and parse_utc(events[cursor]['issued_at_utc'])<=now:
            m=events[cursor];messages.append(m);cursor+=1
            if m['record_type']=='bulletin':latest_b=m
            if m['record_type']=='forecast':latest_f=m
            if m['record_type']=='observation_request':issued[m['request_id']]=m
        if last is not None and last['action']=='report':
            public_report=next(report_results,None)
            if public_report is None or parse_utc(public_report['issued_at_utc'])>now:
                raise RuntimeError('cannot reconstruct public report result')
            messages.append(public_report)
            last={**last,**public_report}
        active=[m for m in issued.values() if parse_utc(m['deadline_utc'])>now]
        snapshot={'now_utc':r['start_utc'],'survey_end_utc':init['survey']['end_utc'],
            'observe_action_index':sum(d['action']=='observe' for d in decs[:k]),
            'running_total':float(p.scores.sum()),'new_messages':messages,'latest_bulletin':latest_b,
            'latest_forecast':latest_f,'last_result':last,'active_requests':active,
            'wallclock':{'remaining_seconds':900}}
        p._ingest_result(snapshot);p._messages(snapshot)
        n=p._night(now);seasonal=seasonal_quality(now.timetuple().tm_yday,p.planner.q0)[0]
        C,E=p.belief_clock.prior(p.C,p.E,now,seasonal);p.last_night=n
        if k in selected:
            env={**p.config,'quality_scale':C*E*p.planner.q0,'program_band_quality_scale':C*p.planner.q0,
                 'target_quality_scale':p._target_scale(now),'use_bulletin_directional_prior':False}
            if p.calibrator:env['pointing_offset_alt_deg'],env['pointing_offset_az_deg']=p.calibrator.estimate[:2]
            meta={'card':card,'night_index':selected[k],'decision_row':k,'now_utc':r['start_utc'],'prefix_sha256':prefix.hexdigest(),
                  'score_sum':float(p.scores.sum()),'C':C,'E':E,'active_request_count':len(active),
                  'pointing_offset_estimate':[float(env.get('pointing_offset_alt_deg',0)),float(env.get('pointing_offset_az_deg',0))],
                  'historical_action_parity_claimed':False,'trace_root':str(trace)}
            # Consumer runs immediately; science choose changes planner caches
            # only. Subsequent history explicitly installs the recorded pending
            # action, never the experimental action or its predicted feedback.
            yield p,copy.deepcopy(snapshot),copy.deepcopy(env),meta
        if r['action']=='observe':
            rank=int(r['observe_index']);a=copy.deepcopy(observes[rank]);pl=p.planner
            alt,az,_,_=pl._altaz(local_sidereal(now,pl.lon))
            prediction={tid:{'alt_deg':float(alt[pl.index[tid]]),'az_deg':float(az[pl.index[tid]])}
                        for tid in a['assignments'].values()}
            p.pending={'action':a,'start':now,'prediction':prediction,'notices':list(p.notices),'prior_C':C,'prior_E':E}
            last={'action':'observe','observe_index':rank,'hits':hits.get(rank,[]),
                  'assigned_count':len(a['assignments']),'hit_count':len(hits.get(rank,[]))}
            prefix.update((json.dumps(a,sort_keys=True,separators=(',',':'))+'\n').encode())
        elif r['action']=='report':p.pending={'action':{'action':'report'}};last={'action':'report'}
        else:p.pending=None;last={'action':'wait'}
        if selected and k>=max(selected):break
