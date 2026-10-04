"""Independent official public-geometry and count-curvature checks."""
import json,sys,itertools,hashlib,zipfile
from pathlib import Path
import numpy as np
from jain_assignment import jain,gradient,Option,exact_select,linear_select,settle
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
sys.path.insert(0,str(ROOT/'formal_v4/runs/official_generator_e01939d0'))
from challenge.v4_fiber_map import FiberGrid,min_altitude_during,validate_action
from datetime import datetime,timedelta

summary=json.loads((OUT/'public_summary.json').read_text());geometry=[];curvature=[]
for state in summary['states']:
    if state['status']!='solved':continue
    root=ROOT/'formal_v4/upstream/gosim-observer-examples/local-cards'/state['card']
    config=json.loads((root/'config/v4_fiber_config.json').read_text())
    site=config['site'];grid=FiberGrid.from_config(config)
    import csv
    with (root/'public/targets.csv').open() as h:targets={r['target_id']:r for r in csv.DictReader(h)}
    now=datetime.fromisoformat(state['now_utc'].replace('Z','+00:00'))
    offset=state['pointing_offset_estimate']
    for row in state['rows']:
        if row['status']!='solved':continue
        action=row['candidate'];a={k:action[k] for k in ('action','pointing','assignments','duration_seconds')}
        validate_action(a,config)
        for fiber,tid in action['assignments'].items():
            target=targets[tid];ra,dec=float(target['ra_deg']),float(target['dec_deg'])
            hit=grid.classify_target(ra,dec,now,action['pointing']['alt_deg'],action['pointing']['az_deg'],
                site['latitude_deg'],site['longitude_deg'],*offset)
            minimum=min_altitude_during(ra,dec,now,now+timedelta(seconds=action['duration_seconds']),config)
            assert hit.region=='glass' and hit.fiber_id==int(fiber),(state['card'],row['scale'],tid)
            assert minimum>=30.,(state['card'],row['scale'],tid,minimum)
            geometry.append((state['card'],state['night_index'],row['scale'],tid))
        counts=np.asarray(row['band_completed_lower']);sizes=np.asarray(row['band_sizes']);active=row['active_bands']
        g=gradient(counts,sizes);base=jain(counts,sizes);worst=0.;examples=0
        # Superset of feasible count vectors; no scheduling or score bound claim.
        for values in itertools.product(range(17),repeat=len(active)):
            if sum(values)>16:continue
            delta=np.zeros(len(sizes),int)
            for b,v in zip(active,values):delta[b]=v
            error=200*(jain(counts+delta,sizes)-base-float(g@delta))
            worst=max(worst,abs(error));examples+=1
        curvature.append({'card':state['card'],'night':state['night_index'],'scale':row['scale'],
                          'count_vectors':examples,'max_absolute_Jain_linearization_error':worst})

synthetic=[]
for name,options in [
    ('completed_upgrade_vs_new_completion',[Option(0,0,.05,-1),Option(1,0,.06,0)]),
    ('two_band_complementarity',[Option(0,0,1.,-1),Option(1,0,1.2,0),Option(2,1,1.,-1),Option(3,1,.9,1)])]:
    counts=[5,5];sizes=[10,10];weight=200.
    exact=exact_select(options,counts,sizes,weight);linear=linear_select(options,counts,sizes,weight)
    synthetic.append({'name':name,'options':[o.__dict__ for o in options],'counts':counts,'sizes':sizes,'weight':weight,
        'linear_targets':[o.target for o in linear],'exact_targets':[o.target for o in exact['chosen']],
        'linear_full_value':settle(linear,counts,sizes,weight),'exact_full_value':exact['value'],
        'difference':exact['value']-settle(linear,counts,sizes,weight)})
zip_path=Path(json.loads((OUT/'INPUT_LOCK.json').read_text())['zip'])
with zipfile.ZipFile(zip_path) as z:
    source_equal={name:(OUT/'strong_package'/name).read_bytes()==z.read(name) for name in z.namelist()}
assert all(source_equal.values())
result={'official_nominal_geometry_assignments':len(geometry),'official_action_contracts':len(curvature),
    'geometry_uses_public_pointing_estimate':True,'actual_hidden_offset_used':False,'curvature':curvature,
    'counterexamples':synthetic,'all_38_package_members_byte_equal':all(source_equal.values()),
    'scope':'exact small assignment subproblem; not a global schedule certificate or actualfull benefit',
    'unavailable_states':[r for r in summary['states'] if r['status']!='solved']}
(OUT/'AUDIT_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'assignments':len(geometry),'contracts':len(curvature),'package_byte_equal':all(source_equal.values()),
    'counterexamples':synthetic,'max_curvature_error':max(r['max_absolute_Jain_linearization_error'] for r in curvature)}))
