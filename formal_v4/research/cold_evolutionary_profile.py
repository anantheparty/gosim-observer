#!/usr/bin/env python3
"""One-off CPU cost profile, explicitly outside the search budget."""
import json,time,os,hashlib
from pathlib import Path
import numpy as np
import cold_evolutionary_season as m

def measure(fn,repeats):
    fn();wall=time.perf_counter();cpu=time.process_time()
    for _ in range(repeats):fn()
    return {'repeats':repeats,'wall_seconds_per_call':(time.perf_counter()-wall)/repeats,'cpu_seconds_per_call':(time.process_time()-cpu)/repeats}

def main():
    result={'scope':'post hoc component microprofile, not actual per-iteration instrumentation','pid':os.getpid(),'cards':{}}
    for card in m.SOURCES:
        s,sp,cols,initial,reports,expected=m.load_or_build(card,m.OUT/card/'prepare');rng=np.random.default_rng(198);engine=m.Season(s,cols,expected['components']['report_settlement'],rng)
        seeds=json.loads((m.OUT/card/'seeds.json').read_text());parents=[]
        for method in ['ga','local']:
            path=m.OUT/card/method/'population.json'
            if path.exists():parents.extend(x['selected'] for x in json.loads(path.read_text())[:6])
        if not parents:parents=seeds
        best=max(parents,key=lambda p:engine.objective(p)['total']);mate=parents[-1];archive=[(p,engine.objective(p)) for p in parents]
        stats={'objective':measure(lambda:engine.objective(best),128),'mutation_and_repair':measure(lambda:engine.mutate(best),32),'crossover':measure(lambda:engine.crossover(best,mate),128),'diverse_archive':measure(lambda:engine.archive(archive,(best,engine.objective(best))),64),'parent_actions':len(best),'candidate_count':len(cols)}
        result['cards'][card]=stats;print(json.dumps({'profile':card,**stats}),flush=True)
    result['source_sha256']=hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest();m.dump(m.OUT/'cpu_component_profile.json',result)
if __name__=='__main__':main()
