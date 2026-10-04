import itertools,json,sys,time
from pathlib import Path
import numpy as np
from jain_assignment import Option,exact_select,linear_select,settle,jain

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]
sys.path.insert(0,str(ROOT/'formal_v4/runs/official_generator_e01939d0'))
from challenge.v4_scorer import uniformity_penalty
rng=np.random.default_rng(20261004);rows=[];all_cases=[];max_error=0.;official_error=0.;wins=ties=0
started=time.perf_counter()
for case in range(1000):
    nb=int(rng.integers(1,4));nf=int(rng.integers(1,6))
    sizes=rng.integers(8,30,nb);counts=np.asarray([rng.integers(0,n-5) for n in sizes])
    weight=float(rng.choice([0,20,200]));options=[]
    for f in range(nf):
        for k in range(int(rng.integers(1,4))):
            b=int(rng.integers(-1,nb));gain=float(rng.uniform(0,5))
            options.append(Option(len(options),f,gain,b))
    exact=exact_select(options,counts,sizes,weight,max_active_bands=None)
    brute=(-np.inf,None)
    domains=[[None]+[o for o in options if o.fiber==f] for f in range(nf)]
    for path in itertools.product(*domains):
        p=[o for o in path if o is not None];v=settle(p,counts,sizes,weight)
        if v>brute[0]:brute=(v,p)
    err=abs(exact['value']-brute[0]);max_error=max(max_error,err)
    assert err<1e-10,(case,err)
    lin=linear_select(options,counts,sizes,weight);diff=exact['value']-settle(lin,counts,sizes,weight)
    if diff>1e-10:wins+=1
    else:ties+=1
    # Official scorer check, with dummy targets defining every band population.
    targets=[];factors={};c2=counts.copy()
    for o in exact['chosen']:
        if o.band>=0:c2[o.band]+=1
    for b,n in enumerate(sizes):
        for k in range(int(n)):
            tid=f'{b}:{k}';targets.append({'target_id':tid,'ra_deg':b*10+1})
            if k<c2[b]:factors[tid]=.5
    config={'uniformity':{'ra_band_width_deg':10,'observed_factor_threshold':.5,'weight':weight}}
    _,cost=uniformity_penalty(targets,factors,config)
    official_error=max(official_error,abs(cost-weight*(1-jain(c2,sizes))))
    all_cases.append({'case':case,'sizes':sizes.tolist(),'counts':counts.tolist(),'weight':weight,
        'options':[o.__dict__ for o in options],'enumerated_paths':int(np.prod([len(v) for v in domains])),
        'exact_value':exact['value'],'brute_value':brute[0],
        'linear_value':settle(lin,counts,sizes,weight),'difference':diff,'status':'positive' if diff>1e-10 else 'tie',
        'linear_targets':[o.target for o in lin],'exact_targets':[o.target for o in exact['chosen']]})
    if diff>1 and len(rows)<4:rows.append({'case':case,'sizes':sizes.tolist(),'counts':counts.tolist(),'weight':weight,'options':[o.__dict__ for o in options], 'linear':[o.target for o in lin],'exact':[o.target for o in exact['chosen']], 'difference':diff})
result={'cases':1000,'enumeration_max_error':max_error,'official_uniformity_max_error':official_error,'exact_win':wins,'tie':ties,'negative':0,'counterexamples':rows,'seconds':time.perf_counter()-started}
(OUT/'synthetic_cases.json').write_text(json.dumps(all_cases,indent=2)+'\n')
(OUT/'checks.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
