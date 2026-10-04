"""Short official worlds: actors receive only their own real public feedback.

Validated in-memory fixtures replace only the Scenario loader. All scoring,
geometry, requests, loss, action normalization and runner code is unmodified.
"""
import os
os.environ['OPENBLAS_NUM_THREADS']='1'
os.environ['OMP_NUM_THREADS']='1'
import csv
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from datetime import timedelta
from unittest.mock import patch

OUT=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(OUT/'official'))
sys.path.insert(0,str(OUT/'package'))
sys.path.insert(0,str(OUT/'package/base'))
from challenge import v4_runner as vr, v4_scorer as vs, v4_weather_simulator as wg
from challenge.v4_config_check import validate_scenario
from challenge.v4_fiber_map import FiberGrid,altaz_to_radec,radec_to_altaz,min_altitude_during
from challenge.observing_calendar import Night,Slot
from challenge.v4_workflow import V4Workflow
from binding_model import PublicScoreLedger,terminal_certificate,prenight_certificate

fiber=json.loads((OUT/'v4_fiber_config.json').read_text())
score=json.loads((OUT/'v4_score_config.json').read_text())
site={**fiber['site'],'sun_altitude_limit_deg':-18.}
lat,lon=site['latitude_deg'],site['longitude_deg']
grid=FiberGrid.from_config(fiber);utc=vr._parse_utc;fmt=vr._format_utc
(OUT/'synthetic_footprint.csv').write_text('component_id,vertex_index,ra_deg,dec_deg\nA,0,0,-60\nA,1,360,-60\nA,2,360,30\nA,3,0,30\n')


def target(name,alt,az,t,flux=.5,weight=1.,required=False):
    ra,dec=altaz_to_radec(alt,az,t,lat,lon)
    return dict(target_id=name,ra_deg=ra,dec_deg=dec,target_class='ELG',feature_flux=flux,science_weight=weight,required=required)


def ray_target(name,da,t):
    a,z=math.radians(70),0.
    c=(math.cos(a),0.,math.sin(a));u=(-math.sin(a),0.,math.cos(a))
    v=tuple(c[j]+math.radians(da)*u[j] for j in range(3));norm=math.sqrt(sum(x*x for x in v))
    return target(name,math.degrees(math.asin(v[2]/norm)),math.degrees(math.atan2(v[1],v[0]))%360,t)


def slots(a,b,name='N_SYN',seeing=1.5,open=True):
    rows=[];t=a
    while t<b:
        e=min(b,t+timedelta(seconds=900));rows.append(vs.SlotTruth(f'{name}-S{len(rows)+1:03d}',t,e,open,seeing if open else 0.,1. if open else 0.,1. if open else 0.,1. if open else 0.));t=e
    return rows


def scenario(name,targets,ss,requests=(),stress=()):
    config=dict(schema_version='v4-scenario-v1',name=name,site=site,minimum_altitude_deg=30.,products={'footprint_csv':'synthetic_footprint.csv'},stress={'enabled':bool(stress)})
    sc=vr.Scenario(config,OUT,site,fiber,score,targets,list(ss),[],[],[],list(requests),list(stress),ss[0].start_utc,ss[-1].end_utc)
    validate_scenario(sc);return sc


def initial(sc):
    nights=[]
    for s in sc.slots:
        night=s.slot_id.split('-S',1)[0]
        if not nights or nights[-1]['night_id']!=night:
            nights.append(dict(night_id=night,night_date=s.start_utc.date().isoformat(),observing_start_utc=fmt(s.start_utc),observing_end_utc=fmt(s.end_utc),slot_count=1))
        else:nights[-1]['observing_end_utc']=fmt(s.end_utc);nights[-1]['slot_count']+=1
    cols=['target_id','ra_deg','dec_deg','target_class','feature_flux','science_weight','required']
    return {'site':{**site,'minimum_altitude_deg':30.},'survey':{'start_utc':fmt(sc.survey_start),'end_utc':fmt(sc.survey_end),'slot_seconds':900,'nights':nights},
            'scoring':score,'instrument':{'exposure':fiber['exposure'],'n_fibers':grid.n_fibers,'grid_side':grid.n_side,'fiber_area_deg2':grid.fiber_area_deg2,'gap_deg':0.,'glass_side_deg':grid.fiber_side_deg,'pitch_deg':grid.pitch_deg,'fov_side_deg':grid.fov_side_deg},
            'targets':{'columns':cols,'rows':[[t[c] for c in cols] for t in sc.targets]},'footprint':[]}


