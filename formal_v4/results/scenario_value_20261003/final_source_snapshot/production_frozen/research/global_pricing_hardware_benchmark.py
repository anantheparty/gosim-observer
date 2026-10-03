"""Public-alpha synthetic finite-column pricing benchmark on owned hardware.

Preparation is local/public-only. Execution uses exact copied pricing/oracle
source in an isolated ownedbenchmark folder, never a service import or API.
The values are synthetic nonnegative dual-incidence contributions, not scores.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,math,os,shutil,subprocess,sys,time
from datetime import datetime,timedelta,timezone
from pathlib import Path

os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def prepare(destination):
    import numpy as np
    from quality_profile_inversion import all_target_model
    from terrain_version_space import altaz_at,SPEED
    root=Path(__file__).resolve().parents[1];card=root/'practice_cards/alpha/alpha'
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    model=all_target_model(card);start=model.nights[0][0]+3600
    duration=np.unique(np.rint(np.linspace(60,3600,20)).astype(int))
    alt,az=altaz_at(np.full(len(model.ids),start),model.ra,model.dec,model.latitude,model.longitude)
    altaz=np.column_stack((alt,az));deg=math.pi/180
    vectors=np.column_stack((np.cos(alt*deg)*np.cos(az*deg),np.cos(alt*deg)*np.sin(az*deg),np.sin(alt*deg)))
    endpoint=model._alt(start+duration,np.arange(len(model.ids)))
    hleft=model._lst([start])[0]-model.ra
    until_lower=(180-hleft)%360
    lower=np.degrees(np.arcsin(np.clip(model.sinlat*model.sin_dec-model.coslat*model.cos_dec,-1,1)))
    minima=np.minimum(alt[None,:],endpoint)
    minima=np.where(until_lower[None,:]<=duration[:,None]*SPEED+1e-7,np.minimum(minima,lower[None,:]),minima)
    visible=minima>=model.minimum_altitude
    rng=np.random.default_rng(2026100302)
    # Explicit synthetic dual incidences, independent of unobserved quality.
    science_dual=rng.uniform(.1,2.,len(model.ids))
    quota_dual=rng.uniform(0,50,len(model.ids))*(rng.random(len(model.ids))<.1)
    request_dual=rng.uniform(0,100,len(model.ids))*(rng.random(len(model.ids))<.03)
    coverage=rng.uniform(0,1,(20,3,len(model.ids)))
    values=science_dual[None,None,:]*coverage+quota_dual[None,None,:]*(coverage>.5)+request_dual[None,None,:]*(coverage>.7)
    eligible=np.flatnonzero((alt>=model.minimum_altitude+.5)&(alt<=89.5))
    chosen=rng.choice(eligible,32768,replace=True)
    centers=altaz[chosen]+rng.uniform(-.4,.4,(32768,2))
    centers[:,0]=np.clip(centers[:,0],model.minimum_altitude,89.9);centers[:,1]%=360
    fiber=json.loads((card/'config/v4_fiber_config.json').read_text())['field']
    glass=math.sqrt(float(fiber['fiber_area_deg2']));pitch=glass+float(fiber['gap_deg'])
    np.savez_compressed(destination/'workload.npz',vectors=vectors,altaz=altaz,ra=model.ra,dec=model.dec,
                        centers=centers,values=values,visible=visible,duration=duration,target_id=np.array(model.ids))
    oracle=root/'upstream/gosim-observer-examples/runner/challenge'
    source_files=['__init__.py','v4_fiber_map.py','tile_geometry_simulator.py','contracts.py','observing_calendar.py','project_paths.py']
    (destination/'challenge').mkdir(exist_ok=True)
    for name in source_files:shutil.copyfile(oracle/name,destination/'challenge'/name)
    pricing=root/'research/interval_column_pricing.py'
    shutil.copyfile(pricing,destination/pricing.name)
    if Path(__file__).resolve()!=destination/Path(__file__).name:
        shutil.copyfile(__file__,destination/Path(__file__).name)
    metadata={'schema':'public-synthetic-global-pricing-workload-v1','card':'alpha','targets':len(model.ids),
        'start_utc':datetime.fromtimestamp(start,timezone.utc).isoformat().replace('+00:00','Z'),
        'site':{'latitude_deg':model.latitude,'longitude_deg':model.longitude},'minimum_altitude_deg':model.minimum_altitude,
        'D':20,'P':3,'centers':32768,'nfib':int(fiber['n_fibers']),'glass':glass,'pitch':pitch,
        'synthetic_values':'iid synthetic coverage × nonnegative science/quota/request dual weights; not science score or weather truth',
        'source_public_sha256':{n:sha(card/n) for n in ('public/targets.csv','public/v4_night_calendar.csv','config/v4_fiber_config.json')},
        'pricing_source_sha256':sha(pricing),'official_oracle_sha256':{n:sha(oracle/n) for n in source_files},
        'workload_npz_sha256':sha(destination/'workload.npz'),'seed':2026100302,'offset':'zero instrument offset',
        'finite_grid_only':True,'hidden_products_read':False}
    (destination/'workload_metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return metadata


def cpu_worker(workload,count,output):
    import numpy as np
    from interval_column_pricing import price_cpu
    p=Path(workload);meta=json.loads((p.parent/'workload_metadata.json').read_text());a=np.load(p)
    began=time.perf_counter()
    totals=price_cpu(a['vectors'],a['centers'][:count],a['values'],a['visible'],glass=meta['glass'],pitch=meta['pitch'],nfib=meta['nfib'])
    elapsed=time.perf_counter()-began
    np.save(output,totals)
    print(json.dumps({'centers':count,'elapsed_seconds':elapsed,'totals_sha256':sha(output)}),flush=True)


def power_snapshot():
    fields='name,power.draw,power.limit,memory.used,memory.total,utilization.gpu,temperature.gpu'
    try:
        p=subprocess.run(['nvidia-smi','--query-gpu='+fields,'--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=3)
        return {'fields':fields.split(','),'stdout':p.stdout.strip(),'returncode':p.returncode}
    except (OSError,subprocess.TimeoutExpired) as e:return {'unavailable':type(e).__name__}


def official_samples(a,meta,totals,count):
    import numpy as np
    from interval_column_pricing import recover_assignment
    from challenge.v4_fiber_map import FiberGrid,min_altitude_during
    grid=FiberGrid(meta['glass']**2,meta['pitch']-meta['glass'],meta['nfib'])
    picks=[(0,0,0),(count-1,19,2)]
    best=np.unravel_index(np.argmax(totals),totals.shape);picks.append(tuple(map(int,best)))
    start=datetime.fromisoformat(meta['start_utc'].replace('Z','+00:00'))
    counts=0;maxerr=0.
    for c,d,p in picks:
        assignment=recover_assignment(a['vectors'],a['centers'][c],a['values'][d,p],a['visible'][d],
                                      glass=meta['glass'],pitch=meta['pitch'],nfib=meta['nfib'])
        assert len(set(assignment.values()))==len(assignment)
        for f,i in assignment.items():
            offset=grid.tangent_offsets(*a['altaz'][i],*a['centers'][c]);assert offset is not None
            actual,region=grid.classify_offset(*offset);assert region=='glass' and actual==f
            altitude=min_altitude_during(float(a['ra'][i]),float(a['dec'][i]),start,start+timedelta(seconds=int(a['duration'][d])),{'site':meta['site']})
            assert altitude>=meta['minimum_altitude_deg']-1e-8
            counts+=1
        error=abs(sum(float(a['values'][d,p,i]) for i in assignment.values())-float(totals[c,d,p]))
        maxerr=max(maxerr,error);assert error<=1e-10
    return {'sampled_columns':len(picks),'official_assignments_checked':counts,'max_recovered_total_error':maxerr,
            'oracle':'official FiberGrid tangent_offsets/classify_offset + min_altitude_during'}


def run(directory,output,cpu_limit=30,gpu_extension_limit=10):
    import threading
    began=time.perf_counter();directory=Path(directory);output=Path(output)
    meta=json.loads((directory/'workload_metadata.json').read_text())
    if sha(directory/'workload.npz')!=meta['workload_npz_sha256']:raise ValueError('workload SHA mismatch')
    if sha(directory/'interval_column_pricing.py')!=meta['pricing_source_sha256']:raise ValueError('pricing source SHA mismatch')
    os.environ['NUMBA_CACHE_DIR']=str(directory/('jitcache-'+str(time.time_ns())))
    import_start=time.perf_counter()
    import numpy as np
    from numba import cuda
    from interval_column_pricing import price_cuda
    import_seconds=time.perf_counter()-import_start
    a=np.load(directory/'workload.npz');kwargs={'glass':meta['glass'],'pitch':meta['pitch'],'nfib':meta['nfib'],'max_cell_bytes':256*1024**2}
    before=power_snapshot();power=[];stop=threading.Event()
    def monitor():
        while not stop.is_set():
            power.append({'elapsed_seconds':time.perf_counter()-began,**power_snapshot()})
            stop.wait(.1)
    thread=threading.Thread(target=monitor,daemon=True);thread.start()
    result={'schema':'owned-public-synthetic-global-pricing-hardware-v1','metadata':meta,'python':sys.version,
            'numpy':np.__version__,'import_seconds':import_seconds,'max_cell_bytes':256*1024**2,
            'scope':'same finite batches, synthetic dual values; no service, API choose, hidden products, power-limit changes',
            'power_before':before,'batches':[]}
    cpu_used=0.
    try:
        for count in (128,512,4096):
            item={'centers':count,'finite_duration_program_columns':count*20*3,
                  'target_pointing_pairs':count*meta['targets'],'target_dual_checks_upper':count*meta['targets']*20*3,
                  'cell_workspace_bytes':count*20*3*meta['nfib']*8,'totals_bytes':count*20*3*8}
            cold=time.perf_counter();gpu=price_cuda(a['vectors'],a['centers'][:count],a['values'],a['visible'],**kwargs)
            item['first_call_end_to_end_seconds']=time.perf_counter()-cold
            if count==128:item['cold_JIT_context_transfer_compute_return_seconds']=item['first_call_end_to_end_seconds']
            warm=[]
            for _ in range(3):
                t=time.perf_counter();again=price_cuda(a['vectors'],a['centers'][:count],a['values'],a['visible'],**kwargs)
                warm.append(time.perf_counter()-t);np.testing.assert_array_equal(again,gpu)
            item['warm_end_to_end_seconds']=warm;item['warm_median_seconds']=float(np.median(warm))
            remaining=cpu_limit-cpu_used
            if remaining>0:
                path=directory/f'cpu_{count}.npy';t=time.perf_counter()
                try:
                    proc=subprocess.run([sys.executable,__file__,'--cpu-worker',str(directory/'workload.npz'),'--count',str(count),'--output',str(path)],
                                        capture_output=True,text=True,timeout=remaining)
                    cpu_used+=time.perf_counter()-t
                    if proc.returncode:raise RuntimeError(proc.stderr[-1000:])
                    timing=json.loads(proc.stdout.strip().splitlines()[-1]);cpu=np.load(path)
                    error=float(np.max(abs(cpu-gpu)))
                    np.testing.assert_allclose(cpu,gpu,rtol=1e-13,atol=1e-10)
                    item['cpu']=timing;item['full_CPU_CUDA_max_abs_error']=error
                    item['full_CPU_CUDA_verified']=True;item['warm_speedup_vs_CPU']=timing['elapsed_seconds']/item['warm_median_seconds']
                except subprocess.TimeoutExpired:
                    cpu_used+=time.perf_counter()-t;item['full_CPU_CUDA_verified']=False
                    item['cpu_budget_timeout_seconds']=remaining
            else:item['full_CPU_CUDA_verified']=False;item['CPU_skip_reason']='30s aggregate subprocess budget exhausted'
            item['official_recover_gate']=official_samples(a,meta,gpu,count)
            result['batches'].append(item)
            output.write_text(json.dumps(result,indent=2)+'\n')
            print(json.dumps({'completed_centers':count,'GPU_warm_seconds':item['warm_median_seconds'],'CPU_full_verified':item['full_CPU_CUDA_verified']}),flush=True)
        # Optional extension only if measured 4096 batch leaves ample <10s margin.
        last=result['batches'][-1]['warm_median_seconds']
        if last*8<gpu_extension_limit/2:
            t=time.perf_counter();extension=price_cuda(a['vectors'],a['centers'][:32768],a['values'],a['visible'],**kwargs)
            elapsed=time.perf_counter()-t
            result['GPU_only_extension']={'centers':32768,'end_to_end_seconds':elapsed,
                'within_10s':elapsed<=gpu_extension_limit,'full_CPU_comparison':False,
                'finite_columns':32768*20*3,'workspace_bytes':32768*20*3*meta['nfib']*8,
                'totals_bytes':extension.nbytes,'max_total':float(extension.max())}
        else:result['GPU_only_extension']={'skipped':'4096 measured timing does not justify <10s extension margin'}
    finally:
        stop.set();thread.join(timeout=4)
        result['power_samples']=power;result['power_after']=power_snapshot()
        result['aggregate_cpu_subprocess_wall_seconds']=cpu_used
        result['device']=str(cuda.get_current_device());result['total_benchmark_seconds']=time.perf_counter()-began
        result['hardware_power_limit_not_modified']=True
        output.write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prepare');p.add_argument('--run');p.add_argument('--cpu-worker');p.add_argument('--count',type=int);p.add_argument('--output')
    args=p.parse_args()
    if args.prepare:print(json.dumps(prepare(args.prepare),indent=2))
    elif args.cpu_worker:cpu_worker(args.cpu_worker,args.count,args.output)
    elif args.run:run(args.run,args.output)
    else:p.error('select prepare, run, or cpu-worker')
