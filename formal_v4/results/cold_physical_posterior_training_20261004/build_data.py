"""Predeclared bank/train/cal/val generation. No test labels until frozen."""
import json,time,hashlib
import numpy as np
from physical_core import *
SPLITS={'bank':range(910000,910032),'train':range(911000,911096),'cal':range(912000,912016),'val':range(913000,913016),'test':range(914000,914016)}
K=256
def records(seed,queries=128):
    w=World(seed);state=PublicHistory(w);repaired=set();rng=np.random.default_rng(seed+401)
    chosen=set(rng.choice(np.arange(8,len(w.geometry)),min(queries,len(w.geometry)-8),replace=False).tolist());out=[]
    loss=next((x for x in w.stress if x['event_type']=='data_loss'),None);loss_done=False
    if loss:
        ref=next(e for e in w.events if e.event_id==loss['trigger_ref']);loss_t=ref.actual_end_utc.timestamp()
    for j,a in enumerate(w.geometry):
        if loss and not loss_done and a['start']>=loss_t:state.resync_count+=1;loss_done=True
        x=state.feature(w,j)
        if j in chosen and x is not None:out.append((x,path(w,j,repaired),seed,j))
        # Independent action design includes true and false public reports.
        # Repair continuation is recomputed in this world, preserving quake/jitter.
        if rng.random()<.012:
            fault=w.active(a['start'],repaired);state.report(a['start'],fault is not None)
            if fault is not None:repaired.add(fault.event_id)
            if j in chosen and x is not None:out.append((state.feature(w,j),path(w,j,repaired),seed,j))
        state.ingest(w,j,w.score(j,repaired)[0])
    return out
def build_bank():
    started=time.time();paths=[]
    for seed in SPLITS['bank']:paths.extend([r[1] for r in records(seed,64)])
    f=np.asarray([path_feature(p) for p in paths]);chosen=[int(np.argmin(np.sum((f-f.mean(0))**2,axis=1)))];dist=np.full(len(f),np.inf)
    for _ in range(K-1):
        dist=np.minimum(dist,np.sum((f-f[chosen[-1]])**2,axis=1));dist[chosen]=-1;chosen.append(int(np.argmax(dist)))
    bank=[paths[i] for i in chosen];(ROOT/'physical_bank.json').write_text(json.dumps(bank,separators=(',',':')))
    np.save(ROOT/'bank_features.npy',f[chosen]);out=dict(paths=len(paths),classes=K,seconds=time.time()-started,selection='single fixed farthest-point physical coverage, actual prototypes only',maxE=max(max(p['e']) for p in bank),maxC=max(max(p['c']) for p in bank))
    (ROOT/'bank_result.json').write_text(json.dumps(out,indent=2));print(json.dumps(out),flush=True)
def build(names):
    started=time.time();bf=np.load(ROOT/'bank_features.npy');bank=json.loads((ROOT/'physical_bank.json').read_text());healthy=np.asarray([p['fault'][0]==0 for p in bank]);arrays={};summary={}
    for split in names:
        xs=[];ix=[];ys=[];ds=[];seedrows=[];js=[]
        for seed in SPLITS[split]:
            rr=records(seed)
            for x,p,s,j in rr:
                labels,weights,distance=label_weights(p,bf,healthy if x[HISTORY*TOKEN_DIM+9]>.5 else None);xs.append(x);ix.append(labels);ys.append(weights);ds.append(distance);seedrows.append(s);js.append(j)
        for name,a in [('x',np.asarray(xs,np.float32)),('ix',np.asarray(ix,np.int16)),('y',np.asarray(ys,np.float32)),('projection_distance',np.asarray(ds,np.float32)),('seed',np.asarray(seedrows,np.int32)),('j',np.asarray(js,np.int16))]:arrays[split+'_'+name]=a
        summary[split]=dict(rows=len(xs),projection_distance_quantiles=np.quantile(ds,[0,.5,.9,.99,1]).tolist());print(json.dumps(dict(split=split,**summary[split],seconds=time.time()-started)),flush=True)
    name='test_data.npz' if names==['test'] else 'fit_data.npz';np.savez_compressed(ROOT/name,**arrays)
    out=dict(summary=summary,seconds=time.time()-started,bytes=(ROOT/name).stat().st_size,sha256=hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),test_unopened='test' not in names)
    (ROOT/(name+'.json')).write_text(json.dumps(out,indent=2));print(json.dumps(out),flush=True)
if __name__=='__main__':
    import sys
    if '--test' in sys.argv:build(['test'])
    else:build_bank();build(['train','cal','val'])
