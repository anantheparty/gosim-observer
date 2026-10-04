"""Owned CPU generation coordinator, independent new worlds; never test before model lock."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import json,hashlib,time,argparse,platform
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
from data_pipeline import ROOT,build

def verify():
    freeze=json.loads((ROOT/'SOURCE_FREEZE.json').read_text())
    for name,h in freeze['files'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==h,('source changed',name)
    assert json.loads((ROOT/'MECHANICAL_GATE_SUMMARY.json').read_text())['passed']

def task(pair):
    seed,split=pair;verify();return build(seed,split,verify=False)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=12);parser.add_argument('--splits',nargs='+',choices=['train','cal','val','test'],default=['train','cal','val']);args=parser.parse_args();verify()
    if 'test' in args.splits:
        lock=json.loads((ROOT/'SELECTED_MODEL_LOCK.json').read_text());assert lock['validation_gate']['positive_launch_gate']
    bounds={'train':(961000,961095),'cal':(962000,962015),'val':(963000,963023),'test':(964000,964023)};pairs=[]
    for split in args.splits:
        lo,hi=bounds[split]
        for seed in range(lo,hi+1):
            if (ROOT/'datasets'/split/f'{seed}.npz').exists():raise RuntimeError('refusing existing data '+str(seed))
            pairs.append((seed,split))
    start=time.perf_counter();results=[];log=ROOT/'generation_progress.jsonl'
    if log.exists():raise RuntimeError('generation log exists: preserve failed job rather than overwrite')
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures={executor.submit(task,pair):pair for pair in pairs}
        for future in as_completed(futures):
            result=future.result();results.append(result)
            with log.open('a') as f:f.write(json.dumps(result)+'\n')
            print(json.dumps(dict(done=len(results),total=len(pairs),seed=result['seed'],split=result['split'],seconds=result['total_world_seconds'])),flush=True)
    summary=dict(schema='fresh-direct-target-world-manifest-v1',workers=args.workers,platform=platform.platform(),python=platform.python_version(),elapsed_wall_seconds=time.perf_counter()-start,world_count=len(results),sum_world_generation_seconds=sum(r['fresh_generation_seconds'] for r in results),sum_future_label_seconds=sum(r['future_label_seconds'] for r in results),sum_full_world_worker_seconds=sum(r['total_world_seconds'] for r in results),physical_label_rows=sum(r['valid_future_rows'] for r in results),bytes=sum(r['npz_bytes'] for r in results),worlds=sorted(results,key=lambda r:r['seed']),source_freeze_sha256=hashlib.sha256((ROOT/'SOURCE_FREEZE.json').read_bytes()).hexdigest(),no_test_generated='test' not in args.splits,scope='CPU data-generation cost only; this is not participant2CPU2GiB900s production gate')
    (ROOT/'DATA_MANIFEST.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k!='worlds'}),flush=True)
if __name__=='__main__':main()
