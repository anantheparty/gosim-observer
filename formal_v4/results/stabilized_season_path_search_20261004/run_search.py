"""Frozen 480-second, one-graph offline search. Never imports the online actor."""
from __future__ import annotations
import os
for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[name] = '1'
import argparse
import csv
import hashlib
import json
import platform
import resource
import sys
import time
from datetime import datetime
from pathlib import Path
import numpy as np
import scipy
from fixed_graph import FixedGraph
from bundle_search import Bundle, rebuild

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OLD = HERE.parent / 'season_pattern_controller_20261004'
INPUTS = dict(graph=OLD/'time_dp/L2_night08/SHARED_PUBLIC_GRAPH.npz',
    ledger=OLD/'time_dp_reuse/L2_night08/CURRENT_PUBLIC_LEDGER.npz',
    snapshot=OLD/'time_dp_reuse/L2_night08/CURRENT_PUBLIC_SNAPSHOT.json',
    pool=OLD/'time_dp_reuse/L2_night08/COMMON_PATH_POOL.json',
    prior_result=OLD/'time_dp_reuse/L2_night08/RESULT.json',
    catalogue=REPO/'formal_v4/upstream/gosim-observer-examples/local-cards/L2/public/targets.csv',
    scoring=REPO/'formal_v4/upstream/gosim-observer-examples/local-cards/L2/config/v4_score_config.json',
    fiber_config=REPO/'formal_v4/upstream/gosim-observer-examples/local-cards/L2/config/v4_fiber_config.json',
    nights=REPO/'formal_v4/upstream/gosim-observer-examples/local-cards/L2/public/v4_night_calendar.csv',
    **{f'first_{n}':OLD/f'time_dp_reuse/L2_night08/COMMON_CONTROL_{n}.json' for n in ('B','priced0','priced1')})
TOTAL_SECONDS = 480.
PRICE_SECONDS = 240.
REPAIR_SECONDS = 150.
MAX_PRICE_ROUNDS_PER_BRANCH = 200
MAX_REPAIR_SWEEPS = 4

