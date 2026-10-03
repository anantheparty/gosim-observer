#!/usr/bin/env python3
"""Bounded incomplete three-field DP with continuous integer time exchange."""
from __future__ import annotations
import importlib.util,copy,json,sys,time,math
from pathlib import Path
from datetime import timedelta
sys.dont_write_bytecode=True
path=Path(__file__).with_name('compound_time_graph_probe.py');spec=importlib.util.spec_from_file_location('compound_probe',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);np=m.np
OUT=m.OUT

def apply(dom,c,s,f,offset):
    raw,low,C=dom.quality(offset,c[1]);ix=c[3];positions={int(i):j for j,i in enumerate(dom.idx)};ss=s.copy();ff=f.copy()
    for i in ix:
        j=positions[int(i)];ss[j]=max(ss[j],C[c[2],j]);ff[j]=max(ff[j],low[j])
    return ss,ff

def search(dom,seed):
    H=dom.H;p=dom.p;calls=0;frontier_kept=6;best=(-math.inf,None,None);cache={}
    def evaluate(ds):
        nonlocal best,calls
        key=tuple(ds)
        if key in cache:return cache[key]
        d1,d2,d3=ds;first=dom.options(0,d1,dom.s,dom.f);second=dom.best_seconds(d1,d2,first);middle=[]
        for a,(v,c2) in zip(first,second):
            if c2 is None:continue
            ss,ff=apply(dom,c2,a[1],a[2],d1);middle.append((v,ss,ff,c2,[a[3],c2]))
        middle.sort(key=lambda a:-a[0]);middle=middle[:frontier_kept]
        third=dom.best_seconds(d1+d2,d3,middle);winner=max(zip(middle,third),key=lambda x:x[1][0]);value=winner[1][0];actions=winner[0][4]+[winner[1][1]]
        calls+=1;result=(value,actions,ds);cache[key]=result
        if value>best[0]:best=result
        return result
    started=time.perf_counter();evaluate(seed);passes=[]
    # One exact integer exchange along each of the three capacity-preserving
    # coordinate lines. The beam is an incomplete DP, no global-optimality claim.
    for fixed in (2,0,1):
        frozen=best[2];remaining=H-frozen[fixed];var=[i for i in range(3) if i!=fixed]
        for d in range(60,remaining-59):
            ds=list(frozen);ds[var[0]]=d;ds[var[1]]=remaining-d;evaluate(ds)
        passes.append(dict(fixed_index=fixed,iterations=remaining-119,best_value=best[0],best_durations=best[2]));print(json.dumps(dict(phase='triple_exchange',fixed=fixed,calls=calls,best_durations=best[2])),flush=True)
    return dict(model_terminal=best[0],model_gain=best[0]-m.terminal(p,dom.s,dom.f,dom.idx,dom.b),durations=best[2],actions=[m.serialize(p,c,dom.env) for c in best[1]],calls=calls,beam=frontier_kept,passes=passes,seconds=time.perf_counter()-started,assignment_options=dom.calls)

