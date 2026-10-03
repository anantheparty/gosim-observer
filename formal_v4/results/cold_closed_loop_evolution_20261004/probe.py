#!/usr/bin/env python3
"""Public-only dynamic partition evolution; small synthetic official-runner gate.

Actor never loads truth. Artificial truth is constructed by the separate harness.
Fitness is a declared midpoint surrogate, not official or season performance.
"""
from __future__ import annotations
import copy, csv, hashlib, json, math, random, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "formal_v4/upstream/gosim-observer-examples/runner"))
from challenge.v4_fiber_map import FiberGrid, radec_to_altaz, min_altitude_during
from challenge.v4_runner import run_scenario
from challenge.v4_scorer import lunar_quality_factor, uniformity_penalty, required_penalty
from challenge.tile_geometry_simulator import _normalized_airmass

def utc(x): return datetime.fromisoformat(x.replace("Z", "+00:00"))
def fmt(x): return x.strftime("%Y-%m-%dT%H:%M:%SZ")
def digest(x): return hashlib.sha256(json.dumps(x, sort_keys=True).encode()).hexdigest()

def canonical(labels):
    seen = {}; return tuple(seen.setdefault(int(v), len(seen)) for v in labels)

class State:
    def __init__(self, n):
        self.best = np.zeros(n); self.lower = np.zeros(n); self.quality = .9
        self.records = []; self.rank = 0

