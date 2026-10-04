"""Read only public geometry/calendar; no real card truth or actor rollouts."""
from __future__ import annotations
import csv, importlib.util, json, math, time
from datetime import timedelta
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('initial_horizon_pilot',ROOT/'pilot.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
from challenge.v4_fiber_map import FiberGrid, min_altitude_during
from challenge.v4_scorer import BestLedger
from research.spatial_candidates import SpatialPlanner, SIDEREAL_SPEED
from research.geometry import local_sidereal_deg, parse_utc


def rows(path):
    with Path(path).open(newline='') as h:return list(csv.DictReader(h))


def public_initial(root):
    # Read an explicit public allowlist; V4Workflow/Scenario loaders are not used.
    config=json.loads((root/'config/v4_scenario.json').read_text())
    f=json.loads((root/'config/v4_fiber_config.json').read_text())
    s=json.loads((root/'config/v4_score_config.json').read_text())
    n=rows(root/'public/v4_night_calendar.csv')
    columns=['target_id','ra_deg','dec_deg','target_class','feature_flux','science_weight','required']
    target_rows=rows(root/'public/targets.csv');grid=FiberGrid.from_config(f)
    return dict(site={**config['site'],'minimum_altitude_deg':config['minimum_altitude_deg']},
        instrument=dict(n_fibers=grid.n_fibers,grid_side=grid.n_side,
            fiber_area_deg2=grid.fiber_area_deg2,gap_deg=grid.gap_deg,
            glass_side_deg=grid.fiber_side_deg,pitch_deg=grid.pitch_deg,
            fov_side_deg=grid.fov_side_deg,exposure=f['exposure']),
        survey=dict(nights=n,start_utc=n[0]['observing_start_utc'],
                    end_utc=n[-1]['observing_end_utc'],slot_seconds=900),
        targets=dict(columns=columns,rows=[[x[c] for c in columns] for x in target_rows]),
        scoring=s),config


def visibility(planner,start,duration):
    h0=(local_sidereal_deg(start,planner.lon)-planner.ra+180)%360-180
    h1=h0+duration*SIDEREAL_SPEED
    sin0=planner.sin_lat*planner.sin_dec+planner.cos_lat*planner.cos_dec*np.cos(np.deg2rad(h0))
    sin1=planner.sin_lat*planner.sin_dec+planner.cos_lat*planner.cos_dec*np.cos(np.deg2rad(h1))
    minimum=np.minimum(sin0,sin1)
    # If the exposure crosses the lower culmination, endpoints alone fail.
    crosses=(np.ceil((h0-180)/360)<=np.floor((h1-180)/360))
    minimum=np.where(crosses,planner.sin_lat*planner.sin_dec-planner.cos_lat*planner.cos_dec,minimum)
    return minimum>=math.sin(math.radians(planner.min_alt)),np.rad2deg(np.arcsin(np.clip(minimum,-1,1)))


def audit_domain(root,indices,label):
    initial,config=public_initial(root);q=SpatialPlanner(initial);results=[];checks=[]
    for index in indices:
        for duration in [900,3600]:
            grids=[];times=[];night_labels=[]
            for k in range(index,min(index+3,len(q.nights))):
                a,b=q.nights[k]; t=a
                while t+timedelta(seconds=duration)<=b:
                    valid,minimum=visibility(q,t,duration)
                    grids.append(valid);times.append(t);night_labels.append(k)
                    if len(checks)<240:
                        i=(len(checks)*73+11)%q.n
                        exact=min_altitude_during(float(q.ra[i]),float(q.dec[i]),t,
                                                 t+timedelta(seconds=duration),config)
                        checks.append(abs(float(minimum[i])-exact))
                    t+=timedelta(seconds=900)
            masks=np.asarray(grids,dtype=bool)
            nights=np.asarray(night_labels)
            count=masks.sum(axis=0)
            first=masks[nights==index].any(axis=0)
            future=masks[nights>index].any(axis=0) if np.any(nights>index) else np.zeros(q.n,dtype=bool)
            current_only=first&~future
            counts_by_night=np.asarray([masks[nights==k].any(axis=0) for k in range(index,index+3)])
            available_nights=counts_by_night.sum(axis=0)
            results.append(dict(label=label,start_night_index=index,duration_seconds=duration,
                targets=q.n,current_night_eligible=int(first.sum()),
                current_only_among_three_nights=int(current_only.sum()),
                any_three_night_eligible=int((count>0).sum()),
                available_nights_histogram={str(k):int((available_nights==k).sum()) for k in range(4)},
                current_only_weight=float(q.weight[current_only].sum()),
                current_only_required=int(q.required[current_only].sum()),
                current_only_ids=[q.ids[i] for i in np.flatnonzero(current_only)],
                eligible_start_counts_quantiles=np.quantile(count[count>0],[0,.1,.5,.9,1]).tolist(),
                finite_start_count=len(times),grid_seconds=900,
                scope='Finite geometric service-start supply only; no unknown quality, shared field/fiber capacity, best ledger or policy score.'))
    return results,max(checks or [0.])


def toy():
    # Abstract finite complete-exposure columns, with official best ledger.
    # It demonstrates the missing decision structure, not a physical-card gain.
    def value(first,second):
        l=BestLedger()
        for rank,name in enumerate([first,second]):
            if name is not None:l.record(rank,name,1.,{'A':5.,'B':6.}[name])
        return sum(s for _,s in l.best().values())
    deterministic={'A_first':value('A','B'),'B_first':value('B','B')}
    # In path X only A remains in the second slot; in Y only B remains.
    # First action must be the same in both paths. Adaptive suffix is allowed.
    x=[value('A','A'),value('B','A')]
    y=[value('A','B'),value('B','B')]
    common_first=[(x[k]+y[k])/2 for k in range(2)]
    clairvoyant=(max(x)+max(y))/2
    return dict(deterministic_rare_A_current_rate=5,deterministic_flexible_B_current_rate=6,
                deterministic_totals=deterministic,
                stochastic_path_X_values=x,stochastic_path_Y_values=y,
                stochastic_common_first_expected_values=common_first,
                illegal_per_path_best_then_average=clairvoyant,
                correct_common_first_best=max(common_first),
                scope='Two time slots, one chosen complete field per slot, terminal best-only ledger; abstract feasible-column example without claiming a physical 16-fiber embedding.')


def main():
    started=time.perf_counter();cpu=time.process_time();results=[];errors=[]
    r,e=audit_domain(ROOT/'worlds/prior/W77101',[0],'pilot192');results+=r;errors.append(e)
    repo=ROOT.parents[2]
    for label in ['L1','L2']:
        root=repo/'formal_v4/upstream/gosim-observer-examples/local-cards'/label
        r,e=audit_domain(root,[0,7,17,35],label);results+=r;errors.append(e)
    result=dict(results=results,official_min_altitude_check_count=720,
                max_official_min_altitude_error_deg=max(errors),toy=toy(),
                cpu_seconds=time.process_time()-cpu,wall_seconds=time.perf_counter()-started,
                reads_real_truth=False,reads_L4=False,new_actor_rollouts=0)
    p.dump(ROOT/'PUBLIC_SCARCITY_AUDIT.json',result);print(json.dumps(result))


if __name__=='__main__':main()