def micro(card):
    start=time.perf_counter();trace=m.TRACE[card];tape=[json.loads(l) for l in (trace/'actions.jsonl').read_text().splitlines()];r=json.loads((OUT/f'{card}_result.json').read_text());initial=m.V4Workflow(m.UP/'local-cards'/card).initialize_payload(900);policy=m.policy.Policy(initial);captured={};seq=0
    def choose(snap,s,f,env,req):
        nonlocal captured
        p=policy.planner;a=tape[seq]
        if seq==r['prefix_actions']:
            natural,q,centers=m.capture(p,snap,s,f,env);captured=dict(snap=copy.deepcopy(snap),s=s.copy(),f=f.copy(),env=copy.deepcopy(env),p=q,centers=centers,natural=natural)
        alt,az,_,_=p._altaz(m.local_sidereal(m.parse_utc(snap['now_utc']),p.lon));p.last_prediction={tid:dict(alt_deg=float(alt[p.index[tid]]),az_deg=float(az[p.index[tid]])) for tid in a['assignments'].values()};p.stats={};return a
    policy.planner.choose=choose
    def decide(snap):
        nonlocal seq
        a=policy.decide(snap)
        if captured:return None
        assert a==tape[seq];seq+=1;return a
    m.run_scenario(m.UP/'local-cards'/card/'config/v4_scenario.json',lambda _:decide,OUT/f'triple_prefix_{card}')
    p=captured['p'];env=captured['env'];snap=captured['snap'];s=captured['s'].copy();f=captured['f'].copy();now=m.parse_utc(snap['now_utc']);H=r['horizon_seconds'];centers=captured['centers'];public_rollout=[];offset=0
    # Generate future fields using only current frozen belief and modeled best.
    # The held-out future source tape never enters this proposal stage.
    for stage in range(2):
        ss=dict(snap,now_utc=(now+timedelta(seconds=offset)).strftime('%Y-%m-%dT%H:%M:%SZ'),observe_action_index=snap['observe_action_index']+stage,new_messages=[])
        a,q,cs=m.capture(p,ss,s,f,env);d=min(a['duration_seconds'],H-offset-(2-stage)*60);a['duration_seconds']=max(60,int(d));public_rollout.append(a)
        for c in cs[:4]:
            eq=m.altaz_to_radec(*c,now+timedelta(seconds=offset),p.lat,p.lon);c0=m.radec_to_altaz(*eq,now,p.lat,p.lon)
            if all(np.linalg.norm(np.array(c0)-np.array(old))>.15 for old in centers):centers.append(c0)
        # Full public-prediction integration for the selected new stage.
        dom=m.PairDomain(p,snap,s,f,env,centers,H);ix=np.array([p.index[t] for t in a['assignments'].values()]);c=(m.center_actual(a,env),a['duration_seconds'],m.PROGRAMS.index(a['program']),ix,np.array(list(map(int,a['assignments']))));ss0,ff0=apply(dom,c,dom.s,dom.f,offset);s[dom.idx]=ss0;f[dom.idx]=ff0;offset+=a['duration_seconds']
    seed=[a['duration_seconds'] for a in public_rollout]+[H-offset]
    dom=m.PairDomain(p,snap,captured['s'],captured['f'],env,centers,H)
    # captured s/f own immutable prefix arrays: public rollout used local copies.
    summary=search(dom,seed);result=dict(card=card,now_utc=r['now_utc'],horizon_seconds=H,prefix_sha256=r['prefix_sha256'],native_prefix_match=captured['natural']==r['source_action'],field_centers=len(centers),relevant_targets=len(dom.idx),public_rollout_seed=public_rollout,search=summary,scope='three actions; continuous integer exchange, beam6 incomplete ledger DP, frozen public current-slot belief; no future truth candidates')
    m.write(OUT/f'{card}_triple_search_frozen.json',result)
    scenario=m.load_scenario(m.UP/'local-cards'/card/'config/v4_scenario.json');grid=m.FiberGrid.from_config(scenario.fiber_config);td={t['target_id']:t for t in scenario.targets};time0=now
    for a in summary['actions']:
        m.normalize_action(a,scenario,td,time0)
        for fi,tid in a['assignments'].items():
            t=td[tid];c=grid.classify_target(t['ra_deg'],t['dec_deg'],time0,a['pointing']['alt_deg'],a['pointing']['az_deg'],p.lat,p.lon,env.get('pointing_offset_alt_deg',0),env.get('pointing_offset_az_deg',0));assert c.region=='glass' and c.fiber_id==int(fi);assert m.min_altitude_during(t['ra_deg'],t['dec_deg'],time0,time0+timedelta(seconds=a['duration_seconds']),scenario.config)>=scenario.minimum_altitude_deg
        time0+=timedelta(seconds=a['duration_seconds'])
    plan=tape[:r['prefix_actions']]+summary['actions'];seq=0
    def callback(snap):
        nonlocal seq
        if seq>=len(plan):return None
        a=plan[seq];seq+=1;return a
    report=m.run_scenario(m.UP/'local-cards'/card/'config/v4_scenario.json',lambda _:callback,OUT/f'{card}_triple_best');result.update(official_micro_terminal=report['total'],official_components=report['components'],official_counts=report['counts'],official_minus_source_multifield=report['total']-r['source_multifield_control']['official_micro_terminal'],seconds=time.perf_counter()-start);m.write(OUT/f'{card}_triple_result.json',result);print(json.dumps({k:result[k] for k in ['card','official_minus_source_multifield','seconds']}),flush=True)
if __name__=='__main__':
    for c in sys.argv[1:] or ['L2']:micro(c)
