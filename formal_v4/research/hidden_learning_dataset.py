"""Exact terminal counterfactual labels for public-input candidate-action learning.

Teacher: replace one source exposure with a public candidate, delete overlapping
source exposures and preserve later absolute starts/reports. This measures actual
terminal-score time opportunity cost conditional on a fixed continuation tape.
It does not identify the optimum continuation or the online causal effect after
replanning. All local truth is confined to labels and scalar scorer audits.
"""
from __future__ import annotations
import argparse,bisect,csv,hashlib,json,os,pickle,shutil,sys,time
from datetime import timedelta,datetime,timezone
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"results/hidden_learning_20261003"
UP=ROOT/"upstream/gosim-observer-examples"
sys.path[:0]=[str(ROOT),str(ROOT/"research"),str(UP/"runner")]
from challenge.v4_runner import load_scenario,run_scenario,_data_loss_plan
from challenge.v4_workflow import V4Workflow
from challenge.v4_fiber_map import min_altitude_during
from research.hidden_learning_policy import CandidateCriticPlanner,FEATURES
from research.feedback_model import seasonal_quality
from research.geometry import format_utc,local_sidereal_deg
from cold_evolutionary_season import StressOracle
from cold_global_incumbent import replay_plan
import policy

SOURCES={c:ROOT/"runs/cpu_calendar_witness_20261003"/c for c in ("L1","L2","L3")}
def utc(x):return datetime.fromisoformat(x.replace("Z","+00:00")).astimezone(timezone.utc)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2,sort_keys=True)+"\n")