def stamp(s): return datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
def dump(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False)+'\n')
def hashfile(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
    return h.hexdigest()
def plain_control(c):
    return dict(increment=c['increment'], path=list(c['path']), schedule=c['schedule'], ledger=c['ledger'].tolist())
def rss():
    r=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(r if platform.system()=='Darwin' else r*1024)

class Pool:
    def __init__(self, graph, branches, start, deadline):
        self.g=graph; self.branches=branches; self.start=start; self.deadline=deadline
        self.paths=set(); self.origins=[]; self.trace=[]; self.matches=0
    def add(self, path, origin):
        path=tuple(path)
        if path in self.paths:return False
        if time.perf_counter()>self.deadline:raise TimeoutError('common-pool budget')
        controls=[]
        # Commit a pool path only after EVERY prefix branch gets its matching.
        for branch in self.branches:
            admissible=tuple(e for e in path if self.g.starts[e]>=branch['blocked']-1e-7)
            controls.append(self.g.match(branch['first'], admissible));self.matches+=1
        self.paths.add(path);self.origins.append(dict(origin=origin,path=list(path)))
        for branch,c in zip(self.branches,controls):
            value=branch['current_gain']+c['increment'];before=branch.get('joint',float('-inf'))
            if value>before+1e-9:
                branch.update(control=c,joint=value,origin=origin)
                self.trace.append(dict(seconds=time.perf_counter()-self.start,branch=branch['name'],
                    joint=value,delta=0. if not np.isfinite(before) else value-before,origin=origin,pool=len(self.paths)))
        return True

def run(output, seconds=TOTAL_SECONDS):
    if seconds!=TOTAL_SECONDS:raise ValueError('frozen budget is exactly 480 seconds')
    output=Path(output).resolve()
    if HERE not in output.parents or output.exists():raise ValueError('use a new run directory inside this experiment')
    output.mkdir(); wall0=time.perf_counter();cpu0=time.process_time();deadline=wall0+seconds
    result=dict(status='started',science_proxy_only=True,stochastic_or_formal_score_claim=False,
        futuretruth_used=False,old_sources_modified=False,budget_seconds=seconds,
        environment=dict(python=sys.version,numpy=np.__version__,scipy=scipy.__version__,platform=platform.platform(),threads=1),
        frozen_plan=dict(price_seconds=PRICE_SECONDS,repair_seconds=REPAIR_SECONDS,
            max_price_rounds_per_branch=MAX_PRICE_ROUNDS_PER_BRANCH,max_repair_sweeps=MAX_REPAIR_SWEEPS))
    pool=None;bundles=[];repair_trace=[]
    try:
        receipt=json.loads((HERE/'INPUT_RECEIPT.json').read_text())
        for name,p in INPUTS.items():
            if hashfile(p)!=receipt['inputs'][name]['sha256']:raise ValueError('frozen input mismatch '+name)
        result['input_receipt_sha256']=hashfile(HERE/'INPUT_RECEIPT.json')
        g=FixedGraph(INPUTS['graph'],INPUTS['catalogue'],INPUTS['scoring'],INPUTS['fiber_config'])
        with np.load(INPUTS['ledger'],allow_pickle=False) as z:b=np.ascontiguousarray(z['best_scores'])
        snapshot=json.loads(INPUTS['snapshot'].read_text());now=stamp(snapshot['now_utc'])
        branches=[]
        for name in ('B','priced0','priced1'):
            d=json.loads(INPUTS['first_'+name].read_text());first=np.ascontiguousarray(d['first_ledger'])
            if np.any(first<b-1e-10):raise ValueError('prefix lowered historical ledger')
            changed=np.flatnonzero(first>b+1e-10)
            assigned={g.ids.index(t) for t in d['first_action']['assignments'].values()}
            if any(int(i) not in assigned for i in changed):raise ValueError('prefix modified unassigned target')
            branches.append(dict(name=name,first=first,first_action=d['first_action'],
                current_gain=float((first-b).sum()),blocked=now+d['first_action']['duration_seconds']))
        pool=Pool(g,branches,wall0,deadline-20.)
        old_paths=json.loads(INPUTS['pool'].read_text())
        for path in old_paths:pool.add(path,'old57')
        baseline={branch['name']:branch['joint'] for branch in branches}
        result['matched_old57']=baseline
        result['old_chronological_joint']={v['name']:v['joint_feasible_lower'] for v in json.loads(INPUTS['prior_result'].read_text())['branches']}
        for branch in branches:
            dump(output/f'BASELINE_MATCHED_{branch["name"]}.json',dict(first_action=branch['first_action'],
                current_gain=branch['current_gain'],joint=branch['joint'],future=plain_control(branch['control'])))
        result['baseline_seconds']=time.perf_counter()-wall0
        bundles=[Bundle(g,branch) for branch in branches]
        price_end=min(deadline-60.,time.perf_counter()+PRICE_SECONDS)
        while time.perf_counter()<price_end and any(v.rounds<MAX_PRICE_ROUNDS_PER_BRANCH for v in bundles):
            for bundle in bundles:
                if time.perf_counter()>=price_end:break
                if bundle.rounds>=MAX_PRICE_ROUNDS_PER_BRANCH:continue
                path,row=bundle.step();added=pool.add(path,'prox_'+bundle.branch['name'])
                row.update(new_common_path=added,common_pool=len(pool.paths),joint=bundle.branch['joint'])
                if bundle.rounds%20==0:print(json.dumps(dict(event='prox',seconds=time.perf_counter()-wall0,**row)),flush=True)
        prox_joint={branch['name']:branch['joint'] for branch in branches}
        result['post_prox_joint']=prox_joint
        with INPUTS['nights'].open() as h:nights=list(csv.DictReader(h))
        starts=[stamp(n['observing_start_utc']) for n in nights];ends=[stamp(n['observing_end_utc']) for n in nights]
        # Same fixed, interleaved one/two/four-night neighborhood list for all
        # branches; all days get one-night coverage before the wider passes.
        windows=[]
        for width in (1,2,4):
            for k in range(len(nights)-width+1):
                if ends[k+width-1]>now:windows.append((starts[k],ends[k+width-1],width,k))
        repair_end=min(deadline-30.,time.perf_counter()+REPAIR_SECONDS)
        attempts=0;accepted=0;pair_improved=False
        for sweep in range(MAX_REPAIR_SWEEPS):
            improved=False
            for a,z,width,k in windows:
                for branch,bundle in zip(branches,bundles):
                    if time.perf_counter()>=repair_end:break
                    if z<=branch['blocked']:continue
                    # Zero marginal prices and stabilized scarcity prices are
                    # alternate deterministic reconstructions, never a scan.
                    sigma=np.zeros(g.n) if sweep%2==0 else bundle.center
                    before=branch['joint'];before_all=[v['joint'] for v in branches]
                    path,detail=rebuild(g,branch,branch['control'],(a,z),sigma)
                    control=g.match(branch['first'],path);candidate=branch['current_gain']+control['increment'];attempts+=1
                    accept=candidate>before+1e-8
                    # Even a source-branch loser is offered to every other
                    # prefix. Search effort cannot create a branch-only pool.
                    added=pool.add(path,f'rebuild_{branch["name"]}_s{sweep}_n{k}_w{width}')
                    changed=[v['name'] for v,old in zip(branches,before_all) if v['joint']>old+1e-8]
                    if accept:
                        if not added or branch['joint']<candidate-1e-8:raise AssertionError('shared accepted candidate missing')
                        accepted+=1
                    improved |= bool(changed)
                    repair_trace.append(dict(sweep=sweep,branch=branch['name'],night=k,width=width,
                        prices='zero' if sweep%2==0 else 'prox_center',before=before,candidate=candidate,
                        after=branch['joint'],accepted=accept,new_common_path=added,
                        common_improved_branches=changed,seconds=time.perf_counter()-wall0,**detail))
                if time.perf_counter()>=repair_end:break
            pair_improved |= improved
            if time.perf_counter()>=repair_end or (sweep%2==1 and not pair_improved):break
            if sweep%2==1:pair_improved=False
        result['repair']=dict(attempts=attempts,accepted=accepted,sweeps=1+sweep)
        winner=max(branches,key=lambda v:(v['joint'],v['name']=='B'))
        result['branches']=[]
        for branch,bundle in zip(branches,bundles):
            audit=g.validate(branch['first'],branch['control'],branch['blocked'])
            row=dict(name=branch['name'],current_gain=branch['current_gain'],joint=branch['joint'],
                matched_old57=baseline[branch['name']],new_path_delta=branch['joint']-baseline[branch['name']],
                post_prox=prox_joint[branch['name']],rebuild_delta=branch['joint']-prox_joint[branch['name']],
                best_dual_upper=branch['current_gain']+bundle.best_upper,rounds=bundle.rounds,
                selected_origin=branch['origin'],audit=audit)
            if row['joint']>row['best_dual_upper']+1e-6:raise AssertionError('integer beats valid full dual')
            result['branches'].append(row)
            dump(output/f'BEST_{branch["name"]}.json',dict(first_action=branch['first_action'],first_ledger=branch['first'].tolist(),**row,future=plain_control(branch['control'])))
            np.savez_compressed(output/f'PRICE_{branch["name"]}.npz',center=bundle.center,box=bundle.box)
        result.update(status='completed',winner=winner['name'],winner_joint=winner['joint'],
            new_path_delta_vs_best_matched_old57=winner['joint']-max(baseline.values()),
            delta_vs_original_chronological_incumbent=winner['joint']-max(result['old_chronological_joint'].values()),
            common_pool_paths=len(pool.paths),matching_evaluations=pool.matches,
            graph=dict(targets=g.n,actions=g.na,shared_edges=len(g.target),starts=g.ns,
                       full_graph_rescan_each_price=True),coefficient_arrays_refreshed=False)
    except Exception as exc:
        import traceback
        result.update(status='error',reason=str(exc),traceback=traceback.format_exc())
    finally:
        if pool is not None:
            dump(output/'COMMON_PATH_POOL.json',[list(p) for p in sorted(pool.paths)])
            dump(output/'PATH_PROVENANCE.json',pool.origins);dump(output/'INCUMBENT_TRACE.json',pool.trace)
        dump(output/'BUNDLE_TRACE.json',[row for bundle in bundles for row in bundle.trace])
        dump(output/'REBUILD_TRACE.json',repair_trace)
        result.update(wall_seconds=time.perf_counter()-wall0,cpu_seconds=time.process_time()-cpu0,peak_rss_bytes=rss())
        dump(output/'RESULT.json',result)
        print(json.dumps({k:result.get(k) for k in ('status','reason','winner','winner_joint','new_path_delta_vs_best_matched_old57','wall_seconds','cpu_seconds','peak_rss_bytes')}),flush=True)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--seconds',type=float,default=TOTAL_SECONDS)
    a=p.parse_args();r=run(a.output,a.seconds);sys.exit(0 if r['status']=='completed' else 1)
