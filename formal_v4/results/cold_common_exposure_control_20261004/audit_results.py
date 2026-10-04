"""Validate decoded public geometry and summarize the fixed budget experiment."""
import json,sys,hashlib
from datetime import timedelta
import numpy as np
import common_exposure as c
sys.path.insert(0,str(c.BASE/'upstream/gosim-observer-examples'))
from runner.challenge.v4_fiber_map import FiberGrid,min_altitude_during,validate_action

def main():
    overview=[];actions=0;hits=0
    for card,night in [('L1',7),('L1',17),('L2',7),('L2',17)]:
        path=c.OUT/f'{card}_night{night}.json'
        if not path.exists():continue
        r=json.loads(path.read_text());pol,snap,env,meta=c.public_prefix(card,night);p=pol.planner
        assert abs(r['public_score_sum']-pol.scores.sum())<1e-7
        assert r['now_utc']==snap['now_utc'] and r['prefix_sha256']==meta['prefix_sha256']
        init=c.initial(card);fiber=dict(field={k:init['instrument'][k] for k in ('n_fibers','fiber_area_deg2','gap_deg')},
                                      exposure=init['instrument']['exposure'])
        grid=FiberGrid.from_config(fiber);config=dict(site=init['site']);origin=c.parse_utc(r['now_utc'])
        def audit(a,t):
            nonlocal actions,hits
            b={k:v for k,v in a.items() if k in ('action','pointing','assignments','duration_seconds')}
            validate_action(b,fiber);assert a['program'] in c.PROGRAMS
            start=origin+timedelta(seconds=t);end=start+timedelta(seconds=a['duration_seconds'])
            assert t>=0 and t+a['duration_seconds']<=14400
            for f,tid in a['assignments'].items():
                i=p.index[tid]
                hit=grid.classify_target(p.ra[i],p.dec[i],start,a['pointing']['alt_deg'],a['pointing']['az_deg'],
                    p.lat,p.lon,env.get('pointing_offset_alt_deg',0),env.get('pointing_offset_az_deg',0))
                assert hit.region=='glass' and hit.fiber_id==int(f),(tid,t,hit)
                assert min_altitude_during(p.ra[i],p.dec[i],start,end,config)>=p.min_alt
                hits+=1
            actions+=1
        rows=[];failed=0
        for result in r['results']:
            all_solutions=[result['unrestricted']]
            for candidate in result['candidates']:
                audit(candidate['action'],0)
                all_solutions.extend([candidate['joint'],candidate['empty_interval']])
            for sol in all_solutions:
                failed+=int(sol.get('no_solver_incumbent',False))
                prior=0
                for a in sol['path']:
                    assert a['start_seconds']>=prior
                    audit(a,a['start_seconds']);prior=a['start_seconds']+a['duration_seconds']
            baseline=result['candidates'][0]['joint']['value']
            row=dict(scale=result['quality_scale_multiplier'],order=result['order'],winner=result['winner'],
                strict_certified=result['certified_strict_winner'],baseline_value=baseline,
                joint_values=[x['joint']['value'] for x in result['candidates']],
                relative_to_strong=[x['joint']['value']-baseline for x in result['candidates']],
                pairwise_margin_over_strong_upper=[x['joint']['value']-result['candidates'][0]['joint']['upper_value'] for x in result['candidates']],
                durations=[x['action']['duration_seconds'] for x in result['candidates']],
                time_opportunity_losses=[x['all_target_time_opportunity_loss'] for x in result['candidates']],
                time_opportunity_intervals=[x['opportunity_loss_interval'] for x in result['candidates']],
                unassigned_target_net=[x['displaced_unassigned_net'] for x in result['candidates']],
                coverage_overlap_losses=[x['coverage_overlap_loss'] for x in result['candidates']],
                solver_gaps=[x['joint']['gap'] for x in result['candidates']],
                primal_sources=[x['joint'].get('primal_source') for x in result['candidates']])
            rows.append(row)
        pairwise=[i for i in range(1,len(rows[0]['joint_values'])) if all(
            row['pairwise_margin_over_strong_upper'][i]>1e-6 for row in rows)]
        overview.append(dict(card=card,night=night,now_utc=r['now_utc'],
            strong_baseline_duration=r['strong_baseline']['duration_seconds'],catalog=r['catalog'],
            columns=r['future_columns'],build_seconds=r['build_seconds'],total_seconds=r['total_seconds'],
            no_incumbent_solves=failed,stable_certified_change=r['stable_ranking_change'],
            observed_stable_pairwise_candidates=pairwise,predeclared_adoption_gate_changed=False,rows=rows))
    c.dump(c.OUT/'audit_summary.json',dict(states=overview,decoded_actions_checked=actions,
        decoded_assignments_checked=hits,public_prefix_reconstruction_matched=True,
        geometry_uses_public_point_estimate=True,actual_pointing_truth_read=False))
    locked=['common_exposure.py','check_operator.py','audit_results.py','PREDECLARATION.json','checks.json']
    c.dump(c.OUT/'MANIFEST.json',dict(files={name:c.sha(c.OUT/name) for name in locked},
        control_zip=c.sha(c.ZIP),control_members={str(path.relative_to(c.CONTROL)):c.sha(path)
            for path in c.CONTROL.rglob('*') if path.is_file() and '__pycache__' not in str(path)},
        new_source_frozen_after_initialization_fixes=True,full_season_run=False,production_adopted=False,
        solver='SciPy 1.14.1 milp/HiGHS; default host thread selection; no 2CPU limit gate',
        forbidden_actual_inputs_consumed=[]))
    print(json.dumps(dict(states=len(overview),actions_checked=actions,assignments_checked=hits)))

if __name__=='__main__':main()
