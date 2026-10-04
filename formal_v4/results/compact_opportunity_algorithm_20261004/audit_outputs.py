"""Independent serialized control/master feasibility audit, without a solver."""
from __future__ import annotations
import sys,json,hashlib
from pathlib import Path
sys.dont_write_bytecode=True
import numpy as np
import run as runtime

ROOT=Path(__file__).resolve().parent

def audit_pricing(world):
    out=ROOT/'pilot'/world;result=json.loads((out/'RESULT.json').read_text())
    initial=json.loads((runtime.OLD/'public_inputs'/world/'initialize.json').read_text())
    now=runtime.old.parse_utc(initial['survey']['start_utc']).timestamp();records=[]
    for row in json.loads((out/'PRICING_TRACE.json').read_text()):
        is_initial=row['branch']=='initial_pattern_LP'
        graph=np.load(out/('INITIAL_PUBLIC_NOMINAL_GRAPH.npz' if is_initial else 'COMMON_PUBLIC_NOMINAL_GRAPH.npz'))
        if is_initial:b=np.zeros(result['targets']);blocked=now
        else:
            name=row['branch'][len('common_recourse_'):]
            control=json.loads((out/f'CONTROL_{name.replace("=","_")}.json').read_text())
            b=np.asarray(control['first_nominal_ledger']);blocked=now+control['first_action']['duration_seconds']
        target=graph['target'];score=graph['score'];edge_action=graph['edge_action'];fiber=graph['fiber']
        starts=graph['starts'];ends=graph['ends'];endpoints=graph['endpoints'];na=len(starts)
        sigma=np.asarray(row['target_prices']);lam=np.asarray(row['time_prices']);repair=np.asarray(row['start_atom_dual_repair'])
        if np.any(sigma<0) or np.any(lam<0) or np.any(repair<0):raise RuntimeError('Negative persisted certificate prices')
        key=edge_action*16+fiber;cell=np.unique(key,return_inverse=True)[1]
        cellmax=np.zeros(cell.max()+1);np.maximum.at(cellmax,cell,np.maximum(0.,score-b[target])-sigma[target])
        cell_action=np.unique(key)//16
        revenue=np.bincount(cell_action,weights=cellmax,minlength=na)
        left=np.searchsorted(endpoints,starts);right=np.searchsorted(endpoints,ends)
        allowed=~((starts<blocked)&(ends>now));prefix=np.r_[0.,np.cumsum(lam)]
        price=revenue-(prefix[right]-prefix[left]);residual=max(0.,float(price[allowed].max()))
        expected_repair=np.zeros(len(lam));np.maximum.at(expected_repair,left[allowed],np.maximum(0.,price[allowed]))
        fixed_prefix=np.r_[0.,np.cumsum(lam+repair)]
        repaired_residual=max(0.,float((revenue-(fixed_prefix[right]-fixed_prefix[left]))[allowed].max()))
        upper=float(sigma.sum()+lam.sum()+repair.sum())
        error=max(abs(residual-row['pricing_residual']),float(np.max(np.abs(repair-expected_repair))),abs(upper-row['full_feasible_dual_upper']))
        if error>1e-7 or repaired_residual>1e-7:raise RuntimeError('Persisted full-graph certificate failed')
        records.append(dict(world=world,branch=row['branch'],iteration=row['iteration'],raw_residual=residual,
            repaired_residual=repaired_residual,upper=upper,certificate_max_error=error,full_actions_priced=int(allowed.sum()),all_valid=True))
    return records

