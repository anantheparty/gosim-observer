"""CPU execution cost for an unfitted ordinary direct-target MLP, no training."""
import json,time,platform,os
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent

def softmax(x):
    x=x-x.max(axis=-1,keepdims=True);x=np.exp(x);return x/x.sum(axis=-1,keepdims=True)

def main():
    rng=np.random.default_rng(949209)
    # Context shared once per decision. Public target query is 56 features.
    stem=rng.normal(0,.01,(88,32)).astype(np.float32)
    moment=rng.normal(0,.01,(32,4)).astype(np.float32)
    histogram=rng.normal(0,.01,(32,195)).astype(np.float32)
    results=[]
    for rows in [512,4096,16384,65536]:
        x=rng.normal(0,1,(rows,88)).astype(np.float32)
        times=[];hist_times=[]
        for repeat in range(6):
            t=time.perf_counter();hidden=np.maximum(x@stem,0);mu=softmax(hidden@moment)
            times.append(time.perf_counter()-t)
            # Histograms only needed for targets with positive current best.
            t=time.perf_counter();p=softmax(hidden@histogram)
            hist_times.append(time.perf_counter()-t)
            assert np.isfinite(mu).all() and np.isfinite(p).all()
        results.append(dict(rows=rows,shared_stem_plus_moment_median_seconds=float(np.median(times[1:])),
            additional_full_histogram_median_seconds=float(np.median(hist_times[1:])),
            macs_per_query_stem_plus_moment=88*32+32*4,
            additional_macs_per_revisited_query=32*195,
            histogram_temporary_bytes=int(rows*195*4)))
    pilot=json.loads((ROOT/'PILOT_RESULT.json').read_text())
    seconds_per_label=pilot['official_scalar_label_seconds']/pilot['label_rows']
    train_rows=96*128*2*5*8
    other_rows=(16+24+24)*128*2*5*8
    out=dict(runtime='Unfitted random-weight float32 cost only; no accuracy claim',
        machine=platform.platform(),numpy=np.__version__,blas_threads=os.environ.get('OPENBLAS_NUM_THREADS'),
        results=results,official_scalar_seconds_per_label=seconds_per_label,
        proposed_train_rows_upper=train_rows,proposed_cal_val_test_rows_upper=other_rows,
        scalar_label_seconds_extrapolation=(train_rows+other_rows)*seconds_per_label,
        prototype_query_float32_storage_bytes=(train_rows+other_rows)*56*4,
        shared_history_storage_bytes=(96+16+24+24)*128*8*16*24*4,
        validity='Mac one BLAS thread; not 2CPU Linux production gate. Exact geometry and history encoding cost still need measurement.')
    (ROOT/'COST_PILOT.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out))

if __name__=='__main__':main()
