"""Approved frozen-harness controls only, with fixed physical CPU slots."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys

from policy_iteration_gate import run, sha


def utc(value):
    return datetime.fromisoformat(value.replace("Z","+00:00"))


def prepare_late_control(out):
    initial=json.loads((out/"L1_initialize_public.json").read_text())
    start,end=utc(initial["survey"]["start_utc"]),utc(initial["survey"]["end_utc"])
    threshold=start+(end-start)*.75
    nights=[(utc(n["observing_start_utc"]),utc(n["observing_end_utc"])) for n in initial["survey"]["nights"]]
    rows=[json.loads(line) for line in (out/"natural_control/L1/rank_0064/control/public_prefix.jsonl").read_text().splitlines()]
    now=start
    selected=None
    for row in rows:
        action=row["action"]
        if now>=threshold and action.get("action")=="observe":
            selected=dict(public_rank=int(row["rank"]),public_now_utc=now.isoformat(),threshold_utc=threshold.isoformat(),step=row["step"])
            break
        kind=action.get("action")
        if kind=="wait":
            now=min(utc(action["until_utc"]) if "until_utc" in action else now+timedelta(seconds=action["duration_seconds"]),end)
        elif kind=="observe":
            exposure_end=min(now+timedelta(seconds=action["duration_seconds"]),end)
            night=next(((a,b) for a,b in nights if a<=now<b),None)
            now=min(exposure_end,night[1]) if night else exposure_end
    if selected is None:
        return None,None
    prefix=[row for row in rows if int(row["rank"])<selected["public_rank"]]
    path=out/f"L1_late_rank{selected['public_rank']}_prefix_public.jsonl"
    path.write_text("".join(json.dumps(row,separators=(",",":"))+"\n" for row in prefix))
    selected.update(prefix_rows=len(prefix),prefix_max_rank=max(r["rank"] for r in prefix),prefix_sha256=sha(path),
        selection_rule="First natural observed public state at/after 75% of initialize UTC calendar span; only public actions/timestamps/ranks",source_trace_sha256=sha(out/"natural_control/L1/rank_0064/control/public_prefix.jsonl"))
    (out/"late_control_public_selection.json").write_text(json.dumps(selected,indent=2)+"\n")
    return selected,path


def main():
    ap=argparse.ArgumentParser()
    for field in ("project","dependencies","kit","out","reference"):
        ap.add_argument("--"+field,type=Path,required=True)
    args=ap.parse_args()
    source_lock=json.loads((args.out/"source_lock.json").read_text())
    assert sha(Path(__file__).with_name("policy_iteration_gate.py"))==source_lock["harness_sha256"]
    # Shared initialization sidecars are host-produced public inputs and never
    # mounted into a participant. The frozen native initialization arrives by stdin.
    sys.path.insert(0,str(args.kit))
    from runner.challenge.v4_workflow import V4Workflow
    for card in ("L2","L3","L4"):
        initial=V4Workflow(args.kit/"local-cards"/card).initialize_payload(900)
        (args.out/(card+"_initialize_public.json")).write_text(json.dumps(initial,separators=(",",":"))+"\n")
    selection,prefix=prepare_late_control(args.out)
    own_source=dict(path=str(Path(__file__).resolve()),sha256=sha(Path(__file__).resolve()),
        frozen_harness_sha256=source_lock["harness_sha256"],main_source_lock_sha256=sha(args.out/"source_lock.json"),
        cpu_slots=dict(L2="8,9",L3="10,11",L4="12,13",L1_late="14,15"),
        scope="Three natural READY controls and one late accelerated READY control; no alternative policy trial or bulk",
        late_selection=selection)
    (args.out/"baseline_groundwork_source_lock.json").write_text(json.dumps(own_source,indent=2)+"\n")
    jobs=[]
    for card,slot in (("L2",4),("L3",5),("L4",6)):
        item=argparse.Namespace(**vars(args),card=card,rank=64,phase="natural_control",prefix=None)
        jobs.append((item,slot))
    if selection:
        jobs.append((argparse.Namespace(**vars(args),card="L1",rank=selection["public_rank"],phase="late_control",prefix=prefix),7))
    results=[]
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures=[executor.submit(run,"control",slot,item) for item,slot in jobs]
        for future in as_completed(futures):
            results.append(future.result())
            (args.out/"baseline_groundwork_summary.json").write_text(json.dumps(results,indent=2)+"\n")


if __name__=="__main__":
    main()