def main():
    pricing=[]
    for world in ['W90501','W90502']:pricing.extend(audit_pricing(world))
    runtime.dump(ROOT/'PERSISTED_DUAL_CERTIFICATE_AUDIT.json',dict(all_passed=True,rounds=len(pricing),
        solver_rerun=False,certificates=pricing,scope='direct public graph evaluation of stored sigma/lambda/repair'))
    world='W90501';out=ROOT/'pilot'/world
    result=json.loads((out/'RESULT.json').read_text())
    graph=np.load(out/'PUBLIC_NOMINAL_GRAPH.npz');target=graph['target'];score=graph['score']
    fiber=graph['fiber'];edge_action=graph['edge_action'];starts=graph['starts'];ends=graph['ends'];endpoints=graph['endpoints']
    initial=json.loads((runtime.OLD/'public_inputs'/world/'initialize.json').read_text())
    actor=runtime.old.wrapper.wrapped(initial);p=actor.planner;now=runtime.old.parse_utc(initial['survey']['start_utc'])
    geom=runtime.old.PublicGeometry(p,int(initial['survey']['slot_seconds']),runtime.Cost())
    records=[]
    for branch in result['recourse']:
        action=branch['action'];b=runtime.old.score_action(p,geom,action,now)
        if abs(b.sum()-branch['current_nominal_gain'])>1e-9:raise RuntimeError('Serialized first-action score mismatch')
        blocked=now.timestamp()+action['duration_seconds'];name=branch['name'].replace('=','_')
        support=json.loads((out/f'MASTER_SUPPORT_{name}.json').read_text());targetload=np.zeros(p.n);timeload=np.zeros(len(endpoints)-1)
        objective=0.
        for mode in support:
            e=mode['action'];ids=np.asarray(mode['edges'],dtype=int);fraction=mode['fraction']
            if np.any(edge_action[ids]!=e) or len(np.unique(fiber[ids]))!=len(ids):raise RuntimeError('Master pattern not a complete physical assignment')
            if starts[e]<blocked and ends[e]>now.timestamp():raise RuntimeError('Master uses blocked first interval')
            np.add.at(targetload,target[ids],fraction)
            left=np.searchsorted(endpoints,starts[e]);right=np.searchsorted(endpoints,ends[e]);timeload[left:right]+=fraction
            objective+=fraction*float(np.maximum(0.,score[ids]-b[target[ids]]).sum())
        if targetload.max()>1.+1e-7 or timeload.max()>1.+1e-7:raise RuntimeError('Master capacity violation')
        if abs(objective-branch['future_LP_increment'])>1e-7:raise RuntimeError('Master support objective mismatch')
        control=json.loads((out/f'CONTROL_{name}.json').read_text())['control'];ledger=b.copy();intervals=[]
        for row in control['schedule']:
            e=row['action'];ids=row['targets'];fs=row['fiber'];scores=row['score']
            if len(set(fs))!=len(fs) or len(set(ids))!=len(ids):raise RuntimeError('Integer control duplicate fiber/target')
            if starts[e]<blocked and ends[e]>now.timestamp():raise RuntimeError('Integer control uses blocked first interval')
            if any(starts[e]<end and start<ends[e] for start,end in intervals):raise RuntimeError('Integer control interval overlap')
            intervals.append((starts[e],ends[e]))
            for i,f,s in zip(ids,fs,scores):
                witnesses=np.flatnonzero((edge_action==e)&(target==i)&(fiber==f))
                if len(witnesses)!=1 or abs(score[witnesses[0]]-s)>1e-10:raise RuntimeError('Control edge not in public graph')
                ledger[i]=max(ledger[i],s)
        if np.max(np.abs(ledger-np.asarray(control['final_ledger'])))>1e-9:raise RuntimeError('Integer target-best ledger mismatch')
        integer_value=float(ledger.sum())
        if abs(integer_value-branch['joint_feasible_integer_control'])>1e-8:raise RuntimeError('Control objective mismatch')
        records.append(dict(name=branch['name'],integer_nominal_value=integer_value,
            master_objective_error=objective-branch['future_LP_increment'],max_target_load=float(targetload.max()),
            max_time_load=float(timeload.max()),control_observations=len(intervals),all_valid=True))
    winner=next(row for row in result['recourse'] if row['name']==result['selected'])
    others=[row for row in result['recourse'] if row['name']!=result['selected']]
    integer_vs_others=winner['joint_feasible_integer_control']-max(row['joint_full_feasible_dual_upper'] for row in others)
    record=dict(all_passed=True,world=world,branches=records,winner_integer_lower_exceeds_every_other_finite_LP_upper=integer_vs_others,
        graph_sha256=hashlib.sha256((out/'PUBLIC_NOMINAL_GRAPH.npz').read_bytes()).hexdigest(),
        scope='serialized finite graph feasibility and fixed nominal science ledger; no actual weather/controller scoring')
    runtime.dump(ROOT/'SERIALIZED_FEASIBILITY_AUDIT.json',record)
    runtime.dump(out/'PROPOSED_FIRST_ACTION.json',dict(action=result['selected_action'],name=result['selected'],
        finite_nominal_delta_vs_B=result['selected_model_delta_vs_B'],certificate=record,
        deployment_authorized=False,scope='existing zero-history public pilot only'))
    print(json.dumps(dict(all_passed=True,branches=len(records),integer_vs_other_upper=integer_vs_others)))

if __name__=='__main__':main()
