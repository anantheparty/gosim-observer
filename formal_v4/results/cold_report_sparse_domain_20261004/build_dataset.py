"""Independent sparse public-history worlds; test remains unopened."""
import json,time,hashlib
from pathlib import Path
import numpy as np
from sparse_world import ROOT,trajectory,XDIM
SPLITS={'train':range(820000,820064),'cal':range(830000,830008),'val':range(840000,840008),'test':range(850000,850016)}
NAMES=['x','y','loss','xw','xr','phase','quake','correct','step','total','world','yw','yr']
def build(names=('train','cal','val'),filename='report_dataset.npz'):
    started=time.time();arrays={};summary={}
    for split in names:
        columns=[[] for _ in NAMES];worlds=[]
        for seed in SPLITS[split]:
            records,info=trajectory(seed,collect=True);worlds.append(info)
            for c,values in zip(columns,zip(*records)):c.extend(values)
        for key,values in zip(NAMES,columns):
            dtype=np.float32 if key in ['x','xw','xr','loss'] else np.int32
            arrays[f'{split}_{key}']=np.asarray(values,dtype=dtype)
        assert all(arrays[f'{split}_{k}'].shape[1]==XDIM and np.isfinite(arrays[f'{split}_{k}']).all() for k in ['x','xw','xr'])
        summary[split]=dict(worlds=worlds,records=len(columns[0]),prevalence=float(arrays[f'{split}_y'].mean()))
        print(json.dumps(dict(split=split,records=len(columns[0]),seconds=time.time()-started)),flush=True)
    np.savez_compressed(ROOT/filename,**arrays)
    out=dict(splits=summary,seconds=time.time()-started,bytes=(ROOT/filename).stat().st_size,sha256=hashlib.sha256((ROOT/filename).read_bytes()).hexdigest(),test_unopened='test' not in names)
    (ROOT/(Path(filename).stem+'_manifest.json')).write_text(json.dumps(out,indent=2));print(json.dumps(out),flush=True)
if __name__=='__main__':build()