def action(ts,t,ra,dec,d,program='BACKUP'):
    alt,az=radec_to_altaz(ra,dec,t,lat,lon);assigned={}
    for target in ts:
        c=grid.classify_target(target['ra_deg'],target['dec_deg'],t,alt,az,lat,lon)
        if c.region=='glass' and c.fiber_id not in assigned:assigned[str(c.fiber_id)]=target['target_id']
    return {'action':'observe','pointing':{'alt_deg':alt,'az_deg':az},'assignments':assigned,'duration_seconds':d,'program':program}


def run(name,sc,schedule,final=None):
    tape=list(schedule);snapshots=[];certificates=[];init=initial(sc);ledger=PublicScoreLedger(init)
    def factory(context):
        def actor(snapshot):
            ledger.ingest(snapshot);snapshots.append(snapshot)
            if tape:a=tape.pop(0)
            elif final:
                a=final(snapshot,init,ledger,certificates)
            else:a={'action':'finish'}
            envelope=dict(a,protocol_version='participant-agent-protocol-v4',message_type='decision_response',decision_sequence=len(snapshots))
            a=V4Workflow.action_from_response(envelope,len(snapshots));vr.normalize_action(a,sc,{t['target_id']:t for t in sc.targets},utc(snapshot['now_utc']))
            return a
        return actor
    stub=OUT/f'{name}_scenario_stub.json';stub.write_text(json.dumps({'validated_synthetic':name})+'\n')
    with patch.object(vr,'load_scenario',return_value=sc):report=vr.run_scenario(stub,factory,OUT/'runs'/name)
    (OUT/'runs'/name/'snapshots.json').write_text(json.dumps(snapshots,indent=2)+'\n')
    (OUT/'runs'/name/'certificates.json').write_text(json.dumps(certificates,indent=2)+'\n')
    return report


def delta(a,b):
    return {'total':round(b['total']-a['total'],6),'components':{k:round(b['components'][k]-a['components'][k],6) for k in a['components']}}