class PartitionActor:
    """Genome = equivalence relation on runtime target obligations, no action tape."""
    def __init__(self, public, start, mode="population", seed=271828, evaluations=32):
        self.public = public; self.ts = public["targets"]; self.site = public["site"]
        self.score = public["score"]; self.grid = FiberGrid.from_config(public["fiber"])
        self.start = start; self.mode = mode; self.rng = random.Random(seed)
        self.n = len(self.ts); self.state = State(self.n); self.ids = {t["target_id"]:i for i,t in enumerate(self.ts)}
        self.flux = np.array([t["feature_flux"] for t in self.ts]); self.w = np.array([t["science_weight"] for t in self.ts])
        self.req = np.array([t["required"] for t in self.ts]); self.evaluations = evaluations
        self.cache = {}; self.traces = []; self.pending = None
        self.work = {"decode_calls":0,"candidate_centers":0,"center_target_entries":0,"simulated_feedbacks":0}
        self.labels = self.initial_labels(); self.seed_labels = self.labels

    def initial_labels(self):
        # Current angular nearest-neighbour batches. These indices are runtime memory.
        pos=np.array([[t["ra_deg"]*math.cos(math.radians(t["dec_deg"])),t["dec_deg"]] for t in self.ts])
        left=set(range(self.n)); labels=[-1]*self.n; g=0
        while left:
            i=min(left); nearest=sorted(left,key=lambda j:(float(np.sum((pos[j]-pos[i])**2)),j))[:5]
            for j in nearest: labels[j]=g; left.remove(j)
            g+=1
        return canonical(labels)

    def public_geometry(self, seconds, duration):
        key=(seconds,duration)
        if key in self.cache:return self.cache[key]
        t=self.start+timedelta(seconds=int(seconds)); end=t+timedelta(seconds=int(duration)); mid=t+(end-t)/2
        aa=np.array([radec_to_altaz(x["ra_deg"],x["dec_deg"],t,self.site["latitude_deg"],self.site["longitude_deg"]) for x in self.ts])
        a=np.radians(aa[:,0]); z=np.radians(aa[:,1]); vec=np.stack((np.cos(a)*np.cos(z),np.cos(a)*np.sin(z),np.sin(a)),axis=1)
        ok=np.array([min_altitude_during(x["ra_deg"],x["dec_deg"],t,end,{"site":self.site})>=30 for x in self.ts])
        # Deliberately approximate model; official integration is only in evaluator.
        geom=np.array([lunar_quality_factor(x["ra_deg"],x["dec_deg"],mid,self.site,self.score)/(_normalized_airmass(radec_to_altaz(x["ra_deg"],x["dec_deg"],mid,self.site["latitude_deg"],self.site["longitude_deg"])[0])**.6) for x in self.ts])
        band=.9*.9/.8/.68*geom
        mult=np.where(band>=.65,1.2,1.0) # declared DARK
        self.cache[key]=(aa,vec,ok,geom,mult);return self.cache[key]

    def candidates(self, group, aa):
        members=np.array(group,dtype=int); p=aa[members]
        # Recomputed continuous centers, derived from this group's current sky.
        azbase=float(p[0,1]); az=azbase+((p[:,1]-azbase+180)%360-180)
        cen=(float(np.mean(p[:,0])),float(np.mean(az))%360)
        centers=[cen]
        for i in members:
            a,z=aa[i]
            for dx,dy in [(0,0),(-.948683,-.948683),(-.948683,.948683),(.948683,-.948683),(.948683,.948683)]:
                ca=float(np.clip(a-dx,0,89.5)); cz=float((z-dy/max(.08,math.cos(math.radians(ca))))%360)
                centers.append((ca,cz))
        return np.array(centers)

    def fibers(self, centers, vec):
        a=np.radians(centers[:,0]); z=np.radians(centers[:,1])
        center=np.stack((np.cos(a)*np.cos(z),np.cos(a)*np.sin(z),np.sin(a)),axis=1)
        up=np.stack((-np.sin(a)*np.cos(z),-np.sin(a)*np.sin(z),np.cos(a)),axis=1)
        right=np.stack((-np.sin(z),np.cos(z),np.zeros_like(z)),axis=1)
        # Small fixed dimension avoids local BLAS warnings on this macOS build.
        dep=np.sum(center[:,None,:]*vec[None,:,:],axis=2)
        dx=np.sum(up[:,None,:]*vec[None,:,:],axis=2)/np.maximum(1e-12,dep)*180/math.pi
        dy=np.sum(right[:,None,:]*vec[None,:,:],axis=2)/np.maximum(1e-12,dep)*180/math.pi
        half=self.grid.fov_side_deg/2; ok=(dep>0)&(np.abs(dx)<=half)&(np.abs(dy)<=half)
        row=np.clip(np.floor(dx/self.grid.pitch_deg+2),0,3).astype(int);col=np.clip(np.floor(dy/self.grid.pitch_deg+2),0,3).astype(int)
        return np.where(ok,row*4+col,-1)

    def action(self, labels, state, seconds, horizon):
        self.work["decode_calls"]+=1
        # Pruning is an operational tiny science-debt tolerance, never a proof of done.
        active=(1.2*self.w-state.best>1e-5)|(self.req&(state.lower<.5))
        groups={}
        for i,l in enumerate(labels):
            if active[i]:groups.setdefault(l,[]).append(i)
        if not groups: return None
        answer=None
        for duration in [180,360,720]:
            if duration>horizon: continue
            aa,vec,ok,geom,mult=self.public_geometry(seconds,duration)
            factor=np.minimum(self.flux*duration*(state.quality*.9*.9/.8/.68)*geom/450,1)
            score=self.w*factor*mult
            gain=np.maximum(score-state.best,0)+50*self.req*(state.lower<.5)*(factor>=.5)
            for group in groups.values():
                centers=self.candidates(group,aa); fib=self.fibers(centers,vec)
                self.work["candidate_centers"]+=len(centers)
                self.work["center_target_entries"]+=len(centers)*self.n
                # Actual concurrency constraint: every live block member must land
                # on glass, above altitude, in a DIFFERENT fiber. This changes the
                # feasible action family rather than only adding centroid proposals.
                mandatory=np.zeros(len(centers),bool)
                if len(group)<=16 and np.all(ok[group]):
                    for ci in range(len(centers)):
                        cells=fib[ci,group]
                        mandatory[ci]=np.all(cells>=0) and len(set(cells.tolist()))==len(group)
                if not np.any(mandatory):continue
                val=np.where(ok&active,gain,0); picks=np.full((len(centers),16),-1,int)
                totals=np.zeros(len(centers))
                for f in range(16):
                    values=np.where(fib==f,val[None,:],-1);idx=np.argmax(values,axis=1);v=values[np.arange(len(centers)),idx]
                    picks[:,f]=np.where(v>0,idx,-1);totals+=np.maximum(v,0)
                # Occupy each mandatory fiber before opportunistic assignments.
                for ci in np.flatnonzero(mandatory):
                    for target in group:
                        f=int(fib[ci,target]);previous=int(picks[ci,f])
                        if previous>=0:totals[ci]-=val[previous]
                        picks[ci,f]=target;totals[ci]+=val[target]
                totals=np.where(mandatory,totals,-1)
                j=int(np.argmax(totals)); utility=float(totals[j])/duration
                key=(utility,float(totals[j]),-duration,tuple(-x for x in centers[j]))
                if answer is None or key>answer[0]:
                    selected=picks[j]; ids=selected[selected>=0].tolist()
                    action={"action":"observe","pointing":{"alt_deg":float(centers[j,0]),"az_deg":float(centers[j,1])},"assignments":{str(f):self.ts[i]["target_id"] for f,i in enumerate(selected) if i>=0},"duration_seconds":duration,"program":"DARK"}
                    answer=(key,action,ids,factor,score,tuple(group))
        return answer

    def feed(self,state,ids,scores,seconds,duration):
        _,_,_,geom,mult=self.public_geometry(seconds,duration); ratios=[]
        for i,s in zip(ids,scores):
            state.best[i]=max(state.best[i],s)
            # Safe public bound includes 6-decimal score rounding and any legal m.
            state.lower[i]=max(state.lower[i],max(0,s-0.5e-6)/(1.2*self.w[i]))
            if 0<s<self.w[i]-1e-6:
                ratios.append(s/(1.2*self.w[i])/(self.flux[i]*duration*(.9*.9/.8/.68)*geom[i]/450))
        if ratios:state.quality=float(np.clip(np.median(ratios),.05,1.2))
        state.rank+=1

    def fitness(self,labels,initial,seconds,horizon):
        # Shared synthetic belief scenarios, separate state and genuine feedback
        # adaptation on each branch. No future observations from real cards.
        values=[]
        # Future scenario levels are conditioned on the public quality estimate.
        for efficiency in [max(.05,.6*initial.quality),min(1.2,1.2*initial.quality)]:
            st=copy.deepcopy(initial); elapsed=0
            max_factor=np.array(initial.lower)
            for step in range(4):
                decoded=self.action(labels,st,seconds+elapsed,horizon-elapsed)
                if decoded is None:break
                _,a,ids,fac,sc,batch=decoded; d=a["duration_seconds"]
                _,_,_,geom,mult=self.public_geometry(seconds+elapsed,d)
                truefac=np.minimum(self.flux*d*(efficiency*.9*.9/.8/.68)*geom/450,1)
                max_factor[ids]=np.maximum(max_factor[ids],truefac[ids])
                self.feed(st,ids,(self.w*truefac*mult)[ids],seconds+elapsed,d)
                self.work["simulated_feedbacks"]+=1
                elapsed+=d
                if elapsed>=horizon:break
            factors={x["target_id"]:float(max_factor[i]) for i,x in enumerate(self.ts)}
            _,reqcost=required_penalty(self.ts,factors,self.score)
            _,jaincost=uniformity_penalty(self.ts,factors,self.score)
            values.append(float(np.sum(st.best)-reqcost-jaincost))
        return sum(values)/len(values)

    def mutate(self,labels):
        l=list(labels); op=self.rng.randrange(3)
        if op==0: # exchange membership, changing concurrency edges
            i,j=self.rng.sample(range(self.n),2);l[i],l[j]=l[j],l[i]
        elif op==1: # split one target from a block
            l[self.rng.randrange(self.n)]=max(l)+1
        else: # merge two blocks
            a,b=self.rng.sample(range(self.n),2);x,y=l[a],l[b];l=[x if z==y else z for z in l]
        return canonical(l)

    def cross(self,a,b):
        # Copy one entire equivalence block; remove those members from all other
        # blocks, preserving partition legality (no overlapping membership).
        block=self.rng.choice(sorted(set(b))); take={i for i,x in enumerate(b) if x==block}
        l=list(a);new=max(l)+1
        for i in take:l[i]=new
        return canonical(l)

    def evolve(self,seconds,horizon):
        seen={}; attempts=0; population=[self.labels,self.seed_labels]
        while len(seen)<self.evaluations and attempts<self.evaluations*10:
            attempts+=1
            if not seen: child=population[0]
            elif self.mode=="single": child=self.mutate(max(seen,key=lambda l:seen[l]))
            elif len(seen)<4:child=self.mutate(self.seed_labels)
            else:
                elite=sorted(seen,key=lambda l:(seen[l],l),reverse=True)[:4]
                child=self.mutate(self.cross(self.rng.choice(elite),self.rng.choice(elite)))
            if child in seen:continue
            seen[child]=self.fitness(child,self.state,seconds,horizon)
        self.labels=max(seen,key=lambda l:(seen[l],l))
        decoded=self.action(self.labels,self.state,seconds,horizon)
        self.traces.append({"seconds":seconds,"quality":self.state.quality,"group_count":len(set(self.labels)),"partition_sha":digest(self.labels),"evaluations":len(seen),"surrogate":seen[self.labels],"action_sha":digest(decoded[1]) if decoded else None,"mandatory_batch":list(decoded[5]) if decoded else [],"work":dict(self.work)})
        return decoded

    def __call__(self,snapshot):
        now=utc(snapshot["now_utc"]); sec=int((now-self.start).total_seconds())
        result=snapshot.get("last_result")
        if result and result.get("action")=="observe" and self.pending:
            oldsec,d=self.pending
            ids=[self.ids[x["target_id"]] for x in result["hits"]];scores=[x["score"] for x in result["hits"]]
            self.feed(self.state,ids,scores,oldsec,d);self.pending=None
        horizon=int((utc(snapshot["survey_end_utc"])-now).total_seconds())
        decoded=self.evolve(sec,horizon)
        if decoded is None:return {"action":"wait","duration_seconds":max(60,min(3600,horizon))}
        action=decoded[1]; self.pending=(sec,action["duration_seconds"]);return action

