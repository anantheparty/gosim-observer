"""Post-run required diagnostic from our own score ledger, never online input."""
from __future__ import annotations

import argparse,csv,hashlib,json,math,time
from collections import defaultdict
from pathlib import Path
import numpy as np

from required_opportunity_model import RequiredOpportunityModel,public_initial,parse,stamp


def audit(args):
    began=time.perf_counter()
    card,result=Path(args.card),Path(args.result)
    model=RequiredOpportunityModel(public_initial(card))
    targets={row['target_id']:row for row in csv.DictReader((card/'public/targets.csv').open())}
    decisions={int(row['observe_index']):row for row in csv.DictReader((result/'decisions.csv').open()) if row['action']=='observe'}
    actions={};count=0
    assigned=defaultdict(list)
    for line in (result/'actions.jsonl').open():
        action=json.loads(line)
        if action['action']=='observe':
            actions[count]=action
            for tid in action['assignments'].values():assigned[tid].append(count)
            count+=1
    if count!=len(decisions):raise AssertionError('action/decision observe order mismatch')
    observations=defaultdict(list)
    for row in csv.DictReader((result/'observations.csv').open()):observations[row['target_id']].append(row)
    report=json.loads((result/'score_report.json').read_text())
    missing=[tid for tid in model.ids if max((float(row['factor']) for row in observations[tid] if row['valid']=='true'),default=0)<model.threshold]
    if len(missing)!=report['counts']['required_missing']:raise AssertionError('missing factor ledger differs from official report')
    n,r=len(model.nights),len(model.ids)
    fields=('visible_seconds','normalized_Q_le1_assumption_upper','site_cap_geometry_upper','frozen_grid_factor',
            'frozen_grid_mass_seconds','geometry_upper_mass_seconds')
    arrays={field:np.zeros((r,n)) for field in fields}
    latest=np.full((r,n),np.nan)
    for night in range(n):
        for i in range(r):
            profile=model.profile(i,night,site_scale=args.site_scale,duration_safety=args.safety)
            for field in fields:arrays[field][i,night]=profile[field]
            if profile['latest_grid_start_utc']:latest[i,night]=parse(profile['latest_grid_start_utc']).timestamp()
        if night%10==0:print(json.dumps({'event':'public_profiles','night':night,'elapsed':round(time.perf_counter()-began,3)}),flush=True)
    output={'schema':'required-opportunity-postrun-audit-v1','card':card.name,
            'scope':'public opportunity models + own completed run; no online future-ledger use',
            'site_scale':args.site_scale,'duration_safety':args.safety,'required_count':r,
            'official_missing':len(missing),'missing':[],
            'factor_not_normalized_quality_is_capped':True,
            'source_sha256':{str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in
                             (card/'public/targets.csv',card/'public/v4_night_calendar.csv',
                              result/'observations.csv',result/'decisions.csv',result/'actions.jsonl')}}
    capacities=arrays['frozen_grid_mass_seconds']*model.flux[:,None]/model.f0t0
    for scale in (.35,.55,.75,1.,2.):
        feasible=capacities*scale/args.safety>=model.threshold
        geometry=arrays['visible_seconds']>=model.tmin
        output.setdefault('conditional_scale_sweep',[]).append({'site_scale':scale,
              'never_predicted_feasible':int(np.count_nonzero(~feasible.any(axis=1))),
              'geometry_nights':int(geometry.sum()),'predicted_quota_nights':int(feasible.sum()),
              'targets_with_fewer_quota_nights':int(np.count_nonzero(feasible.sum(axis=1)<geometry.sum(axis=1)))})
    for tid in missing:
        i=model.index[tid]
        profiles=[model.profile(i,night,site_scale=args.site_scale,duration_safety=args.safety,exact_refine=True) for night in range(n)]
        valid=[row for row in observations[tid] if row['valid']=='true']
        all_max=max((float(row['factor']) for row in observations[tid]),default=0)
        maximum=max((float(row['factor']) for row in valid),default=0)
        best=max(profiles,key=lambda row:row['frozen_checked_factor'])
        feasible=[row for row in profiles if row['frozen_checked_feasible']]
        geometry=[row for row in profiles if row['visible_seconds']>=model.tmin]
        records=[]
        for row in observations[tid]:
            d=decisions[int(row['observe_index'])]
            records.append({**row,'start_utc':d['start_utc'],'duration_seconds':int(d['duration_seconds'])})
        output['missing'].append({'target_id':tid,'ra_deg':float(targets[tid]['ra_deg']),
              'dec_deg':float(targets[tid]['dec_deg']),'flux':float(targets[tid]['feature_flux']),
              'target_class':targets[tid]['target_class'],'assignments':assigned[tid],
              'observation_records':records,'max_valid_factor':maximum,'max_all_factor':all_max,
              'invalidation_caused_missing':all_max>=model.threshold>maximum,
              'geometry_nights':len(geometry),'frozen_quota_nights':len(feasible),
              'last_geometry_night':geometry[-1]['night_date'] if geometry else None,
              'last_frozen_quota_night':feasible[-1]['night_date'] if feasible else None,
              'last_frozen_start':feasible[-1]['latest_checked_start_utc'] if feasible else None,
              'best_frozen_factor':best['frozen_checked_factor'],'best_frozen_night':best['night_date'],
              'best_frozen_start':best['checked_max_start_utc'],
              'frozen_geometry_upper':min(1.,max(p['geometry_upper_mass_seconds'] for p in profiles)*model.flux[i]/model.f0t0*args.site_scale/args.safety),
              'minimum_normalized_Q_for_3600':model.threshold*model.f0t0/(model.flux[i]*model.tmax),
              'normalized_Q_le1_upper':max(row['normalized_Q_le1_assumption_upper'] for row in profiles),
              'site_Z_le1_geometry_upper':max(row['site_cap_geometry_upper'] for row in profiles),
              'profiles':profiles})
    # Positive observed target scores are public evidence against broad permanent
    # azimuth masks at those particular locations/times, not a recovered terrain map.
    terrain={'NE':45.,'E':90.,'NW':315.}
    witness=[]
    for tid,rows in observations.items():
        row_target=targets[tid];ra=float(row_target['ra_deg']);dec=float(row_target['dec_deg'])
        sd,cd=math.sin(dec*math.pi/180),math.cos(dec*math.pi/180)
        for row in rows:
            if float(row['score'])<=0:continue
            d=decisions[int(row['observe_index'])];start=parse(d['start_utc']).timestamp();mid=start+int(d['duration_seconds'])/2
            hour=((float(model._lst([mid])[0])-ra+180)%360-180)*math.pi/180
            sine=model.sinlat*sd+model.coslat*cd*math.cos(hour)
            alt=math.asin(max(-1,min(1,sine)));cosalt=max(1e-12,math.cos(alt))
            az=math.degrees(math.atan2(-math.sin(hour)*cd/cosalt,(sd-math.sin(alt)*model.sinlat)/(cosalt*model.coslat)))%360
            directions=[name for name,angle in terrain.items() if abs((az-angle+180)%360-180)<25]
            if directions:witness.append({'target_id':tid,'observe_index':int(row['observe_index']),
                  'mid_alt_deg':math.degrees(alt),'mid_az_deg':az,'directions':directions,
                  'duration_seconds':int(d['duration_seconds']),'quality':float(row['quality']),
                  'factor':float(row['factor']),'score':float(row['score'])})
    output['permanent_coarse_direction_positive_witnesses']={'count':len(witness),
        'by_direction':{direction:sum(direction in row['directions'] for row in witness) for direction in terrain},
        'max_quality':max((row['quality'] for row in witness),default=0),
        'top_quality_examples':sorted(witness,key=lambda row:row['quality'],reverse=True)[:12]}
    output['diagnosis_counts']={'never_assigned':sum(not row['assignments'] for row in output['missing']),
          'invalidated_threshold':sum(row['invalidation_caused_missing'] for row in output['missing']),
          'threshold_gap_under_0_01':sum(.49<=row['max_valid_factor']<.5 for row in output['missing']),
          'no_frozen_opportunity':sum(row['frozen_quota_nights']==0 for row in output['missing']),
          'conditional_geometry_proves_infeasible':sum(bool(row['frozen_geometry_upper']<model.threshold) for row in output['missing']),
          'frozen_opportunities_but_never_assigned':sum(row['frozen_quota_nights']>0 and not row['assignments'] for row in output['missing'])}
    output['elapsed_seconds']=time.perf_counter()-began
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(out.with_suffix('.npz'),target_ids=np.array(model.ids),night_dates=np.array(model.night_dates),
                        latest_grid_start_seconds=latest,**arrays)
    out.write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps({'event':'complete','elapsed_seconds':output['elapsed_seconds'],
                      'diagnosis_counts':output['diagnosis_counts'],'out':str(out)}),flush=True)
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--card',default='formal_v4/practice_cards/delta/delta')
    parser.add_argument('--result',default='formal_v4/results/cloud_cd2_delta_20261003')
    parser.add_argument('--out',default='formal_v4/research/required_opportunity_delta_result.json')
    parser.add_argument('--site-scale',type=float,default=.55)
    parser.add_argument('--safety',type=float,default=1.10)
    audit(parser.parse_args())
