"""Exhaustive finite-pair ledger and executable rank-preserving action delta.

Only own official observations and independently gated conditional columns are
read. Predictions remain conditional. No challenge truth or simulator is read.
"""
from __future__ import annotations
import csv, hashlib, json, sys, time
from collections import defaultdict
from pathlib import Path
import numpy as np
from request_remote_owned_gate import initial_public
from quality_profile_inversion import all_target_model
from spatial_candidates import SpatialPlanner


def readlines(p): return [json.loads(x) for x in p.read_text().splitlines() if x]
def rows(p): return list(csv.DictReader(p.open()))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


class SparseLedger:
    def __init__(self, model, planner, decisions, observations, request, fixed_reward):
        self.model=model; self.planner=planner; self.decisions=decisions
        self.request=request; self.fixed_reward=fixed_reward
        self.by_target=defaultdict(list); self.original_ids=defaultdict(set)
        self.req_rows=defaultdict(list)
        for h in observations:
            if h['valid']!='true': continue
            j=int(h['observe_index']); tid=h['target_id']
            entry=(j,float(h['score']),float(h['factor']))
            self.by_target[tid].append(entry); self.original_ids[j].add(tid)
            d=decisions[j]
            if tid in request['target_ids'] and request['issued_at_utc']<=d['start_utc'] and d['end_utc']<=request['deadline_utc']:
                self.req_rows[tid].append(entry)
        self.bestscore={t:max(x[1] for x in hs) for t,hs in self.by_target.items()}
        self.bestfactor={t:max(x[2] for x in hs) for t,hs in self.by_target.items()}
        self.reqfactor={t:max((x[2] for x in self.req_rows[t]),default=0.) for t in request['target_ids']}
        self.science=sum(self.bestscore.values())
        self.required={model.ids[i] for i in np.flatnonzero(planner.required)}
        self.completed={t for t,g in self.bestfactor.items() if g>=.5}
        self.missing=self.required-self.completed
        self.bands=(model.ra//10).astype(int)
        self.band_total=np.bincount(self.bands); self.active=self.band_total>0
        self.completed_counts=np.zeros(len(self.band_total),dtype=int)
        for t in self.completed:self.completed_counts[self.bands[model.index[t]]]+=1

    def settle(self, columns):
        removed={c['original_observe_index'] for c in columns}
        added=defaultdict(list)
        affected=set()
        for c in columns:
            j=c['original_observe_index']; affected.update(self.original_ids[j])
            for t,e in c['entries'].items():added[t].append(e); affected.add(t)
        science=self.science; missing=len(self.missing)
        counts=self.completed_counts.copy(); reqf=self.reqfactor.copy()
        changed=[]
        for t in affected:
            remaining=[e for e in self.by_target[t] if e[0] not in removed]
            s=max([e[1] for e in remaining]+[e['score_lower'] for e in added[t]]+[0.])
            f=max([e[2] for e in remaining]+[e['factor_lower'] for e in added[t]]+[0.])
            science+=s-self.bestscore.get(t,0.)
            oldcomplete=t in self.completed; newcomplete=f>=.5
            dc=int(newcomplete)-int(oldcomplete)
            if dc:
                counts[self.bands[self.model.index[t]]]+=dc
                if t in self.required:missing-=dc
            if t in reqf:
                reqf[t]=max([e[2] for e in self.req_rows[t] if e[0] not in removed]+[e['factor_lower'] for e in added[t]]+[0.])
            changed.append({'target_id':t,'score_before':self.bestscore.get(t,0.),'score_after':s,
                            'factor_before':self.bestfactor.get(t,0.),'factor_after':f,'required':t in self.required})
        ratios=counts[self.active]/self.band_total[self.active]
        jain=float(sum(ratios)**2/(len(ratios)*sum(ratios**2)))
        completed=[t for t in self.request['target_ids'] if reqf[t]>=.5]
        reward=float(self.request['completion_reward']) if len(completed)>=self.request['minimum_completed'] else 0.
        uniform=200*(1-jain); total=science-50*missing-uniform+reward+self.fixed_reward
        return {'conditional_total':total,'science':science,'required_missing':missing,'uniformity_penalty':uniform,
                'REQ1_completed':completed,'REQ1_reward':reward,'changed_target_ledger':sorted(changed,key=lambda e:e['target_id'])}


def main():
    started=time.perf_counter(); root=Path(__file__).resolve().parents[2]
    sys.path.insert(0,str(root/'formal_v4/upstream/gosim-observer-examples/runner'))
    out=root/'formal_v4/results/request_quota_failure_20261003';run=root/'formal_v4/results/cloud_request_gpu_delta_20261003'
    card=root/'formal_v4/practice_cards/delta/delta'; initial,_=initial_public(card)
    model=all_target_model(card);planner=SpatialPlanner(initial)
    ds=[d for d in rows(run/'decisions.csv') if d['action']=='observe']
    original_actions=readlines(run/'actions.jsonl');observations=rows(run/'observations.csv')
    req=[m for m in readlines(run/'messages.jsonl') if m['record_type']=='observation_request'][0]
    report=json.loads((run/'score_report.json').read_text())
    fixed_reward=report['components']['report_settlement']+sum(r['reward'] for r in report['observation_requests'][1:])
    ledger=SparseLedger(model,planner,ds,observations,req,fixed_reward);baseline=ledger.settle([])
    assert abs(baseline['conditional_total']-report['total'])<.005
    columns=json.loads((out/'delta_one_for_one_columns.json').read_text())
    for c in columns:
        j=c['original_observe_index']; assert ds[j]['valid']=='true' and not(150<=j<169)
        assert c['start_utc']==ds[j]['start_utc'] and c['end_utc']==ds[j]['end_utc']
        assert c['action']['duration_seconds']==int(ds[j]['duration_seconds'])
        assert all(np.isfinite(v) for e in c['entries'].values() for v in e.values())
        assert set(c['entries'])==set(c['action']['assignments'].values())
    best=None;checked=0;qualified=0;mandatory_preserving_best=None
    for i,a in enumerate(columns):
        for b in columns[i+1:]:
            if a['original_observe_index']==b['original_observe_index'] or a['anchor']==b['anchor']:continue
            value=ledger.settle([a,b]);checked+=1
            if value['REQ1_reward']!=100:continue
            qualified+=1
            result={'changes':[a,b],'settlement':value,'conditional_total_difference':value['conditional_total']-baseline['conditional_total']}
            if best is None or value['conditional_total']>best['settlement']['conditional_total']:best=result
            if value['required_missing']<=baseline['required_missing']:
                if mandatory_preserving_best is None or value['conditional_total']>mandatory_preserving_best['settlement']['conditional_total']:mandatory_preserving_best=result
    if best:
        replacement={c['original_observe_index']:c['action'] for c in best['changes']}
        derived=[];j=0;changed_action_indices=[]
        for ai,a in enumerate(original_actions):
            if a['action']=='observe':
                if j in replacement:derived.append(replacement[j]);changed_action_indices.append(ai)
                else:derived.append(a)
                j+=1
            else:derived.append(a)
        assert j==len(ds) and len(derived)==len(original_actions)
        assert all(a==b for a,b in zip(original_actions,derived) if a['action']!='observe')
        oldobs=[a for a in original_actions if a['action']=='observe'];newobs=[a for a in derived if a['action']=='observe']
        assert len(oldobs)==len(newobs) and all(a['duration_seconds']==b['duration_seconds'] for a,b in zip(oldobs,newobs))
        assert all(oldobs[j]==newobs[j] for j in range(150,169))
        best['changed_action_indices']=changed_action_indices
        best['executable_file']='delta_rank_preserving_conditional_actions.jsonl'
        path=out/best['executable_file'];path.write_text(''.join(json.dumps(a,separators=(',',':'))+'\n' for a in derived))
        best['actions_sha256']=sha(path)
    result={'baseline':baseline,'columns':len(columns),'all_distinct_anchor_distinct_rank_pairs_checked':checked,
            'request_quorum_pairs':qualified,'best_pair':best,'best_pair_preserving_baseline_mandatory_count':mandatory_preserving_best,
            'exhaustive_within_provided_pair_family':True,'complete_over_all_physical_schedules':False,
            'conditional_only_not_official_score':True,'original_action_count':len(original_actions),'original_observe_count':len(ds),
            'scope':'fixed original slots, >.03 glass margin, whole visibility, narrow supported conditional quality, zero offset, E<=1 DARK lower',
            'observable_start_end_sequence_and_all_wait_report_actions_preserved':True,'invalidated_original_ranks_150_169_unchanged':True,
            'elapsed_seconds':time.perf_counter()-started,'input_columns_sha256':sha(out/'delta_one_for_one_columns.json'),'source_sha256':sha(Path(__file__))}
    (out/'delta_all_pairs_exact_ledger.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('best_pair','best_pair_preserving_baseline_mandatory_count')},indent=2))
    print('best', None if best is None else {k:v for k,v in best.items() if k!='changes'})


if __name__=='__main__':main()