def choose_public_domain(card):
    base=ROOT/"formal_v4/upstream/gosim-observer-examples/local-cards"/card
    fiber=json.loads((base/"config/v4_fiber_config.json").read_text());score=json.loads((base/"config/v4_score_config.json").read_text())
    rows=list(csv.DictReader((base/"public/targets.csv").open()));night=next(csv.DictReader((base/"public/v4_night_calendar.csv").open()))
    start=utc(night["observing_start_utc"])+timedelta(seconds=3600)
    targets=[{"target_id":x["target_id"],"ra_deg":float(x["ra_deg"]),"dec_deg":float(x["dec_deg"]),"feature_flux":float(x["feature_flux"]),"science_weight":float(x["science_weight"]),"target_class":x["target_class"],"required":x["required"]=="true"} for x in rows]
    eligible=[t for t in targets if min_altitude_during(t["ra_deg"],t["dec_deg"],start,start+timedelta(seconds=1440),{"site":fiber["site"]})>=45]
    # Stable public selection: densest 2.5-deg neighbourhood of the first 40
    # visible required anchors, then nearest 28. No outcome-based selection.
    anchors=[t for t in eligible if t["required"]][:40] or eligible[:40]
    def dist(a,b):return (((a["ra_deg"]-b["ra_deg"]+180)%360-180)*math.cos(math.radians(a["dec_deg"])))**2+(a["dec_deg"]-b["dec_deg"])**2
    anchor=max(anchors,key=lambda a:(sum(dist(a,b)<6.25 for b in eligible),a["target_id"]))
    selected=sorted(eligible,key=lambda t:(dist(anchor,t),t["target_id"]))[:28]
    return {"targets":selected,"site":fiber["site"],"fiber":fiber,"score":score},start

