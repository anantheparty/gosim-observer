"""Generate independent worlds; export only public/config actor files.

This host generator may create truth. No truth file is read by the selector.
"""
from __future__ import annotations
import copy, csv, hashlib, json, math, resource, shutil, sys, time
from pathlib import Path
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parent
BASE=ROOT.parents[1]
sys.dont_write_bytecode=True

def dump(path,obj):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+'\n')

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def public_initial(root):
    def read(name):
        p=root/name
        if 'truth' in p.parts: raise ValueError('truth forbidden')
        return p.read_text()
    cfg=json.loads(read('config/v4_scenario.json'))
    fiber=json.loads(read('config/v4_fiber_config.json'))
    score=json.loads(read('config/v4_score_config.json'))
    targets=list(csv.DictReader(read('public/targets.csv').splitlines()))
    calendar=list(csv.DictReader(read('public/v4_night_calendar.csv').splitlines()))
    columns=['target_id','ra_deg','dec_deg','target_class','feature_flux','science_weight','required']
    rows=[[r[n] if n in ('target_id','target_class') else r[n].lower()=='true' if n=='required' else float(r[n]) for n in columns] for r in targets]
    field=fiber['field']; side=math.isqrt(int(field['n_fibers'])); glass=math.sqrt(float(field['fiber_area_deg2'])); pitch=glass+float(field['gap_deg'])
    nights=[{k:r[k] for k in ('night_id','night_date','observing_start_utc','observing_end_utc')} for r in calendar]
    site=dict(cfg['site']);site['minimum_altitude_deg']=float(cfg['minimum_altitude_deg'])
    initial=dict(schema_version='v4-initialize-v1',task_card=cfg['task_card'],site=site,
        survey=dict(start_utc=nights[0]['observing_start_utc'],end_utc=nights[-1]['observing_end_utc'],nights=nights,
                    slot_seconds=int(round(int(calendar[0]['night_seconds'])/int(calendar[0]['slot_count'])))),
        instrument=dict(**field,grid_side=side,glass_side_deg=glass,pitch_deg=pitch,fov_side_deg=side*pitch,exposure=fiber['exposure']),
        scoring=score,targets=dict(columns=columns,rows=rows),limits=cfg.get('limits',{}))
    return initial

def main():
    started=time.perf_counter();cpu=time.process_time()
    upstream=BASE/'results/cold_horizon_opportunity_policy_20261004/official'
    shutil.copytree(upstream,ROOT/'official',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    package=BASE/'results/cold_sparse_science_runtime_20261004/observer_sparse_exact_fault_20261004.zip'
    with ZipFile(package) as z:
        z.extractall(ROOT/'baseline_package')
        assert all((ROOT/'baseline_package'/n).read_bytes()==z.read(n) for n in z.namelist())
    sys.path.insert(0,str(ROOT/'official'))
    from challenge import v4_bundle
    ref=ROOT/'official/challenge/reference/v4'
    times=[]
    for q,(cs,ws) in enumerate([(20261004901,90501),(20261004902,90502)]):
        t=time.perf_counter();cput=time.process_time()
        configs={k:json.loads((ref/f'v4_{k}_config.json').read_text()) for k in ('catalog','weather','fiber','score')}
        c=configs['catalog'];w=configs['weather']
        c.update(seed=cs,seed_derivation='sha256-v1')
        c['footprint'].update(total_area_deg2=240.,n_components=2,component_area_weights=[.5,.5],
            component_centers=[[335.,-22.],[65.,-54.]],vertices_per_component=24,
            harmonic_amplitude_ranges=[.06,.04,.02],component_gap_deg=2.)
        c['targets'].update(total_count=192,n_cluster_centers=3,clustered_fraction=.25)
        c['observability'].update(start_date='2026-11-02',end_date='2026-12-04',minimum_window_seconds=900)
        w.update(seed=ws,seed_derivation='sha256-v1')
        w['survey'].update(start_date='2026-11-02',end_date='2026-12-04')
        for ev in w['weather_events']['conditions'].values():ev['count']=0
        for kind in ('rocket_launch','earthquake','instrument_fault'):w[kind]['count']=0
        w['terrain_obstruction']['sector_count']=[0,0];w['stress_tests']['enabled']=False
        configs['card']=dict(name=f'Public opportunity pilot {q}',card_id=f'opportunity-{q}',
            scenario_slug=f'opportunity-{q}',phase='synthetic-only',stress=False,wallclock_seconds=120,
            observation_requests=dict(count=0,window_nights=1,targets_per_request=3,minimum_completion_fraction=2/3))
        spec=ROOT/'specs'/f'W{ws}'
        for k,cfg in configs.items():dump(spec/('card.json' if k=='card' else f'v4_{k}_config.json'),cfg)
        dest=ROOT/'generated_worlds'/f'W{ws}'
        if dest.exists():raise ValueError('Refuse regeneration/seed rescue')
        v4_bundle.build_spec_bundle(dest,spec)
        sanitized=ROOT/'public_inputs'/f'W{ws}'
        for name in ('config/v4_scenario.json','config/v4_fiber_config.json','config/v4_score_config.json',
                     'public/targets.csv','public/v4_night_calendar.csv','public/footprint.csv'):
            out=sanitized/name;out.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(dest/name,out)
        initial=public_initial(sanitized);dump(sanitized/'initialize.json',initial)
        times.append(dict(world=f'W{ws}',wall_seconds=time.perf_counter()-t,cpu_seconds=time.process_time()-cput,
            public_sha256={str(p.relative_to(sanitized)):sha(p) for p in sanitized.rglob('*') if p.is_file()},
            night_count=len(initial['survey']['nights']),targets=len(initial['targets']['rows'])))
    dump(ROOT/'GENERATION_RECEIPT.json',dict(worlds=times,wall_seconds=time.perf_counter()-started,
        cpu_seconds=time.process_time()-cpu,max_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        baseline_zip_sha256=sha(package),baseline_member_count=len(list((ROOT/'baseline_package').rglob('*'))),
        generator_source_sha256={str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'official').rglob('*') if p.is_file()},
        actor_input_boundary='public_inputs only; truth not read/exported by selector'))
    print(json.dumps(times))

if __name__=='__main__':main()
