#!/usr/bin/env python3
"""Read-only public-feedback opportunity audit and generator-family loss model.

No scenario truth, future weather, private fractions or future request rows are
read. Observations CSV is used through an explicit score-only projection; its
factor/quality/prog_mult columns are prohibited in the public audit.
"""
from __future__ import annotations
import csv, hashlib, json, math, random, sys, time
from collections import defaultdict
from pathlib import Path
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/survival_hedging_20261004'
M = 10**6


def all_loss(indices, n, x, rounded=True):
    """Exact area under ideal continuous RNG, including six-decimal CSV rounding.

    This is conditional on the generator family, a fixed frozen N and known x.
    It is not claimed to be an identified probability on hidden task cards.
    """
    if not indices:
        return 1.
    a, b = min(indices), max(indices)
    assert 0 <= a <= b < n and 0 < x <= 1
    if rounded:
        # round(y,6)<(a+1)/n changes at (ceil((a+1)*M/n)-.5)/M.
        u = (((a+1)*M+n-1)//n - .5)/M
        v = (((b+1)*M+n-1)//n - .5)/M
    else:
        u, v = (a+1)/n, (b+1)/n
    lo, hi = max(0., v-x), min(1., u)
    if hi <= lo:
        return 0.
    cut = min(hi, max(lo, 1-x))
    area = .5*(cut-lo)*(cut+lo+2*(x-v)) + (hi-cut)*(1-v)
    return max(0., min(1., area/(x-.5*x*x)))


def expected_best(rows, n, x, rounded=True):
    """rows contain only (observe index, public contribution)."""
    if not rows:
        return 0.
    groups = defaultdict(list)
    for a, c in rows:
        if c > 0:
            groups[c].append(a)
    levels = sorted(groups, reverse=True)
    included, value = [], 0.
    for k, c in enumerate(levels):
        included.extend(groups[c])
        nxt = levels[k+1] if k+1 < len(levels) else 0.
        value += (c-nxt)*(1-all_loss(included,n,x,rounded))
    return value


def clip(poly, coef):
    aa,bb,cc=coef;out=[]
    for p,q in zip(poly,poly[1:]+poly[:1]):
        fp=aa*p[0]+bb*p[1]+cc;fq=aa*q[0]+bb*q[1]+cc
        if fp>=0:out.append(p)
        if (fp>=0)!=(fq>=0):
            z=fp/(fp-fq);out.append((p[0]+z*(q[0]-p[0]),p[1]+z*(q[1]-p[1])))
    return out


def joint_window_weights(n,x):
    """Exact shared window cells after six-decimal rounding, including j=1."""
    def threshold(k):return 0. if k==0 else 1. if k==n+1 else (((k*M+n-1)//n)-.5)/M
    rows=[]
    for first in range(n+1):
        for last in range(first,n+1):
            il,iu=threshold(first),threshold(first+1)
            jl,ju=threshold(last),threshold(last+1)
            poly=[(il,jl),(iu,jl),(iu,ju),(il,ju)]
            poly=clip(poly,(-1.,1.,0.));poly=clip(poly,(1.,-1.,x))
            if len(poly)<3:continue
            area=abs(sum(p[0]*q[1]-q[0]*p[1] for p,q in zip(poly,poly[1:]+poly[:1])))/2
            if area>0:rows.append((first,last,area/(x-.5*x*x)))
    assert abs(sum(p for f,l,p in rows)-1)<1e-10
    return rows


def official_joint_checks():
    # Synthetic ledger only. Unmodified official scorer supplies full settlement.
    sys.path.insert(0,str(ROOT/'upstream/gosim-observer-examples/runner'))
    from challenge.v4_scorer import BestLedger,required_penalty,uniformity_penalty,settle_observation_requests
    from datetime import datetime,timedelta,timezone
    cfg=json.loads((ROOT/'upstream/gosim-observer-examples/local-cards/L1/config/v4_score_config.json').read_text())
    targets=[dict(target_id='A',required=True,ra_deg=5.),dict(target_id='B',required=False,ra_deg=15.),dict(target_id='C',required=False,ra_deg=5.)]
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    req=dict(request_id='synthetic',issued_at_utc=start,deadline_utc=start+timedelta(days=1),target_ids=['A','B'],minimum_completed=2,completion_factor_threshold=.5,completion_reward=100.)
    raw=[(4,'A',.6,1.),(4,'B',.6,.6),(5,'A',.55,.8),(7,'C',.55,.55)]
    n,x=10,.2;weights=joint_window_weights(n,x)
    expected_science=expected_total=expected_jain=expected_req=0.
    for f,l,p in weights:
        ledger=BestLedger()
        for a,t,g,c in raw:ledger.record(a,t,g,c,start,start+timedelta(seconds=60))
        ledger.invalidate_window(f,l,'synthetic')
        science=sum(c for g,c in ledger.best().values());factors=ledger.max_factors()
        _,rp=required_penalty(targets,factors,cfg);_,jp=uniformity_penalty(targets,factors,cfg);_,rq=settle_observation_requests([req],ledger)
        expected_science+=p*science;expected_total+=p*(science-rp-jp+rq);expected_jain+=p*jp;expected_req+=p*rq
    groups=defaultdict(list)
    for a,t,g,c in raw:groups[t].append((a,c))
    analytic=sum(expected_best(rows,n,x) for rows in groups.values())
    assert abs(analytic-expected_science)<1e-10
    # A and B original witnesses share rank; their losses are correlated. A's
    # backup does not make B's missing witness independent.
    pa=1-all_loss([4,5],n,x);pb=1-all_loss([4],n,x)
    assert abs(100*pa*pb-expected_req)>1.
    return dict(scope='Synthetic common-window full official ledger settlement; no decision policy or season gain.',
                window_cells=len(weights),probability_mass=sum(p for f,l,p in weights),
                analytic_science=analytic,official_shared_science=expected_science,
                official_shared_total=expected_total,official_shared_req=expected_req,
                incorrect_independent_req=100*pa*pb,official_shared_jain_penalty=expected_jain)


def mechanism_checks():
    started = time.perf_counter()
    rng = random.Random(20261004)
    checks = []
    # Common-path Monte Carlo is independent of the analytic area routine.
    for n,x,idx in [(10,.05,[9]),(10,.2,[4]),(10,.2,[3,6]),(7,.75,[1,4]),(11,1.,[1,8])]:
        hit = accepted = 0
        while accepted < 100000:
            i,j = sorted([rng.random(),rng.random()])
            if j-i > x:
                continue
            accepted += 1
            i,j = float(f'{i:.6f}'),float(f'{j:.6f}')
            f,l = math.floor(i*n),math.floor(j*n)
            hit += all(f <= a < l for a in idx)
        exact = all_loss(idx,n,x)
        error = abs(hit/accepted-exact)
        assert error < .007
        checks.append(dict(n=n,x=x,indices=idx,exact=exact,mc=hit/accepted,error=error))
    # Lower c has fixed-N value when the only larger witness is lost.
    base=[(4,1.)]; hedge=base+[(8,.8)]
    hedge_delta=expected_best(hedge,10,.2)-expected_best(base,10,.2)
    assert hedge_delta > 0
    # Appending a zero-value observe changes N and endangers the old last witness.
    before=expected_best([(1,1.)],2,.2)
    after=expected_best([(1,1.)],3,.2)
    assert after < before
    # Moving a first witness toward the endpoint can improve its survival.
    positive=expected_best([(0,1.)],3,.75)-expected_best([(0,1.)],2,.75)
    assert positive > 0
    last=all_loss([9],10,.05)
    assert last > 0 and all_loss([9],10,.05,False) == 0
    return dict(checks=checks,lower_score_fixed_n_delta=hedge_delta,
                append_empty_observe_global_delta=after-before,
                append_empty_observe_other_history_delta=positive,
                rounded_last_action_loss_probability=last,
                monte_carlo_seconds=time.perf_counter()-started)


TRACE={'L1':ROOT/'results/geometry_native_20261003/protocol_gate_remaining/L1',
       'L2':ROOT/'results/geometry_native_20261003/protocol_gate_retry/L2',
       'L3':ROOT/'results/geometry_native_20261003/protocol_gate_remaining/L3',
       'L4':ROOT/'results/geometry_native_20261003/protocol_gate_retry/L4'}


def public_history(card):
    path=TRACE[card]
    targets={r['target_id']:r for r in csv.DictReader((ROOT/f'upstream/gosim-observer-examples/local-cards/{card}/public/targets.csv').open())}
    cfg=json.loads((ROOT/f'upstream/gosim-observer-examples/local-cards/{card}/config/v4_score_config.json').read_text())
    decisions={int(r['observe_index']):r for r in csv.DictReader((path/'decisions.csv').open()) if r['action']=='observe'}
    all_decisions=list(csv.DictReader((path/'decisions.csv').open()))
    last_decision_id=max(int(d['decision_id']) for d in all_decisions)
    messages=[json.loads(r) for r in (path/'messages.jsonl').read_text().splitlines()]
    requests=[r for r in messages if r['record_type']=='observation_request']
    resyncs=[r for r in messages if r['record_type']=='state_resync']
    # Projection uses only public feedback content; no raw-factor access.
    observations=[dict(a=int(r['observe_index']),tid=r['target_id'],c=float(r['score']))
                  for r in csv.DictReader((path/'observations.csv').open())]
    oldbest=defaultdict(float); lower=defaultdict(float); per=defaultdict(list)
    lower_count=lower_factor_certificate=lower_req_new=0
    examples=[]
    for r in observations:
        a,tid,c=r['a'],r['tid'],r['c'];d=decisions[a];t=targets[tid]
        # A final observe has no following decision_request/last_result delivery.
        if int(d['decision_id'])==last_decision_id:
            continue
        # Hard risk audit restricts to pre-trigger feedback. Prefix is defined
        # retrospectively for mechanism audit; it is not a deployable trigger prior.
        if resyncs and d['end_utc'] >= resyncs[0]['issued_at_utc']:
            continue
        weight=float(t['science_weight']);prog=d['program']
        lb=max(0.,c-.5e-6)/(weight*cfg['program']['multipliers'][prog])
        if c < oldbest[tid]-1e-6:
            lower_count+=1
            cross=lower[tid]<cfg['required']['observed_factor_threshold']<=lb
            lower_factor_certificate+=cross
            # Previously observed globally, but this particular REQ window may
            # contain no previous public lower-bound witness for this target.
            rq=[]
            for q in requests:
                if q['issued_at_utc']<=d['start_utc'] and d['end_utc']<=q['deadline_utc'] and tid in q['target_ids']:
                    prior=[(aa,cc) for aa,cc in per[tid] if q['issued_at_utc']<=decisions[aa]['start_utc'] and decisions[aa]['end_utc']<=q['deadline_utc']]
                    prior_lb=max([max(0.,cc-.5e-6)/(weight*cfg['program']['multipliers'][decisions[aa]['program']]) for aa,cc in prior],default=0.)
                    if prior_lb<q['completion_factor_threshold']<=lb:
                        rq.append(q['request_id'])
            lower_req_new+=bool(rq)
            if (cross or rq) and len(examples)<12:
                examples.append(dict(a=a,target=tid,score=c,old_best=oldbest[tid],new_lower=lb,old_lower=lower[tid],required=t['required'],new_request_witness=rq))
        oldbest[tid]=max(oldbest[tid],c);lower[tid]=max(lower[tid],lb);per[tid].append((a,c))
    n=max([a for rows in per.values() for a,c in rows],default=-1)+1
    conditional={}
    if card in ['L3','L4']:
        # A hypothetical public prior from the reference generator, never card truth:
        # keep N=2*prefix actions and x=.05 for all Hard histories.
        frozen_n=max(1,2*n);x=.05
        gains=[]
        begin=time.perf_counter()
        for tid,rows in per.items():
            v=expected_best(rows,frozen_n,x)
            # Aggregate incremental value of each lower-than-previous-max witness;
            # this is descriptive, not additive over simultaneously removed rows.
            maxc=0.
            for k,(a,c) in enumerate(rows):
                if c < maxc-1e-6:
                    delta=v-expected_best(rows[:k]+rows[k+1:],frozen_n,x)
                    if delta>1e-12:
                        gains.append((delta,tid,a,c))
                maxc=max(maxc,c)
        conditional=dict(scope='Synthetic conditional survival model applied to public score history, no future truth; x=.05 and N=2*prefix_n are uncalibrated hypotheses.',
                         n=frozen_n,x=x,positive_lower_witnesses=len(gains),
                         top=sorted(gains,reverse=True)[:12],cpu_seconds=time.perf_counter()-begin)
    return dict(card=card,public_prefix_observe_count=n,score_feedback_hits=sum(map(len,per.values())),
                lower_science_hits=lower_count,lower_science_new_factor_certificate=lower_factor_certificate,
                lower_science_new_req_window_witness=lower_req_new,examples=examples,
                public_resyncs=[dict(issued_at_utc=r['issued_at_utc'],invalidated_window=r['invalidated_window']) for r in resyncs],
                survival_enabled_in_local_card=card in ['L3','L4'],conditional_model=conditional)


def offline_factor_teacher(card):
    """Offline only: actual observed raw factors are not public agent features."""
    path=TRACE[card];best=defaultdict(float);factor=defaultdict(float)
    lower_raw_improved=lower_threshold_crossed=0;examples=[]
    decisions={int(r['observe_index']):r for r in csv.DictReader((path/'decisions.csv').open()) if r['action']=='observe'}
    messages=[json.loads(r) for r in (path/'messages.jsonl').read_text().splitlines()]
    resync=next((r for r in messages if r['record_type']=='state_resync'),None)
    for r in csv.DictReader((path/'observations.csv').open()):
        a=int(r['observe_index']);tid=r['target_id'];c=float(r['score']);g=float(r['factor'])
        if resync and decisions[a]['end_utc']>=resync['issued_at_utc']:continue
        if c<best[tid]-1e-6 and g>factor[tid]+1e-6:
            lower_raw_improved+=1;lower_threshold_crossed+=factor[tid]<.5<=g
            if len(examples)<8:examples.append(dict(a=a,target=tid,c=c,old_best=best[tid],g=g,old_g=factor[tid]))
        best[tid]=max(best[tid],c);factor[tid]=max(factor[tid],g)
    return dict(card=card,scope='Offline actual hit factor teacher audit, unavailable to participant; never used by public_history or action selection.',
                lower_science_raw_factor_improved=lower_raw_improved,
                lower_science_raw_factor_crossed_half=lower_threshold_crossed,examples=examples)


def main():
    started=time.perf_counter();OUT.mkdir(parents=True,exist_ok=True)
    result=dict(mechanism=mechanism_checks(),joint=official_joint_checks(),cards=[public_history(c) for c in TRACE],
                offline_factor_teacher=[offline_factor_teacher(c) for c in TRACE])
    result['elapsed_seconds']=time.perf_counter()-started
    result['source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (OUT/'public_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(seconds=result['elapsed_seconds'],mechanism=result['mechanism'],
                         cards=[{k:v for k,v in c.items() if k not in ['examples','public_resyncs','conditional_model']}|{'conditional':c['conditional_model']} for c in result['cards']]),indent=2))


if __name__=='__main__':main()
