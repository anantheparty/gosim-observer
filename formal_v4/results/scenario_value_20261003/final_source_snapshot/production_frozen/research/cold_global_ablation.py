#!/usr/bin/env python3
"""Same candidate pool/time budget, restricting destroyed blocks to one night."""
import json
import pickle
import time
import numpy as np
import cold_global_search as m

out=m.ROOT/"results/cold_global_search_20261003/L1"
dest=out/"ablation_single_night";dest.mkdir(exist_ok=True)
s=m.load_scenario(m.UPSTREAM/"local-cards/L1/config/v4_scenario.json")
c=pickle.loads((out/"columns_a30_s91.pkl").read_bytes())
search=m.Search(s,c,np.random.default_rng(91))
baseline=search.chronological();start=time.monotonic()
selected,obj,iters=search.optimize(baseline,100,dest,widths=(1,))
actions=m.export_actions(s,c,selected,dest/"actions.jsonl")
native=m.replay(m.UPSTREAM/"local-cards/L1/config/v4_scenario.json",s,actions,dest/"native")
result={"seconds":100,"iterations":iters,"destruction_nights":[1],"optimized":obj,"native":native,"multinight_native_total":json.loads((out/"summary.json").read_text())["native_optimized"]["total"],"seed":91}
(dest/"summary.json").write_text(json.dumps(result,indent=2))
print(json.dumps({k:v for k,v in result.items() if k!="native"}),flush=True)