class Terminal:
    def __init__(self,s,rows,report):
        self.s=s;self.n=len(s.targets);self.rows=rows;self.report=report
        self.ids=np.array([c["ids"] for c in rows]);self.g=np.array([c["g"] for c in rows]);self.scores=np.array([c["scores"] for c in rows]);self.bits=np.array([c["bits"] for c in rows],np.int64)
        self.start=np.array([c["start"] for c in rows],np.int64);self.end=np.array([c["end"] for c in rows],np.int64)
        self.loss=_data_loss_plan(s);self.req=np.array([t["required"] for t in s.targets]+[False])
        b=np.array([int(t["ra_deg"]//s.score_config["uniformity"]["ra_band_width_deg"]) for t in s.targets]);_,self.band,self.count=np.unique(b,return_inverse=True,return_counts=True)
    def objective(self,keep,candidate=None):
        ix=np.asarray(keep,int)
        start=self.start[ix];ids=self.ids[ix];g=self.g[ix];scores=self.scores[ix];bits=self.bits[ix]
        if candidate is not None:
            start=np.r_[start,candidate["start"]];ids=np.vstack([ids,candidate["ids"]]);g=np.vstack([g,candidate["g"]]);scores=np.vstack([scores,candidate["scores"]]);bits=np.vstack([bits,candidate["bits"]])
        order=np.argsort(start,kind="stable")
        if self.loss:
            n=int((start<self.loss.trigger_utc.timestamp()).sum());lo=int(np.floor(self.loss.window_start_fraction*n));hi=int(np.floor(self.loss.window_end_fraction*n))
            order=np.r_[order[:lo],order[hi:]]
        best=np.zeros(self.n+1);factor=np.zeros(self.n+1)
        np.maximum.at(best,ids[order].ravel(),scores[order].ravel());np.maximum.at(factor,ids[order].ravel(),g[order].ravel())
        rb=np.bitwise_or.reduce(bits[order],axis=0) if len(order) else np.zeros(len(self.s.observation_requests),np.int64)
        reward=sum(r["completion_reward"] for r,b in zip(self.s.observation_requests,rb) if int(b).bit_count()>=r["minimum_completed"])
        cfg=self.s.score_config;missing=int((self.req&(factor<cfg["required"]["observed_factor_threshold"])).sum())
        ratios=np.bincount(self.band,weights=factor[:self.n]>=cfg["uniformity"]["observed_factor_threshold"])/self.count;den=ratios@ratios
        jain=ratios.sum()**2/(len(ratios)*den) if den else 0
        uniform=cfg["uniformity"]["weight"]*(1-jain)
        return dict(total=float(best.sum()-cfg["required"]["penalty_per_missing"]*missing-uniform+reward+self.report),science=float(best.sum()),required_missing=missing,request_reward=reward,uniformity_penalty=float(uniform))

def fast_row(o,start,end,action):
    # Geometry and continuous exposure altitude are scalar exact. Integration uses
    # Oracle's verified official <=120-second mesh, vectorized over selected IDs.
    a={**action,"assignments":dict(action["assignments"])}
    for f,tid in list(a["assignments"].items()):
        t=o.s.targets[o.idxs[tid]]
        hit=o.grid.classify_target(t["ra_deg"],t["dec_deg"],start,a["pointing"]["alt_deg"],a["pointing"]["az_deg"],o.lat,o.lon,*o.offset)
        if hit.region!="glass" or hit.fiber_id!=int(f) or min_altitude_during(t["ra_deg"],t["dec_deg"],start,end,o.s.config)<o.s.minimum_altitude_deg:del a["assignments"][f]
    if not a["assignments"]:
        z=np.full(16,o.n,np.int32);return {"start":int(start.timestamp()),"end":int(end.timestamp()),"ids":z,"g":np.zeros(16),"scores":np.zeros(16),"bits":[0]*len(o.request_ids),"action":action}
    row=o.row(start,end,a,False);row["action"]=action;return row

def frozen_source():
    target=OUT/"frozen_project";target.mkdir(parents=True,exist_ok=True);hashes={}
    paths=list(ROOT.glob("*.py"))+list((ROOT/"research").glob("*.py"))
    paths += [p for p in (UP/"python").rglob("*.py") if "__pycache__" not in p.parts]
    for p in paths:
        rel=p.relative_to(ROOT);d=target/rel;d.parent.mkdir(parents=True,exist_ok=True);d.write_bytes(p.read_bytes());hashes[str(rel)]=sha(d)
    (target/"policy_config.json").write_text("{}\n");hashes["policy_config.json"]=sha(target/"policy_config.json")
    dump(OUT/"source_manifest.json",dict(frozen_at_utc=format_utc(datetime.now(timezone.utc)),files_sha256=hashes,source_project=str(target),remote_or_credentials_included=False,engine_sha256={str(p.relative_to(UP)):sha(p) for p in (UP/"runner/challenge").glob("*.py")}))
    return target

def generate_card(card,every=18,maxstates=70):
    ci=("L1","L2","L3").index(card);src=SOURCES[card];sp=UP/"local-cards"/card/"config/v4_scenario.json";s=load_scenario(sp)
    dec=list(csv.DictReader((src/"decisions.csv").open()));observe_dec=[r for r in dec if r["action"]=="observe"]
    actions=[json.loads(l) for l in (src/"actions.jsonl").read_text().splitlines() if l.strip()];observe=[a for a in actions if a["action"]=="observe"]
    reports=[utc(r["start_utc"]) for r in dec if r["action"]=="report"]
    o=StressOracle(s,reports);raw=[]
    for r,a in zip(observe_dec,observe):raw.append(fast_row(o,utc(r["start_utc"]),utc(r["end_utc"]),a))
    terminal=Terminal(s,raw,o.report_settlement);baseline=terminal.objective(range(len(raw)));expected=json.loads((src/"score_report.json").read_text())
    if abs(baseline["total"]-expected["total"])>1e-5:raise RuntimeError(f"source gate {card}: {baseline} vs {expected['total']}")
    initial=V4Workflow(UP/"local-cards"/card).initialize_payload(900)
    policy.SpatialPlanner=CandidateCriticPlanner;p=policy.Policy(initial)
    if p.remote:raise RuntimeError("teacher source must not use remote runtime")
    p.config.update(planning_budget_seconds=30.,anchor_count=24)
    groups=[];xx=[];yy=[];dd=[];cc=[];gg=[];saved=[];audit=[];idx=0;started=time.monotonic()
    action_by_time={utc(r["start_utc"]):a for r,a in zip(observe_dec,observe)};report_set=set(reports);reported=set();times=sorted(set(action_by_time)|report_set)
    selected=set(range(0,len(raw),every));selected=set(sorted(selected)[:maxstates])
    def agent(snapshot):
        nonlocal idx
        now=utc(snapshot["now_utc"]);p._ingest_result(snapshot);p._messages(snapshot)
        if now in report_set and now not in reported:
            reported.add(now);p.pending={"action":{"action":"report"}};return {"action":"report"}
        a=action_by_time.get(now)
        if a is None:
            nxt=bisect.bisect_right(times,now)
            return {"action":"wait","until_utc":format_utc(times[nxt] if nxt<len(times) else s.survey_end)}
        ni=p._night(now);C,_=seasonal_quality(now.timetuple().tm_yday,p.planner.q0)
        C,E=p.belief_clock.prior(p.C,p.E,now,C);p.last_night=ni
        env=dict(p.config);env.update(quality_scale=C*E*p.planner.q0,program_band_quality_scale=C*p.planner.q0,target_quality_scale=p._target_scale(now),use_bulletin_directional_prior=False)
        if p.calibrator:
            est=p.calibrator.estimate;env.update(pointing_offset_alt_deg=est[0],pointing_offset_az_deg=est[1])
        if idx in selected:
            planner=p.planner;planner.choose(snapshot,p.scores,p.factor_lower,env,snapshot.get("active_requests",[]));pool=list(planner.candidates);features=list(planner.feature_matrix)
            # Include the actual trace baseline with zero label, even if its
            # runtime-stopped candidate is outside the current top32 pool.
            if not any(z[2]==a for z in pool) and pool:
                args=planner._critic_eval_args;k=args[3];sc=args[4];fac=args[5];mult=args[6];req=args[7];ur=args[12]
                ii=np.array([planner.index[t] for t in a["assignments"].values()],int);ff=np.array([int(f) for f in a["assignments"]],int);dur=a["duration_seconds"];prog=("DARK","BRIGHT","BACKUP").index(a["program"])
                rawpred=np.minimum(1,k[ii]*dur);rd=req[ii]&(rawpred/args[14]>=.5)
                rate=float(((np.maximum(0,planner.weight[ii]*rawpred*mult[prog,ii]-sc[ii])+rd*50)*ur[ii]).sum()/dur)
                center=(a["pointing"]["alt_deg"]+env.get("pointing_offset_alt_deg",0),(a["pointing"]["az_deg"]+env.get("pointing_offset_az_deg",0))%360)
                c=(rate,center,dur,prog,ii,ff);x=planner._features(c,args);best=pool[0][0][0]
                pool.append((c,x,a));features.append(np.r_[x,best*100,rate/max(best,1e-12),pool[0][0][2]/planner.tmax].astype(np.float32))
            state_group=ci*100000+idx;count=0
            for j,(z,x) in enumerate(zip(pool,features)):
                cand=z[2];end=now+timedelta(seconds=cand["duration_seconds"])
                if end>p.planner.nights[ni][1]:continue
                if any(now<t<end for t in reports):continue
                row=fast_row(o,now,end,cand)
                keep=np.flatnonzero((terminal.end<=int(now.timestamp()))|(terminal.start>=int(end.timestamp())))
                cf=terminal.objective(keep,row);delta=cf["total"]-baseline["total"]
                xx.append(x);yy.append(delta/cand["duration_seconds"]);dd.append(cand["duration_seconds"]);cc.append(ci);gg.append(state_group);count+=1
                if len(saved)<3 and j==min(4,len(pool)-1):saved.append(dict(group=state_group,now=format_utc(now),action=cand,row=row,keep=keep,expected=cf))
            groups.append(dict(group=state_group,observe_index=idx,now_utc=format_utc(now),candidates=count,baseline_action=a,scores_sum=float(p.scores.sum()),factor_lower_missing=int((p.planner.required&(p.factor_lower<.5)).sum())))
            if len(groups)%10==0:print(json.dumps(dict(card=card,groups=len(groups),pairs=len(xx),seconds=time.monotonic()-started)),flush=True)
        alt,az,_,_=p.planner._altaz(local_sidereal_deg(now,p.planner.lon));pred={tid:{"alt_deg":float(alt[p.planner.index[tid]]),"az_deg":float(az[p.planner.index[tid]])} for tid in a["assignments"].values()}
        p.pending={"action":a,"start":now,"prediction":pred,"notices":list(p.notices),"prior_C":C,"prior_E":E};idx+=1
        return a
    replay=run_scenario(sp,lambda _:agent,OUT/f"teacher_replay_{card}")
    if replay["total"]!=expected["total"]:raise RuntimeError(f"source replay gate {card}: {replay['total']} != {expected['total']}")
    for j,z in enumerate(saved):
        native=o.row(utc(z["now"]),utc(z["now"])+timedelta(seconds=z["action"]["duration_seconds"]),z["action"],True)
        err=max(float(np.max(np.abs(native["g"]-z["row"]["g"]))),float(np.max(np.abs(native["scores"]-z["row"]["scores"]))))
        plan=[{**raw[int(i)]["action"],"start_utc":format_utc(datetime.fromtimestamp(raw[int(i)]["start"],timezone.utc))} for i in z["keep"]]+[{**z["action"],"start_utc":z["now"]}]
        native_report=replay_plan(sp,s,plan,reports,OUT/f"native_intervention_{card}_{j}")
        audit.append(dict(group=z["group"],column_score_max_error=err,expected=z["expected"],official_total=native_report["total"],terminal_error=abs(z["expected"]["total"]-native_report["total"])))
        if err>1e-7 or audit[-1]["terminal_error"]>1e-5:raise RuntimeError(f"counterfactual scalar gate failed {audit[-1]}")
    np.savez_compressed(OUT/f"dataset_{card}.npz",x=np.array(xx,np.float32),y=np.array(yy,np.float32),duration_seconds=np.array(dd,np.float32),card=np.array(cc,np.int8),group=np.array(gg,np.int32))
    dump(OUT/f"manifest_{card}.json",dict(card=card,features=FEATURES,source=str(src),source_sha256={n:sha(src/n) for n in ["actions.jsonl","decisions.csv","observations.csv","messages.jsonl","score_report.json"]},groups=groups,source_total=expected["total"],teacher_replay_total=replay["total"],model_source_gate=baseline,scalar_audit=audit,seconds=time.monotonic()-started))
    print(json.dumps(dict(card=card,groups=len(groups),pairs=len(xx),seconds=time.monotonic()-started,completed=True)),flush=True)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--card",choices=["L1","L2","L3"]);ap.add_argument("--every",type=int,default=18);ap.add_argument("--states",type=int,default=70);ap.add_argument("--merge",action="store_true");a=ap.parse_args();OUT.mkdir(parents=True,exist_ok=True)
    if a.merge:
        ds=[dict(np.load(OUT/f"dataset_{c}.npz")) for c in ["L1","L2","L3"]]
        np.savez_compressed(OUT/"dataset.npz",**{k:np.concatenate([d[k] for d in ds]) for k in ds[0]})
        dump(OUT/"dataset_manifest.json",dict(features=FEATURES,split={"training":["L1","L2"],"validation":["L3"],"heldout":["L4"]},label="y=(exact counterfactual terminal total - baseline terminal total)/candidate duration; raw delta=y*duration_seconds",labels_use_local_truth=True,inputs="public protocol, public geometry and past policy feedback only",limit="fixed absolute continuation with overlapped actions removed; conditional teacher, not replanning effect",card_manifests=[str(OUT/f"manifest_{c}.json") for c in ["L1","L2","L3"]],dataset_sha256=sha(OUT/"dataset.npz")))
    else:
        if not (OUT/"source_manifest.json").exists():frozen_source()
        generate_card(a.card,a.every,a.states)
if __name__=="__main__":main()
