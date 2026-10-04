"""Host-only fresh-world audit of the frozen NN's physical path support.

No checkpoint selection, repairs or actual-card truth inputs occur here.
The source's original synthetic history design is deliberately retained.
"""
from pathlib import Path
import json,sys,hashlib,time
sys.dont_write_bytecode=True
import numpy as np
ROOT=Path(__file__).resolve().parent;REPO=ROOT.parents[2]
OLD=REPO/'formal_v4/results/cold_predictive_world_model_20261004'
sys.path.insert(0,str(OLD))
from build_world_dataset import build,build_nights
from predictive_core import NumpyPredictor


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    lock={'model_sha256':sha(OLD/'joint_model.npz'),'generator_design_sha256':sha(OLD/'build_world_dataset.py'),
      'seeds':[869620,869635],'worlds':16,'query_indices_seed':869404,'queries_per_world':64,
      'paths_per_query':512,'path_seed':8954,'training':False,'actual_card_truth':False,
      'scope':'physical distribution support only; no source/checkpoint/actor modification'}
    (ROOT/'physical_distribution_lock.json').write_text(json.dumps(lock,indent=2))
    base=json.loads((OLD/'official/challenge/reference/v4/v4_weather_config.json').read_text())
    base['survey']['end_date']='2026-11-08'
    nights,slots=build_nights(base)
    model=NumpyPredictor(OLD/'joint_model.npz')
    rng=np.random.default_rng(8954);normal=rng.normal(size=(512,8));um=(np.arange(512)+.5)/512;uc=rng.random(512)
    choose=np.random.default_rng(869404)
    rows=[];points=0;closed=0;invalid_high=invalid_low=invalid_c=0;badpaths=0
    t=time.time()
    for seed in range(869620,869636):
        x,y,masks,pats,evalrows=build(seed,nights,slots,base)
        idx=choose.choice(len(x),min(64,len(x)),replace=False)
        world_total=world_high=world_low=world_bad=0
        for j in idx:
            c,z,op=model.samples(x[j],float(evalrows[j,0]),normal,um,uc)
            opened=op>0;E=z/c
            high=(E>1.+1e-12)&opened;low=(E<.1-1e-12)&opened
            overc=(c>1.5/(.5*.68)+1e-12)&opened
            points+=int(opened.sum());closed+=int((~opened).sum())
            invalid_high+=int(high.sum());invalid_low+=int(low.sum());invalid_c+=int(overc.sum())
            badpaths+=int(np.any(high|low|overc,axis=1).sum())
            world_total+=int(opened.sum());world_high+=int(high.sum());world_low+=int(low.sum())
            world_bad+=int(np.any(high|low|overc,axis=1).sum())
        rows.append({'seed':seed,'records':len(x),'queries':len(idx),'open_sample_slots':world_total,
                     'efficiency_gt1':world_high,'efficiency_lt0p1':world_low,'invalid_paths':world_bad})
    queries=sum(r['queries'] for r in rows)
    result={**lock,'queries':queries,'sample_paths':queries*512,'open_sample_slots':points,
      'closed_sample_slots':closed,'efficiency_gt1_slots':invalid_high,'efficiency_lt0p1_slots':invalid_low,
      'C_gt_physical_max_slots':invalid_c,'any_invalid_path_count':badpaths,
      'efficiency_gt1_fraction_open':invalid_high/max(1,points),
      'efficiency_lt0p1_fraction_open':invalid_low/max(1,points),'any_invalid_path_fraction':badpaths/(queries*512),
      'model_unchanged':sha(OLD/'joint_model.npz')==lock['model_sha256'],'seconds':time.time()-t,
      'worlds_detail':rows,'claim':'unconstrained Gaussian logC/logZ is approximate; impossible path mass is not proof of production regret'}
    assert result['model_unchanged']
    (ROOT/'physical_distribution_audit.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='worlds_detail'}))

if __name__=='__main__':main()
