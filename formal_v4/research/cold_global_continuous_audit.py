#!/usr/bin/env python3
"""Validate exact column scores against the untouched official scalar scorer."""
import argparse,csv,json,pickle
import numpy as np
import cold_global_incumbent as c

ap=argparse.ArgumentParser();ap.add_argument("--card",choices=("L1","L2"),default="L1");args=ap.parse_args()
out=c.m.ROOT/"results/cold_global_search_20261003"/f"continuous_{args.card}"
s=c.m.load_scenario(c.m.UPSTREAM/"local-cards"/args.card/"config/v4_scenario.json")
gate=json.loads((out/"incumbent_gate.json").read_text());source=c.Path(gate["source"])
decisions=list(csv.DictReader((source/"decisions.csv").open()))
reports=[c.utc(r["start_utc"]) for r in decisions if r["action"]=="report"]
oracle=c.Oracle(s,reports)
columns,initial=pickle.loads((out/"columns_a3_s407.pkl").read_bytes())[:2]
rng=np.random.default_rng(81);errors=[];id_mismatches=[]
for k in rng.choice(np.arange(len(initial),len(columns)),100,replace=False):
    row=columns[k]
    native=oracle.row(c.datetime.fromtimestamp(row["start"],c.timezone.utc),c.datetime.fromtimestamp(row["end"],c.timezone.utc),row["action"],exact_native=True)
    if not np.array_equal(native["ids"],row["ids"]):id_mismatches.append(int(k))
    errors.append({"column":int(k),"g_max_error":float(np.max(np.abs(native["g"]-row["g"]))),"score_max_error":float(np.max(np.abs(native["scores"]-row["scores"]))),"request_bits_exact":native["bits"]==row["bits"]})
result={"columns":len(columns),"sampled_columns":len(errors),"id_mismatches":id_mismatches,"g_max_error":max(x["g_max_error"] for x in errors),"score_max_error":max(x["score_max_error"] for x in errors),"all_request_bits_exact":all(x["request_bits_exact"] for x in errors),"records":errors}
result["passed"]=not id_mismatches and result["g_max_error"]<1e-7 and result["score_max_error"]<1e-7 and result["all_request_bits_exact"]
(out/"column_scalar_audit.json").write_text(json.dumps(result,indent=2))
print(json.dumps({k:v for k,v in result.items() if k!="records"},indent=2))
if not result["passed"]:raise SystemExit(1)
