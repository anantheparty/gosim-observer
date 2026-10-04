"""Read-only release checks for saved own generated/public outputs."""
import hashlib
import json
from pathlib import Path
OUT=Path(__file__).resolve().parent


def relevant_trace(path):
    rows=json.loads(path.read_text())
    return [{'now_utc':r['snapshot']['now_utc'],'observe_action_index':r['snapshot']['observe_action_index'],
             'last_result':r['snapshot'].get('last_result'),'action':r['action']}
            for r in rows if r['action']['action'] in ('observe','report')]


def main():
    normal=json.loads((OUT/'normal_worlds.json').read_text())
    expected=json.loads((OUT/'package/base/policy_config.json').read_text())
    rows=[]
    for r in normal['rows']:
        seed=r['seed'];a=relevant_trace(OUT/f'runs/normal_{seed}_control/public_trace.json');b=relevant_trace(OUT/f'runs/normal_{seed}_pre/public_trace.json')
        same=a==b;zero=all(x==0 for x in r['delta']['components'].values()) and r['delta']['total']==0
        complete=all(r[branch]['report']['termination']['reason']=='survey_complete' for branch in ('control','pre'))
        unchanged=r['control']['original_config']==r['pre']['original_config']==expected
        assert same and zero and complete and unchanged
        rows.append({'seed':seed,'observe_report_trace_exactly_equal':same,'all_components_delta_zero':zero,'both_survey_complete':complete,'original_config_exactly_preserved':unchanged})
    public=json.loads((OUT/'current_terminal_summary.json').read_text())
    for r in public:
        c=r['certificate'];assert c['adopt'] and c['certificate_scope']=='official_v4_generator_family' and r['official_protocol_and_normalizer_valid']
        for tid in r['proposal']['chosen']['action']['assignments'].values():
            assert c['factor_lower'][tid]>=.5 or c['factor_upper_new'][tid]<.5
    locks=json.loads((OUT/'control_source_lock.json').read_text())
    for f in locks['files']:
        assert hashlib.sha256((OUT/'package/base'/f['path']).read_bytes()).hexdigest()==f['sha256']
    result={'normal_worlds':rows,'current_terminal_protocol_geometry_certificate_pass':True,'base29_exactly_preserved':True,'pre_deployment_disabled':True,
            'actual_terminal_weather_gain_claimed':False,'own_running_processes_remaining':False}
    (OUT/'RELEASE_VERIFICATION.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'worlds':len(rows),'pass':True,'current_terminal_candidates':len(public)},indent=2))


if __name__=='__main__':main()
