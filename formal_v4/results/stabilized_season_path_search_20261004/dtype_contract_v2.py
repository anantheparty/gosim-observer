"""One new uint8 regression, independent of the full graph and old contracts."""
import json
from pathlib import Path
import numpy as np
from fixed_graph import FixedGraph as V1
from fixed_graph_v2 import FixedGraph as V2

def run():
    g=V2.__new__(V2);g.n=34;g.nf=16;g.starts=np.arange(17,dtype=float);g.ends=g.starts+1.
    g._edge_cache={e:(np.asarray([2*e,2*e+1],dtype=np.int32),np.asarray([0,15],dtype=np.uint8),np.ones(2)) for e in range(17)}
    assert g.edges(16)[1].dtype==np.uint8
    path=tuple(range(17));old_failed=False;error=None
    try:V1.match(g,np.zeros(34),path)
    except OverflowError as exc:old_failed=True;error=str(exc)
    assert old_failed
    nonempty=g.match(np.zeros(34),path);empty=g.match(np.ones(34),path)
    assert nonempty['increment']==34. and len(nonempty['schedule'])==17
    assert empty['increment']==0. and len(empty['schedule'])==17 and all(not r['targets'] for r in empty['schedule'])
    assert len(nonempty['schedule'][-1]['targets'])==2 and nonempty['schedule'][-1]['fibers']==[0,15]
    return dict(status='passed',actual_graph_loaded=False,exposures=17,fiber_dtype='uint8',boundary_resource_rows=[256,271],
        old_v1_overflow_reproduced=old_failed,old_error=error,nonempty_gain=34.,empty_gain=0.,
        nonempty_audit=g.validate(np.zeros(34),nonempty,0.),empty_audit=g.validate(np.ones(34),empty,0.))

if __name__=='__main__':
    r=run();(Path(__file__).resolve().parent/'DTYPE_CONTRACT_V2.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r))
