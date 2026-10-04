"""Current exposure finite-family controls; no future/controller objective."""
import numpy as np
PROGRAMS=('DARK','BRIGHT','BACKUP')

def multipliers(scoring):
    out=np.full((3,3),scoring['program']['mismatch_multiplier'],np.float64)
    for k,p in enumerate(PROGRAMS):out[k,k]=scoring['program']['multipliers'][p]
    return out

def prepare_original_rows(data,cases,actions,target_ids):
    """All original pairs retained, including deterministic invalid-altitude rows."""
    bystate={x['state']:x['action'] for x in actions}
    target_index={tid:i for i,tid in enumerate(target_ids)}
    for c in cases:
        if not c['original_point_case']:continue
        action=bystate[c['state']]
        lookup={(target_ids[int(data['idx'][r])],int(data['fiber'][r])):r for r in c['rows']}
        c['original_row_indices']=[lookup[(tid,int(f))] for f,tid in action['assignments'].items()]
        c['original_target_indices_by_fiber']={str(f):target_index[tid] for f,tid in action['assignments'].items()}
        assert len(c['original_row_indices'])==len(action['assignments'])

def options(data,cases,gain):
    """Public gain only; entire original action first, tie order deterministic."""
    result={}
    for state in sorted({c['state'] for c in cases}):
        family=[c for c in cases if c['state']==state]
        original=next(c for c in family if c['original_point_case'])
        program=PROGRAMS.index(original['original_program']);rows=original['original_row_indices']
        valid=np.asarray(data['altitude_valid'][rows],bool)
        candidates=[dict(kind='full_original',case=cases.index(original),program=program,rows=rows,
            value=float((gain[rows,program]*valid).sum()/original['duration']),duration=original['duration'])]
        for c in family:
            for program in range(3):
                pairs={}
                for r in c['rows']:
                    if not data['altitude_valid'][r] or gain[r,program]<=0:continue
                    fiber=int(data['fiber'][r]);prev=pairs.get(fiber)
                    if prev is None or gain[r,program]>gain[prev,program]:pairs[fiber]=r
                rows=[pairs[f] for f in sorted(pairs)]
                candidates.append(dict(kind='finite_family',case=cases.index(c),program=program,rows=rows,
                    value=float(gain[rows,program].sum()/c['duration']),duration=c['duration']))
        result[state]=candidates
    return result

def controls(data,cases,scoring,expected_gain):
    """Select on public expectations; true ledger and actual hit only judge."""
    m=multipliers(scoring)
    truth=np.maximum(data['weight'][:,None]*data['F'][:,None]*m[:,data['b']].T-data['truebest'][:,None],0)*data['actual_hit'][:,None]
    point=np.maximum(data['weight'][:,None]*data['point_factor'][:,None]*m[:,data['point_band']].T-data['best'][:,None],0)
    choices=options(data,cases,expected_gain);pchoices=options(data,cases,point)
    states=[]
    for state,items in choices.items():
        selected=max(range(len(items)),key=lambda k:items[k]['value']);pitems=pchoices[state]
        pselected=max(range(len(pitems)),key=lambda k:pitems[k]['value'])
        def judge(item):return float(truth[item['rows'],item['program']].sum()/item['duration'])
        nn=judge(items[selected]);original=judge(items[0]);prate=judge(pitems[pselected])
        assert items[0]['rows']==pitems[0]['rows'] and items[0]['program']==pitems[0]['program']
        states.append(dict(state=state,selected=items[selected],point_selected=pitems[pselected],
            original=items[0],rate=nn,point_original_rate=original,point_family_rate=prate,
            delta_original=nn-original,delta_point_family=nn-prate))
    if not states:return dict(states=[],mean_rate=0.,mean_original=0.,mean_point_family=0.,delta_original=0.,delta_point_family=0.)
    return dict(states=states,mean_rate=float(np.mean([s['rate'] for s in states])),
        mean_original=float(np.mean([s['point_original_rate'] for s in states])),
        mean_point_family=float(np.mean([s['point_family_rate'] for s in states])),
        delta_original=float(np.mean([s['delta_original'] for s in states])),
        delta_point_family=float(np.mean([s['delta_point_family'] for s in states])))
