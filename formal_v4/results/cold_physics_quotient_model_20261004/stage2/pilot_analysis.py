"""Read-only, no-fit support audit and predeclared finite-family point control.

This runs after the four mechanical pilots. It does not select a model or alter
the source, sampling, calibration, numerical gates, or future split seeds.
"""
import hashlib,json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent
PROGRAMS=('DARK','BRIGHT','BACKUP')

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def selected_output(index):
    return ROOT/'fresh_output'/('output_v2' if index==0 else 'output_v3')

def analyze(index):
    base=selected_output(index);directory=base/'datasets/pilot'
    data=np.load(directory/f'{index}.npz',allow_pickle=False)
    cases=json.loads((directory/f'{index}_cases.json').read_text())
    actions=json.loads((directory/f'{index}_point_actions.json').read_text())
    host=json.loads((directory/f'{index}_point_host.json').read_text())
    receipt=json.loads((directory/f'{index}_receipt.json').read_text())
    history=json.loads((directory/f'{index}_history_judge.json').read_text())
    init=json.loads((base/'worlds'/f'pilot_{index}/public_initializer.json').read_text())
    scoring=init['scoring'];ids=init['targets']['rows'];cols=init['targets']['columns']
    targetids=[x[cols.index('target_id')] for x in ids]
    mismatch=scoring['program']['mismatch_multiplier']
    multip=np.full((3,3),mismatch,np.float64)
    for k,program in enumerate(PROGRAMS):multip[k,k]=scoring['program']['multipliers'][program]
    predicted=np.maximum(data['weight'][:,None]*data['point_factor'][:,None]*multip[:,data['point_band']].T-data['best'][:,None],0)
    realized=np.maximum(data['weight'][:,None]*data['F'][:,None]*multip[:,data['b']].T-data['truebest'][:,None],0)*data['actual_hit'][:,None]
    controls=[]
    for original in actions:
        state=original['state'];action=original['action']
        if action['action']!='observe':continue
        family=[c for c in cases if c['state']==state]
        originalcase=next(c for c in family if c['original_point_case'])
        declared=PROGRAMS.index(action['program'])
        lookup={(targetids[int(data['idx'][r])],int(data['fiber'][r])):r for r in originalcase['rows']}
        mandatory=[lookup[(tid,int(f))] for f,tid in action['assignments'].items()]
        assert len(mandatory)==len(action['assignments'])
        d=originalcase['duration'];pvalue=float(predicted[mandatory,declared].sum()/d)
        value=float(realized[mandatory,declared].sum()/d)
        assert abs(value-next(x['realized_science_rate'] for x in host if x['state']==state))<1e-12
        # The full original action is always option zero. This is a finite-family
        # control, not a recomputation of the source selector's entire search.
        options=[dict(kind='full_original',case=cases.index(originalcase),program=declared,rows=mandatory,predicted=pvalue,realized=value,duration=d)]
        for case in family:
            for program in range(3):
                assignment={}
                for r in case['rows']:
                    if not data['altitude_valid'][r]:continue
                    f=int(data['fiber'][r]);prev=assignment.get(f)
                    if predicted[r,program]>0 and (prev is None or predicted[r,program]>predicted[prev,program]):assignment[f]=r
                rows=[assignment[f] for f in sorted(assignment)]
                options.append(dict(kind='finite_family',case=cases.index(case),program=program,rows=rows,
                    predicted=float(predicted[rows,program].sum()/case['duration']),realized=float(realized[rows,program].sum()/case['duration']),duration=case['duration']))
        choice=max(range(len(options)),key=lambda j:options[j]['predicted']);winner=options[choice]
        controls.append(dict(state=state,full_original_rate=value,finite_point_rate=winner['realized'],delta=winner['realized']-value,
            full_original_predicted=pvalue,finite_point_predicted=winner['predicted'],original_retained_option_zero=True,
            selected_kind=winner['kind'],selected_case=winner['case'],selected_program=PROGRAMS[winner['program']],
            selected_duration=winner['duration'],selected_rows=winner['rows']))
    positive=data['R'][data['R']>0]
    return dict(pilot_index=index,receipt=receipt,band_counts=np.bincount(data['b'],minlength=3).tolist(),
        positive_R_quantile=np.quantile(positive,[0,.01,.1,.5,.9,.99,1]).tolist(),
        public_input_shapes={k:list(data[k].shape) for k in ['ht','hn','hm','cn','cm','q']},
        public_input_finite=all(bool(np.isfinite(data[k]).all()) for k in ['ht','hn','hm','cn','cm','q']),
        empty_historical_assignments=sum(not x['action']['assignments'] for x in history),
        public_hit_zero=sum(h['score']==0 for x in history for h in x['public_result']['hits']),
        public_hit_positive=sum(h['score']>0 for x in history for h in x['public_result']['hits']),
        controls=controls,
        full_original_mean_rate=float(np.mean([x['full_original_rate'] for x in controls])),
        finite_point_mean_rate=float(np.mean([x['finite_point_rate'] for x in controls])),
        finite_point_mean_delta=float(np.mean([x['delta'] for x in controls])),
        finite_point_changed_states=sum(x['selected_kind']!='full_original' for x in controls),
        consumed_files_sha256={p.name:sha(p) for p in directory.glob(f'{index}*')})

def main():
    lock=json.loads((ROOT/'ANALYSIS_FREEZE.json').read_text())
    assert lock['pilot_analysis.py']==sha(ROOT/'pilot_analysis.py')
    results=[analyze(i) for i in range(4)]
    dump(ROOT/'PILOT_ANALYSIS.json',dict(status='FOUR_FRESH_PILOT_SUPPORT_AUDIT_NO_FIT',
        analysis_source_sha256=sha(ROOT/'pilot_analysis.py'),worlds=results,
        numerical_export_gate_tested=False,production_NN_cost_gate_tested=False,NN_fit_started=False,
        scope='current science exposure marginal/finite family; full point action retained; no shared future path or full-season score claim'))
    print(json.dumps([{k:r[k] for k in ['pilot_index','band_counts','positive_R_quantile','empty_historical_assignments','public_hit_zero','finite_point_mean_delta','finite_point_changed_states']} for r in results],indent=2))
if __name__=='__main__':main()
