#!/usr/bin/env python3
"""Spot-check real trajectory global labels using official BestLedger settlement."""
import json
from datetime import datetime,timezone
import numpy as np
from cold_neural_trajectory_teacher import TOUT,rows,utc,UPSTREAM
from runner.challenge.v4_scorer import (BestLedger,required_penalty,uniformity_penalty,
                                      observation_request_status)

def main():
    d=np.load(TOUT/"samples.npz");m=json.loads((TOUT/"manifest.json").read_text());checks=[]
    for source_id,s in enumerate(m["sources"]):
        from pathlib import Path
        src=Path(s["path"]);card=s["card"]
        observation=rows(src/"observations.csv");decisions=rows(src/"decisions.csv")
        times={int(x["observe_index"]):(utc(x["start_utc"]),utc(x["end_utc"]))
               for x in decisions if x["action"]=="observe"}
        msgs=[json.loads(l) for l in (src/"messages.jsonl").read_text().splitlines() if l.strip()]
        rawtargets=rows(UPSTREAM/"local-cards"/card/"public/targets.csv")
        targets=[{**r,"ra_deg":float(r["ra_deg"]),"required":r["required"].lower()=="true"} for r in rawtargets]
        cfg=json.loads((UPSTREAM/"local-cards"/card/"config/v4_score_config.json").read_text())
        indices=np.flatnonzero(d["global_source"]==source_id)
        for j in indices[np.unique(np.rint(np.linspace(0,len(indices)-1,5)).astype(int))]:
            a=int(d["global_observe_index"][j]);now=datetime.fromtimestamp(float(d["global_now"][j]),timezone.utc)
            invalid=set()
            for msg in msgs:
                if msg.get("record_type")=="state_resync" and utc(msg["issued_at_utc"])<=now:
                    w=msg["invalidated_window"];invalid.update(range(w["action_index_start"],w["action_index_end_exclusive"]))
            ledger=BestLedger()
            for r in observation:
                action=int(r["observe_index"])
                if action<a and action not in invalid:
                    start,end=times[action];ledger.record(action,r["target_id"],float(r["factor"]),float(r["score"]),start,end)
            factors=ledger.max_factors();science=sum(x[1] for x in ledger.best().values())
            _,req=required_penalty(targets,factors,cfg);_,uniform=uniformity_penalty(targets,factors,cfg)
            request=report=0.
            for msg in msgs:
                kind=msg.get("record_type")
                if kind=="report_result" and utc(msg["issued_at_utc"])<=now:report+=float(msg.get("score_delta",0))
                if kind=="observation_request" and utc(msg["issued_at_utc"])<=now:
                    r={**msg,"issued_at_utc":utc(msg["issued_at_utc"]),"deadline_utc":utc(msg["deadline_utc"])}
                    request+=observation_request_status(r,ledger)["reward"]
            official_prefix=science-req-uniform+request+report
            implied_prefix=float(s["official_total"])-float(d["global_y"][j])
            error=abs(official_prefix-implied_prefix)
            checks.append({"source":str(src),"card":card,"observe_index":a,"now_utc":now.isoformat(),
                "official_ledger_prefix":official_prefix,"dataset_implied_prefix":implied_prefix,"absolute_error":error})
    report={"checks":checks,"max_absolute_error":max(x["absolute_error"] for x in checks),
        "tolerance":.02,"passed":all(x["absolute_error"]<.02 for x in checks),
        "rounding_note":"CSV score/factor are six decimals; dataset arrays float32; exact global rule is independently settled by official BestLedger"}
    (TOUT/"official_prefix_audit.json").write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!="checks"}))
    if not report["passed"]:raise ValueError("official prefix settlement disagrees")

if __name__=="__main__":main()