def adversarial():
    a=utc('2026-11-03T00:30:00Z');early=a-timedelta(seconds=2700);e=a+timedelta(seconds=900)
    ts=[ray_target('PAIR_LOW',-1.4,a),ray_target('PAIR_HIGH',1.4,a)]
    ra,dec=altaz_to_radec(70,0,a,lat,lon)
    ss=slots(a-timedelta(days=1),a-timedelta(seconds=57600),'N_PREV',open=False)+slots(a,e,'N_NEXT',seeing=4.)
    pre=action(ts,early,ra,dec,3600);inside=action(ts,a,ra,dec,900)
    sc=scenario('prenight_orientation',ts,ss)
    r0=run('orientation_inside',sc,[{'action':'wait','until_utc':fmt(a)},inside]);r1=run('orientation_pre',sc,[{'action':'wait','until_utc':fmt(early)},pre])
    assert len(pre['assignments'])==2 and len(inside['assignments'])<=1
    # Paired same-prefix worlds: the request is not public at early.
    bright=target('NEW_REQUEST',70,0,a,flux=2.)
    req={'schema_version':'v4-observation-request-v1','record_type':'observation_request','request_id':'R_NIGHT','issued_at_utc':a,'deadline_utc':e,'target_ids':[bright['target_id']],'minimum_completed':1,'completion_factor_threshold':.5,'completion_reward':100.,'reason':'synthetic_information_barrier'}
    p=action([bright],early,bright['ra_deg'],bright['dec_deg'],3600,'BACKUP');q=action([bright],a,bright['ra_deg'],bright['dec_deg'],900,'DARK')
    sc2=scenario('prenight_request',[bright],slots(a-timedelta(days=1),a-timedelta(seconds=57600),'N_PREV',open=False)+slots(a,e,'N_NEXT',seeing=1.),[req])
    n0=run('request_inside',sc2,[{'action':'wait','until_utc':fmt(a)},q]);n1=run('request_pre',sc2,[{'action':'wait','until_utc':fmt(early)},p])
    # Same integration, DARK declaration, diluted q_band.
    sc3=scenario('prenight_program',[bright],sc2.slots)
    dpre=dict(p,program='DARK');dinside=dict(q,program='DARK')
    d0=run('program_inside',sc3,[{'action':'wait','until_utc':fmt(a)},dinside]);d1=run('program_pre',sc3,[{'action':'wait','until_utc':fmt(early)},dpre])
    # A complete-target terminal proof with a genuine feedback prior.
    t=utc('2026-11-03T08:29:30Z');s=t-timedelta(seconds=60);end=t+timedelta(seconds=30)
    done=target('DONE',70,30,t,flux=20.)
    first=vs.SlotTruth('N_LAST-S001',s,t,True,6.,1.,1.,1.);last=vs.SlotTruth('N_LAST-S002',t,end,True,.5,1.,1.,1.)
    sc4=scenario('terminal_complete',[done],[first,last]);prefix=[action([done],s,done['ra_deg'],done['dec_deg'],60,'BACKUP')]
    wait={'action':'wait','until_utc':fmt(end)}
    candidate=action([done],t,done['ra_deg'],done['dec_deg'],60,'DARK')
    def strict(snapshot,init,ledger,certs):
        cert=terminal_certificate(init,snapshot,wait,candidate,ledger);certs.append(cert)
        return candidate if cert['adopt'] else wait
    c0=run('terminal_complete_wait',sc4,prefix+[wait]);c1=run('terminal_complete_safe',sc4,prefix,strict)
    assert c1['total']>c0['total'] and c1['components']['uniformity_penalty']==c0['components']['uniformity_penalty']
    low=target('LOW_FLUX',69.5,30,t,flux=.1)
    scf=scenario('terminal_public_envelope',[done,low],[first,last]);fc=action([low],t,low['ra_deg'],low['dec_deg'],60,'DARK')
    def family_safe(snapshot,init,ledger,certs):
        ledger.set_family_envelope(3.,init)
        cert=terminal_certificate(init,snapshot,wait,fc,ledger);certs.append(cert)
        return fc if cert['adopt'] else wait
    f0=run('terminal_family_wait',scf,prefix+[wait]);f1=run('terminal_family_safe',scf,prefix,family_safe)
    assert f1['total']>f0['total'] and f1['components']['uniformity_penalty']==f0['components']['uniformity_penalty']
    # Jain counterexample: A1/B1 complete, high-flux new A2 completes.
    start=t-timedelta(seconds=1800);jts=[target(f'J{i}',70,30,t,flux=20. if i==1 else 2.) for i in range(4)]
    jts[1]['ra_deg']+=.1 if jts[0]['ra_deg']%10<9.8 else -.1
    jts[2]['ra_deg']=jts[3]['ra_deg']=(jts[0]['ra_deg']+20)%360
    sj=scenario('terminal_jain',jts,slots(start,end))
    jp=[action([jts[0]],start,jts[0]['ra_deg'],jts[0]['dec_deg'],900,'DARK'),action([jts[2]],start+timedelta(seconds=900),jts[2]['ra_deg'],jts[2]['dec_deg'],900,'DARK')]
    jc=action([jts[1]],t,jts[1]['ra_deg'],jts[1]['dec_deg'],60,'DARK')
    j0=run('jain_wait',sj,jp+[wait]);j1=run('jain_naive',sj,jp+[jc])
    def safe_j(snapshot,init,ledger,certs):
        cert=terminal_certificate(init,snapshot,wait,jc,ledger);certs.append(cert);return jc if cert['adopt'] else wait
    j2=run('jain_safe_reject',sj,jp,safe_j)
    assert j1['total']<j0['total'] and j2['total']==j0['total']
    # Added nonterminal empty exposure changes deletion from [1,2) to [2,3).
    ls=utc('2026-11-03T06:00:00Z');le=ls+timedelta(seconds=1200);trigger=le+timedelta(seconds=1200)
    high=target('LOSS',70,30,ls,flux=2.)
    stress=[dict(event_id='DL',event_type='data_loss',trigger_mode='fixed_date',trigger_ref=fmt(trigger),window_start_fraction='0.4',window_end_fraction='0.6',window_max_fraction='0.2')]
    sl=scenario('rank_loss',[high],slots(ls,le,'N_FIRST')+slots(trigger,trigger+timedelta(seconds=60),'N_SECOND'),stress=stress)
    empty=lambda d:dict(action='observe',pointing={'alt_deg':70.,'az_deg':30.},assignments={},duration_seconds=d,program='BACKUP')
    lp=[empty(60),empty(60),action([high],ls+timedelta(seconds=120),high['ra_deg'],high['dec_deg'],900,'DARK'),empty(60),{'action':'wait','until_utc':fmt(le-timedelta(seconds=30))}]
    l0=run('loss_wait',sl,lp+[{'action':'wait','until_utc':fmt(trigger)}]);l1=run('loss_insert',sl,lp+[empty(60),{'action':'wait','until_utc':fmt(trigger)}])
    assert l1['total']<l0['total']
    return {'orientation_delta':delta(r0,r1),'request_delta':delta(n0,n1),'program_dilution_delta':delta(d0,d1),'terminal_safe_delta':delta(c0,c1),
            'terminal_family_safe_delta':delta(f0,f1),'jain_naive_delta':delta(j0,j1),'jain_safe_delta':delta(j0,j2),'loss_extra_rank_delta':delta(l0,l1),
            'prenight_gate':prenight_certificate({'now_utc':fmt(early)},pre,True)}


