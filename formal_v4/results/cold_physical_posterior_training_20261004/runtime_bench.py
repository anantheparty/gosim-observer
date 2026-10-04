"""2CPU read-only public-fixture microbenchmark; no world generation/truth labels."""
import json,time,pickle,resource,platform
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from physical_core import Predictor
from physical_operator import qualities
ROOT=Path(__file__).resolve().parent
def contribution_config(qb,qz,flux,weight,duration,program,scoring):
    cfg=scoring['program'];names=['DARK','BRIGHT','BACKUP'];band=np.where(qb>=float(cfg['bands']['DARK']),0,np.where(qb>=float(cfg['bands']['BRIGHT']),1,2));mult=np.where(band==program,float(cfg['multipliers'][names[program]]),float(cfg['mismatch_multiplier']));f0t0=float(scoring['flux_zero_point'])*float(scoring['exposure_zero_point_seconds']);return weight[None,:]*np.minimum(1.,flux[None,:]*duration*qz/f0t0)*mult
def main():
    with (ROOT/'public_runtime_fixtures.pkl').open('rb') as f:fixtures=pickle.load(f)
    model=Predictor(ROOT/'physical_model.npz');bank=json.loads((ROOT/'physical_bank.json').read_text());rows=[]
    for i,(initial,slots,a,x,flux,weight) in enumerate(fixtures):
        stub=SimpleNamespace(design=dict(initial=initial,slots=slots,actions=[a]));probt=[];oprt=[]
        duration=int(a['duration']);end=max(s.end_utc.timestamp() for s in slots if s.night_id==slots[int(a['slots'][0])].night_id);durations=sorted({min(duration,int(end-a['start'])),*[min(t,int(end-a['start'])) for t in [60,300,900,1800,3600]]})
        for repeat in range(5):
            before=time.perf_counter();p=model.probabilities(x);probt.append(time.perf_counter()-before);before=time.perf_counter();checksum=0.
            for d in durations:
                qb,qz=qualities(stub,0,a['ra'],a['dec'],d,bank)
                for program in range(3):checksum+=float((contribution_config(qb,qz,flux,weight,d,program,initial['scoring']).sum(1)/d)@p)
            oprt.append(time.perf_counter()-before)
        rows.append(dict(case=i,targets=len(flux),durations=durations,programs=3,paths=len(bank),posterior_seconds=probt,integral_scores_seconds=oprt,checksum=checksum))
    allp=[v for r in rows for v in r['posterior_seconds']];allo=[v for r in rows for v in r['integral_scores_seconds']]
    result=dict(scope='public fixture inference and common fixed field durations/three programs; no actor/no complete season/no future truth/no generator invoked',python=platform.python_version(),numpy=np.__version__,platform=platform.platform(),max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,cpus=2,memory_limit_bytes=2147483648,posterior_seconds=dict(mean=float(np.mean(allp)),p95=float(np.quantile(allp,.95)),max=float(max(allp))),integral_scores_seconds=dict(mean=float(np.mean(allo)),p95=float(np.quantile(allo,.95)),max=float(max(allo))),rows=rows)
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