def writecsv(path,rows,fields):
    with path.open("w") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def artificial_bundle(public,start,efficiency,name):
    base=OUT/name;base.mkdir(exist_ok=True);end=start+timedelta(seconds=1440)
    (base/"fiber.json").write_text(json.dumps(public["fiber"]));(base/"score.json").write_text(json.dumps(public["score"]))
    rows=[dict(t,required=str(t["required"]).lower()) for t in public["targets"]]
    writecsv(base/"targets.csv",rows,list(rows[0]));writecsv(base/"footprint.csv",[],["component_id","vertex_index","ra_deg","dec_deg"])
    slots=[{"slot_id":f"N-S{i+1:03d}","night_id":"N","timestamp_utc":fmt(start+timedelta(seconds=i*180)),"duration_seconds":180} for i in range(8)]
    writecsv(base/"slots.csv",slots,list(slots[0]));weather=[{"slot_id":x["slot_id"],"is_observable":"true","seeing_arcsec":.8,"transparency":.9,"sky_quality":.9,"instrument_efficiency":efficiency} for x in slots]
    writecsv(base/"weather.csv",weather,list(weather[0]));events=["event_id","event_type","actual_start_utc","actual_end_utc","scope_type","azimuth_start_deg","azimuth_end_deg","min_altitude_deg","max_altitude_deg","seeing_multiplier","transparency_multiplier","sky_quality_multiplier","instrument_efficiency_multiplier","force_close"]
    writecsv(base/"events.csv",[],events)
    cfg={"schema_version":"v4-scenario-v1","name":name,"site":public["site"],"minimum_altitude_deg":30,"fiber_config":"fiber.json","score_config":"score.json","products":{"targets_csv":"targets.csv","footprint_csv":"footprint.csv","slots_csv":"slots.csv","weather_truth_csv":"weather.csv","events_csv":"events.csv","bulletins_jsonl":"bulletins.jsonl","forecasts_jsonl":"forecasts.jsonl"},"stress":{"enabled":False}}
    (base/"scenario.json").write_text(json.dumps(cfg));return base/"scenario.json"

def main():
    started=time.monotonic(); results=[]
    for card in ["L1","L2"]:
        public,start=choose_public_domain(card)
        (OUT/f"{card}_public_domain.json").write_text(json.dumps({"start":fmt(start),"public":public},indent=2))
        for mode in ["population","single"]:
            for world,eff in [("high",1.0),("low",.4)]:
                name=f"{card}_{mode}_{world}";scenario=artificial_bundle(public,start,eff,name)
                actor=PartitionActor(public,start,mode);t=time.monotonic()
                report=run_scenario(scenario,lambda context:actor,OUT/name/"replay")
                result={"card":card,"mode":mode,"world":world,"efficiency":eff,"seconds":time.monotonic()-t,"report":report,"trace":actor.traces}
                results.append(result)
                (OUT/name/"result.json").write_text(json.dumps(result,indent=2))
                print(name,report["total"],flush=True)
    summary={"kind":"PUBLIC_CATALOG_SYNTHETIC_WEATHER_MICRO_ONLY","results":results,"elapsed_seconds":time.monotonic()-started}
    (OUT/"summary.json").write_text(json.dumps(summary,indent=2))
    print("elapsed",summary["elapsed_seconds"])
if __name__=="__main__":main()
