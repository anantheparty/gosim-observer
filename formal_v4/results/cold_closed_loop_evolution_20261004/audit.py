#!/usr/bin/env python3
"""Checks geometric decoding, public feedback causality, and provenance."""
from pathlib import Path
import csv, json, random, time, hashlib
import numpy as np
from probe import OUT, ROOT, PartitionActor, choose_public_domain, canonical, digest

def main():
    started=time.monotonic(); checks=[]; work=[]
    rng=random.Random(424242)
    for card in ['L1','L2']:
        public,start=choose_public_domain(card)
        for mode in ['population','single']:
            high=json.loads((OUT/f'{card}_{mode}_high/result.json').read_text())
            low=json.loads((OUT/f'{card}_{mode}_low/result.json').read_text())
            checks.append({'name':f'{card}_{mode}_latent_initial_same','pass':high['trace'][0]['action_sha']==low['trace'][0]['action_sha'] and high['trace'][0]['partition_sha']==low['trace'][0]['partition_sha']})
            checks.append({'name':f'{card}_{mode}_feedback_changes_structure','pass':high['trace'][1]['partition_sha']!=low['trace'][1]['partition_sha'] and high['trace'][1]['action_sha']!=low['trace'][1]['action_sha']})
            actor=PartitionActor(public,start,mode)
            decoded=actor.evolve(0,1440);_,action,ids,_,_,batch=decoded
            hitcheck=actor.grid.assigned_hits({int(k):v for k,v in action['assignments'].items()},{t['target_id']:(t['ra_deg'],t['dec_deg']) for t in public['targets']},start,action['pointing']['alt_deg'],action['pointing']['az_deg'],public['site']['latitude_deg'],public['site']['longitude_deg'])
            checks.append({'name':f'{card}_{mode}_mandatory_batch_official_geometry','pass':all(public['targets'][i]['target_id'] in hitcheck and hitcheck[public['targets'][i]['target_id']] for i in batch) and all(hitcheck.values()) and len(set(action['assignments']))==len(action['assignments'])})
            checks.append({'name':f'{card}_{mode}_instrumentation_preserves_first_action','pass':digest(action)==high['trace'][0]['action_sha']})
            work.append({'card':card,'mode':mode,'first_decision_work':actor.work})
        actor=PartitionActor(public,start);aa,vec,_,_,_=actor.public_geometry(0,180)
        centers=np.array([(max(0,min(89,float(aa[rng.randrange(actor.n),0])+rng.uniform(-2,2))),float(aa[rng.randrange(actor.n),1]+rng.uniform(-2,2))%360) for _ in range(50)])
        fibers=actor.fibers(centers,vec);mismatch=0
        for ci,c in enumerate(centers):
            for i,t in enumerate(public['targets']):
                exact=actor.grid.classify_target(t['ra_deg'],t['dec_deg'],start,float(c[0]),float(c[1]),public['site']['latitude_deg'],public['site']['longitude_deg'])
                expected=exact.fiber_id if exact.region=='glass' else -1
                mismatch+=expected!=int(fibers[ci,i])
        checks.append({'name':f'{card}_1400_vectorized_official_classifications','pass':mismatch==0,'mismatches':mismatch})
    # Canonical equivalence relation survives arbitrary feedback deletions.
    bad=0
    for _ in range(2000):
        a=[rng.randrange(8) for _ in range(28)];b=canonical(a);live=[i for i in range(28) if rng.random()<.5]
        for i in live:
            for j in live:bad+=(a[i]==a[j])!=(b[i]==b[j])
    checks.append({'name':'canonical_partition_after_feedback_deletions','pass':bad==0,'mismatches':bad})
    gains=[]
    for card in ['L1','L2']:
        for world in ['high','low']:
            pop=json.loads((OUT/f'{card}_population_{world}/result.json').read_text());single=json.loads((OUT/f'{card}_single_{world}/result.json').read_text())
            gains.append({'card':card,'world':world,'population_total':pop['report']['total'],'single_total':single['report']['total'],'difference':pop['report']['total']-single['report']['total']})
    allowed=[ROOT/'formal_v4/upstream/gosim-observer-examples/runner/challenge'/n for n in ['v4_runner.py','v4_scorer.py','v4_fiber_map.py']]
    allowed += [ROOT/f'formal_v4/upstream/gosim-observer-examples/local-cards/{card}/public/{name}' for card in ['L1','L2'] for name in ['targets.csv','v4_night_calendar.csv']]
    allowed += [OUT/'probe.py',OUT/'audit.py']
    report={'checks':checks,'all_passed':all(x['pass'] for x in checks),'work':work,'gains':gains,'mean_difference':sum(x['difference'] for x in gains)/4,'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in allowed},'elapsed_seconds':time.monotonic()-started,'limits':'Synthetic constant-efficiency worlds, 28 public targets, 1440 simulated seconds; no future request, loss, fault, offset, background closure, or season test. Equal 32 unique structure evaluations do not equal physical work.'}
    (OUT/'audit.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':main()