def generator_worlds():
    cfg=json.loads((OUT/'official/challenge/reference/v4/v4_weather_config.json').read_text())
    # Independent seeds declared before evaluation. No real card worlds loaded.
    seeds=list(range(910701,910709));rows=[]
    for seed in seeds:
        config=copy.deepcopy(cfg);config['seed']=seed
        a=utc('2026-11-03T00:30:00Z');end=a+timedelta(seconds=900);early=a-timedelta(seconds=2700)
        nights=[Night('N_PREV',(a-timedelta(days=1)).date(),a-timedelta(days=1),a-timedelta(seconds=85500),a-timedelta(days=1),a-timedelta(seconds=85500),1),Night('N_NEXT',a.date(),a,end,a,end,1)]
        calendar=[Slot(n.night_id+'-S001',n.night_id,n.observing_start_utc,900) for n in nights]
        truth=wg.generate_weather(config,nights,calendar,[],[])
        ss=[vs.SlotTruth(row['slot_id'],utc(row['timestamp_utc']),utc(row['timestamp_utc'])+timedelta(seconds=row['duration_seconds']),row['is_observable']=='true',
                float(row['seeing_arcsec'] or 0),float(row['transparency'] or 0),float(row['sky_quality'] or 0),float(row['instrument_efficiency'] or 0)) for row in truth]
        ts=[ray_target('PAIR_LOW',-1.4,a),ray_target('PAIR_HIGH',1.4,a)];ra,dec=altaz_to_radec(70,0,a,lat,lon);sc=scenario('generator_pair',ts,ss)
        p=action(ts,early,ra,dec,3600);q=action(ts,a,ra,dec,900)
        r0=run(f'gen_{seed}_inside',sc,[{'action':'wait','until_utc':fmt(a)},q]);r1=run(f'gen_{seed}_pre',sc,[{'action':'wait','until_utc':fmt(early)},p])
        rows.append({'seed':seed,'delta':delta(r0,r1),'generated_background_only':True,'events':[], 'weather_truth':truth,
                     'prenight_assignments':p['assignments'],'inside_same_center_assignments':q['assignments']})
    return {'seeds':seeds,'rows':rows,'full_season':False,'actual_cards_used':False,'candidate_not_adopted':True}


