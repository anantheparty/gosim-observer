#!/usr/bin/env python3
"""Real strong-policy trajectory teacher, using only public local L1--L3 runs.

Inputs reconstruct participant-visible past information. Raw factor and final
validity are used for endpoint LABELS, not leaked as current state features.
These are behavior-policy continuation labels, not causal action advantages.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np

from cold_neural_value import Catalog,UPSTREAM,BASE,OUT,rows,utc,public_times

TOUT=OUT/"strong_trajectory_teacher"
FEATURES=["log_flux","science_weight","required","current_factor_lower","current_best_fraction",
          "remaining_visible_slots","future_peak_geometry","current_altitude","local_missing_required",
          "required_pressure","band_fraction","global_fraction","remaining_season","local_missing_targets",
          "active_request_member","request_reward_per_quota","request_hours_left","recent_quality_lower"]

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def sources(card):
    selected=[]
    # Explicitly local L1--L3 only. No cloud/practice outputs or future truth.
    for path in sorted((BASE/"runs").glob(f"*/{card}/observations.csv")):
        d=path.parent;report=d/"score_report.json"
        if not report.exists() or not (d/"decisions.csv").exists():continue
        r=json.loads(report.read_text())
        if r.get("termination",{}).get("reason")!="survey_complete" or r.get("total",-1)<4000:continue
        if r.get("scenario")!=f"v4-{card.lower()}":continue
        selected.append(d)
    return selected

def catalog(card):
    raw=rows(UPSTREAM/"local-cards"/card/"public/targets.csv")
    targets=[{**r,"ra_deg":float(r["ra_deg"]),"dec_deg":float(r["dec_deg"]),
        "feature_flux":float(r["feature_flux"]),"science_weight":float(r["science_weight"]),
        "required":r["required"].lower()=="true"} for r in raw]
    cfg=json.loads((UPSTREAM/"local-cards"/card/"config/v4_scenario.json").read_text())
    score=json.loads((UPSTREAM/"local-cards"/card/"config/v4_score_config.json").read_text())
    return Catalog(targets,cfg["site"],public_times(card),score)

def generate(every=2,sample=192):
    TOUT.mkdir(parents=True,exist_ok=True);begin=time.monotonic()
    xx,yy,cc,meta=[],[],[],[]
    gx,gy,gc,gs,ga,gt=[],[],[],[],[],[]
    for ci,card in enumerate(["L1","L2","L3"]):
        cat=catalog(card)
        for si,src in enumerate(sources(card)):
            obs=rows(src/"observations.csv");decs=rows(src/"decisions.csv")
            report=json.loads((src/"score_report.json").read_text())
            by_action={};history=[];invalid=set()
            finalbest=np.zeros(len(cat.ids),np.float32);finalfactor=np.zeros(len(cat.ids),np.float32)
            for r in obs:
                i=cat.index[r["target_id"]];s=float(r["score"]);f=float(r["factor"]);a=int(r["observe_index"])
                by_action.setdefault(a,[]).append((i,s,f))
                if r["valid"]=="true":finalbest[i]=max(finalbest[i],s);finalfactor[i]=max(finalfactor[i],f)
            msgs=[json.loads(l) for l in (src/"messages.jsonl").read_text().splitlines() if l.strip()]
            resync=[m for m in msgs if m.get("record_type")=="state_resync"]
            requests=[m for m in msgs if m.get("record_type")=="observation_request"]
            resync.sort(key=lambda m:m["issued_at_utc"]);cursor=0
            reqdata=[(utc(r["issued_at_utc"]),utc(r["deadline_utc"]),r) for r in requests]
            curbest=np.zeros(len(cat.ids),np.float32)
            currawfactor=np.zeros(len(cat.ids),np.float32)
            report_results=[m for m in msgs if m.get("record_type")=="report_result"]
            rng=np.random.default_rng(20261003+ci*10000+si)
            nsamples=0;quality_history=[]
            for d in decs:
                now=utc(d["start_utc"])
                while cursor<len(resync) and utc(resync[cursor]["issued_at_utc"])<=now:
                    m=resync[cursor];w=m["invalidated_window"]
                    invalid.update(range(w["action_index_start"],w["action_index_end_exclusive"]))
                    # Published state_resync best_scores are the authoritative past.
                    curbest.fill(0)
                    for b in m.get("best_scores",[]):curbest[cat.index[b["target_id"]]]=float(b["best_score"])
                    currawfactor.fill(0)
                    for past_a,i,s,f,start,end in history:
                        if past_a not in invalid:currawfactor[i]=max(currawfactor[i],f)
                    cursor+=1
                if d["action"]!="observe":continue
                a=int(d["observe_index"])
                if a%every==0:
                    t=int(np.clip(np.searchsorted(cat.stamps,now.timestamp(),side="right")-1,0,len(cat.times)-1))
                    lower=np.minimum(1,curbest/(cat.weight*1.2))
                    required_ix=np.flatnonzero(cat.req)
                    req_take=min(sample//3,len(required_ix))
                    ix=np.unique(np.concatenate([rng.choice(len(cat.ids),sample-req_take,replace=False),
                        rng.choice(required_ix,req_take,replace=False)]))
                    x=cat.features(t,lower,curbest,ix)
                    member=np.zeros(len(ix),np.float32);reward=np.zeros(len(ix),np.float32);hours=np.zeros(len(ix),np.float32)
                    for issue,deadline,r in reqdata:
                        if not issue<=now<deadline:continue
                        ids=set(r["target_ids"]);remain=max(1,int(r["minimum_completed"]))
                        # Membership/deadline/reward are published when issued. No
                        # raw future completion is used to construct these inputs.
                        m=np.array([cat.ids[i] in ids for i in ix]);member[m]=1
                        reward[m]=float(r["completion_reward"])/remain/100
                        hours[m]=np.log1p((deadline-now).total_seconds()/3600)/np.log(73)
                    q=float(np.median(quality_history[-8:])) if quality_history else .8
                    x=np.column_stack([x,member,reward,hours,np.full(len(ix),q)]).astype(np.float32)
                    # Terminal labels use valid scorer factors and scores after ALL
                    # real events/loss. Residual science may be negative after loss.
                    complete=(finalfactor[ix]>=.5).astype(np.float32)
                    science=(finalbest[ix]-curbest[ix])/(cat.weight[ix]*1.2)
                    y=np.column_stack([complete,np.clip(science,-1,1)]).astype(np.float32)
                    xx.append(x);yy.append(y);cc.append(np.full(len(ix),ci,np.int8));nsamples+=len(ix)
                    done=lower>=.5;bd=np.bincount(cat.band,weights=done,minlength=36)
                    ratios=np.divide(bd,cat.bandtot,out=np.zeros(36),where=cat.bandtot>0)
                    active=cat.bandtot>0;b=(ratios[active]**2).sum();s=ratios[active].sum()
                    j=s*s/(active.sum()*b) if b else 0
                    # Raw prefix factors are used only in the GLOBAL RETURN LABEL.
                    # This equals scoring the history at this moment, including any
                    # already completed issued request and public report settlement.
                    current_terminal=cat.terminal(currawfactor,curbest)
                    current_terminal+=sum(float(m.get("score_delta",0)) for m in report_results
                        if utc(m["issued_at_utc"])<=now)
                    for issue,deadline,r in reqdata:
                        if issue>now:continue
                        reqfactor={}
                        for past_a,i,s,f,start,end in history:
                            if past_a not in invalid and issue<=start and end<=deadline:
                                reqfactor[cat.ids[i]]=max(reqfactor.get(cat.ids[i],0),f)
                        if sum(reqfactor.get(sid,0)>=float(r["completion_factor_threshold"])
                               for sid in r["target_ids"])>=int(r["minimum_completed"]):
                            current_terminal+=float(r["completion_reward"])
                    gx.append(np.concatenate([[t/len(cat.times),curbest.sum()/1e4,done.mean(),
                        (cat.req&~done).sum()/max(1,cat.req.sum()),j,q,len(reqdata)/10],ratios]).astype(np.float32))
                    gy.append(float(report["total"])-current_terminal);gc.append(ci)
                    gs.append(len(meta));ga.append(a);gt.append(now.timestamp())
                observations=by_action.get(a,[])
                for i,s,f in observations:
                    curbest[i]=max(curbest[i],s);currawfactor[i]=max(currawfactor[i],f)
                    history.append((a,i,s,f,utc(d["start_utc"]),utc(d["end_utc"])))
                # Score-only lower quality from unsaturated hits (public feedback).
                duration=float(d["duration_seconds"])
                qvals=[s/(cat.weight[i]*1.2)*.5*900/(cat.flux[i]*duration)
                       for i,s,_ in observations if 0<s<cat.weight[i]*1.2*.95]
                if qvals:quality_history.append(float(np.clip(np.median(qvals),0,3)))
            item={"card":card,"path":str(src),"official_total":report["total"],"samples":nsamples,
                  "source_sha256":{p:sha(src/p) for p in ["observations.csv","decisions.csv","messages.jsonl","score_report.json"]},
                  "science_sum_recomputed":float(finalbest.sum()),"score_report_science_sum":report["components"]["sum_best_scores"],
                  "required_missing_recomputed":int((cat.req&(finalfactor<.5)).sum()),
                  "score_report_required_missing":report["counts"]["required_missing"]}
            meta.append(item);print(json.dumps({k:item[k] for k in ["card","path","official_total","samples"]}),flush=True)
    if not xx:raise ValueError("no eligible public local trajectories")
    np.savez_compressed(TOUT/"samples.npz",x=np.concatenate(xx),y=np.concatenate(yy),card=np.concatenate(cc),
        global_x=np.stack(gx),global_y=np.array(gy,np.float32),global_card=np.array(gc,np.int8),
        global_source=np.array(gs,np.int16),global_observe_index=np.array(ga,np.int32),global_now=np.array(gt,np.float64))
    manifest={"utc":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),"seconds":time.monotonic()-begin,
        "samples":sum(len(x) for x in xx),"global_samples":len(gx),"features":FEATURES,"sources":meta,
        "split":{"training":["L1","L2"],"validation":["L3"],"heldout":["L4"]},
        "labels":"official valid terminal target completion, signed remaining best science; official final total minus prefix settlement reconstructed from rounded valid records",
        "causal_limit":"behavior-policy continuation only; no do(skip-target) or action-advantage identification; histories correlated",
        "current_input_safety":"raw factors/final validity are endpoint labels only; current factors from score/(weight*1.2); resync applied only after publication"}
    (TOUT/"manifest.json").write_text(json.dumps(manifest,indent=2))

def train(epochs=30):
    import torch
    torch.set_num_threads(2);torch.manual_seed(20261003)
    d=np.load(TOUT/"samples.npz");x,y,c=d["x"],d["y"],d["card"];train=c<2;val=c==2
    mean=x[train].mean(0);std=np.maximum(x[train].std(0),.05)
    xt=torch.from_numpy((x[train]-mean)/std);yt=torch.from_numpy(y[train])
    xv=torch.from_numpy((x[val]-mean)/std);yv=torch.from_numpy(y[val])
    net=torch.nn.Sequential(torch.nn.Linear(len(FEATURES),64),torch.nn.ReLU(),torch.nn.Linear(64,48),
        torch.nn.ReLU(),torch.nn.Linear(48,2));optim=torch.optim.AdamW(net.parameters(),lr=.0015)
    history=[];begin=time.monotonic()
    for e in range(epochs):
        perm=torch.randperm(len(xt));losses=[]
        for start in range(0,len(xt),4096):
            ix=perm[start:start+4096];z=net(xt[ix]);loss=torch.nn.functional.binary_cross_entropy_with_logits(z[:,0],yt[ix,0])+\
                torch.nn.functional.smooth_l1_loss(torch.tanh(z[:,1]),yt[ix,1])
            optim.zero_grad();loss.backward();optim.step();losses.append(float(loss.detach()))
        with torch.no_grad():
            z=net(xv);p=torch.sigmoid(z[:,0]);r=torch.tanh(z[:,1]);m=x[val,3]<.5;req=m&(x[val,2]>.5)
            item={"epoch":e+1,"train_loss":float(np.mean(losses)),"brier":float(((p-yv[:,0])**2).mean()),
                "science_mse":float(((r-yv[:,1])**2).mean()),"unfinished_brier":float(((p[m]-yv[m,0])**2).mean()),
                "unfinished_required_brier":float(((p[req]-yv[req,0])**2).mean()),
                "unfinished_science_mse":float(((r[m]-yv[m,1])**2).mean())}
            history.append(item);print(json.dumps(item),flush=True)
    weights={"mean":mean,"std":std}
    for i,layer in enumerate([net[0],net[2],net[4]]):weights[f"w{i}"]=layer.weight.detach().numpy();weights[f"b{i}"]=layer.bias.detach().numpy()
    np.savez_compressed(TOUT/"model.npz",**weights)
    (TOUT/"training.json").write_text(json.dumps({"parameters":sum(p.numel() for p in net.parameters()),
        "seconds":time.monotonic()-begin,"train_samples":int(train.sum()),"validation_samples":int(val.sum()),
        "science_output":"tanh, signed residual normalized by weight*1.2","history":history},indent=2))

def main():
    ap=argparse.ArgumentParser();ap.add_argument("command",choices=["generate","train","all"])
    ap.add_argument("--every",type=int,default=2);ap.add_argument("--sample",type=int,default=192)
    ap.add_argument("--epochs",type=int,default=30);a=ap.parse_args()
    if a.command in ["generate","all"]:generate(a.every,a.sample)
    if a.command in ["train","all"]:train(a.epochs)

if __name__=="__main__":main()
