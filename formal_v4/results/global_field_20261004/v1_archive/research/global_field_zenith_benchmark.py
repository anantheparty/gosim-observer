"""Native endpoint cost/parity on independently exported offline prefix states.

The supplied raw factors are offline trace truth, not participant feedback.
No season benefit is inferred from these fixed-state rates.
"""
import ctypes
import importlib.util
import ast
import inspect
import json
from pathlib import Path
import sys
import time
import textwrap
import numpy as np

BASE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('global_field_experiment',BASE/'research/global_field_experiment.py')
ex=importlib.util.module_from_spec(spec);sys.modules[spec.name]=ex;spec.loader.exec_module(ex)

def main():
    _,Workflow,Grid,Planner,_,upper_rates,_,_=ex.prepare()
    import research.spatial_candidates as spatial
    from research.spatial_candidates import SpatialPlanner,DEG
    tree=ast.parse(textwrap.dedent(inspect.getsource(SpatialPlanner._evaluate)))
    fn=tree.body[0]
    # A verification-only clone: delete exactly the 72-duration truncation.
    removed=[x for x in fn.body if isinstance(x,ast.If) and 'len(durations) > 72' in ast.unparse(x.test)]
    assert len(removed)==1
    fn.body.remove(removed[0]);scope=dict(vars(spatial));exec(compile(tree,'uncapped_verification','exec'),scope)
    uncapped=scope['_evaluate']
    labels=BASE/'results/objective_graph_20261004'
    records=json.loads((labels/'zenith_prefix_probe.json').read_text())['records']
    lookup={(r['card'],r['rank']):r for r in records}
    lib=ctypes.CDLL(str(ex.OUT/'global_field_zenith_darwin_arm64.dylib'))
    array=np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS')
    lib.global_field_zenith_search.argtypes=[ctypes.c_int,array,array,array,array]
    lib.global_field_zenith_search.restype=ctypes.c_int
    results=[];planners={}
    for path in sorted(labels.glob('prefix_*.npz')):
        _,card,rank=path.stem.split('_');rank=int(rank)
        if card not in planners:planners[card]=Planner(Workflow(ex.OFFICIAL/'local-cards'/card).initialize_payload(900))
        p=planners[card];r=lookup[(card,rank)];d=np.load(path)
        frame=tuple(d[k] for k in ['vectors','up','k','scores','factors','mult','missing','rr','rt','rd','ub','urg'])+(int(d['seconds']),float(d['safety']),None)
        v=frame[0];alt=np.arcsin(np.clip(v[:,2],-1,1))/DEG;az=np.arctan2(v[:,1],v[:,0])/DEG%360
        upper=upper_rates(p,frame);idx=np.flatnonzero((upper>1e-10)&(alt>=p.min_alt+.04)&(frame[1]>=p.tmin))
        data=np.ascontiguousarray(np.column_stack((alt[idx],az[idx],frame[2][idx],frame[1][idx],frame[3][idx],frame[4][idx],p.weight[idx],
                 frame[11][idx],frame[6][idx],frame[7][idx],frame[8][idx],frame[9][idx],frame[10][idx],upper[idx],frame[5][:,idx].T,np.zeros(len(idx)))),dtype=float)
        for a in [90.,89.95]:
            cfg=np.ascontiguousarray([p.side,p.pitch,p.glass,p.tmin,frame[12],frame[13],p.req_threshold,p.req_penalty,p.uniform_threshold,
                                     0.,0.,16,0.,0.,0.,0.,28.,a],dtype=float)
            out=np.zeros((16,3));stats=np.zeros(5);ts=[]
            for j in range(5):
                started=time.perf_counter();count=lib.global_field_zenith_search(len(data),data,cfg,out,stats);ts.append(time.perf_counter()-started)
            assert count>=0
            best=None;gap=0.;cap_gap=0.;remaining_gap=0.;tolerant_gap=0.;worst=None
            for predicted,ca,cz in out[:count]:
                actual=SpatialPlanner._evaluate(p,(float(ca),float(cz)),idx,*frame)
                uncut=uncapped(p,(float(ca),float(cz)),idx,*frame)
                original_classify=p._classify
                def tolerant_classify(vectors,altitude,azimuth):
                    f,valid,margin=original_classify(vectors,altitude,azimuth)
                    return f,margin>=.008-1e-9,margin
                p._classify=tolerant_classify
                try:tolerant=uncapped(p,(float(ca),float(cz)),idx,*frame)
                finally:p._classify=original_classify
                if actual is not None:
                    assert predicted+1e-9>=actual[0]
                    gap=max(gap,predicted-actual[0])
                    uv=0. if uncut is None else uncut[0]
                    tv=0. if tolerant is None else tolerant[0]
                    cap_gap=max(cap_gap,uv-actual[0]);remaining_gap=max(remaining_gap,predicted-uv)
                    tolerant_gap=max(tolerant_gap,predicted-tv)
                    if worst is None or predicted-actual[0]>worst['gap']:
                        worst=dict(center=[float(ca),float(cz)],predicted=float(predicted),capped=actual[0],uncapped=uv,
                                   tolerant_uncapped=tv,gap=predicted-actual[0],
                                   tolerant_duration=None if tolerant is None else int(tolerant[2]),
                                   tolerant_selected=[] if tolerant is None else tolerant[4].tolist(),
                                   tolerant_fibers=[] if tolerant is None else tolerant[5].tolist())
                    if best is None or actual[0]>best[0]:best=actual
            results.append(dict(card=card,rank=rank,actual_alt=a,native_seconds_median=float(np.median(ts)),pool=int(stats[0]),
                        events=int(stats[1]),evaluations=int(stats[2]),period_deg=int(stats[4]),proposals=count,
                        best_rate=0. if best is None else best[0],cpu_phase_rate=r['control_rate'],
                        previous_zenith_rate=r['best_zenith_rate'],max_native_parent_gap=gap,
                        max_72_cap_gap=cap_gap,max_native_uncapped_gap=remaining_gap,
                        max_native_tolerant_gap=tolerant_gap,worst=worst))
    result=dict(offline_factor_truth=True,full_season=False,results=results,
                cpp_sha256=__import__('hashlib').sha256((BASE/'research/global_field_zenith.cpp').read_bytes()).hexdigest())
    (ex.OUT/'zenith_native_benchmark.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)

if __name__=='__main__':main()