def certificate_boundaries():
    a=utc('2026-11-03T00:30:00Z');ts=[target('BOUND',70,0,a)]
    sc=scenario('proof_rounding',ts,slots(a,a+timedelta(seconds=90)));init=initial(sc);ledger=PublicScoreLedger(init)
    ledger.ingest({'last_result':{'action':'observe','observe_index':0,'hits':[{'target_id':'BOUND','score':.600000}]},'new_messages':[]})
    at_threshold='BOUND' in ledger.completed()
    ledger.ingest({'last_result':{'action':'observe','observe_index':1,'hits':[{'target_id':'BOUND','score':.600001}]},'new_messages':[]})
    above_threshold='BOUND' in ledger.completed()
    ledger.ingest({'last_result':{'action':'observe','observe_index':1,'hits':[{'target_id':'BOUND','score':.600001}]},'new_messages':[{'record_type':'state_resync','best_scores':[]}]})
    after_resync='BOUND' in ledger.completed()
    assert not at_threshold and above_threshold and not after_resync
    return {'rounding_boundary_rejected':not at_threshold,'above_boundary_accepted':above_threshold,'resync_canonical_removes_proof':not after_resync}


def integrated_tail():
    import binding_agent as entry
    t=utc('2026-11-03T08:29:30Z');a=t-timedelta(seconds=60);end=t+timedelta(seconds=30)
    # The two faint targets share one coordinate/cell, so at least one remains
    # unassigned in the original first exposure. This exercises an actual new
    # tail action under unchanged strong first-action planning and own feedback.
    targets=[target('LIVE_DONE',70,30,t,flux=20.),target('LIVE_LOW',69.5,30,t,flux=.1),target('LIVE_LOW_OTHER',69.5,30,t,flux=.1)]
    ss=[vs.SlotTruth('N_LIVE-S001',a,t,True,6.,1.,1.,1.),vs.SlotTruth('N_LIVE-S002',t,end,True,.5,1.,1.,1.)]
    sc=scenario('integrated_terminal',targets,ss);results=[]
    for name,cls in [('integrated_control',entry.frozen.ExactCachedRequestPolicy),('integrated_safe',entry.BoundaryPolicy)]:
        owner=None;trace=[];started=time.perf_counter()
        def factory(context):
            nonlocal owner
            owner=cls(initial(sc))
            def actor(snapshot):
                elapsed=time.perf_counter()-started
                snapshot={**snapshot,'wallclock':{'remaining_seconds':900.-elapsed,'elapsed_seconds':elapsed}}
                act=owner.decide(snapshot)
                env=dict(act,protocol_version='participant-agent-protocol-v4',message_type='decision_response',decision_sequence=len(trace)+1)
                act=V4Workflow.action_from_response(env,len(trace)+1);trace.append({'snapshot':snapshot,'action':act})
                return act
            return actor
        stub=OUT/f'{name}_scenario_stub.json';stub.write_text(json.dumps({'integrated_synthetic':name})+'\n')
        with patch.object(vr,'load_scenario',return_value=sc):report=vr.run_scenario(stub,factory,OUT/'runs'/name)
        (OUT/'runs'/name/'public_trace.json').write_text(json.dumps(trace,indent=2)+'\n')
        (OUT/'runs'/name/'owner_summary.json').write_text(json.dumps(owner.summary(),indent=2)+'\n')
        results.append({'report':report,'summary':owner.summary(),'trace':trace})
    change=delta(results[0]['report'],results[1]['report'])
    assert change['total']>=0 and change['components']['uniformity_penalty']==0
    assert results[1]['summary']['calendar_boundary']['adopted']==1
    return {'control':results[0],'safe':results[1],'delta':change,'normal_own_feedback_replanning':True,'original_all_parameters_preserved':True}


if __name__=='__main__':
    begin=time.perf_counter();result={'adversarial':adversarial(),'generator':generator_worlds(),'certificate':certificate_boundaries(),'integrated_tail':integrated_tail()}
    result['seconds']=time.perf_counter()-begin
    (OUT/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'adversarial':result['adversarial'],'certificate':result['certificate'],'integrated_tail_delta':result['integrated_tail']['delta'],'generator_deltas':[r['delta']['total'] for r in result['generator']['rows']],'seconds':result['seconds']},indent=2))
