#!/usr/bin/env python3
"""Continuous-second LNS seeded by an unmodified production local-card replay.

Only L1/L2 (without retrospective loss/pointing offset) are supported in this
initial implementation. Every original observe action is an available column,
including every short exposure. The original report policy is held fixed at its
recorded times. Alternative columns use the official scorer and geometry; local
truth is an explicitly labelled oracle. This is NOT an online competition policy.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import os
import pickle
import time
from datetime import datetime,timedelta,timezone
from pathlib import Path

import numpy as np
import cold_global_search as m
from challenge.v4_scorer import WeatherTruth,score_target_exposure,lunar_quality_factor,program_band,program_multiplier
from challenge.v4_fiber_map import FiberGrid,radec_to_altaz,min_altitude_during


def utc(s):return datetime.fromisoformat(s.replace("Z","+00:00"))


class Oracle:
    def __init__(self,s,report_times):
        self.s=s;self.cfg=s.score_config;self.n=len(s.targets);self.grid=FiberGrid.from_config(s.fiber_config)
        self.lat=s.site["latitude_deg"];self.lon=s.site["longitude_deg"]
        self.ra=np.array([t["ra_deg"] for t in s.targets]);self.dec=np.array([t["dec_deg"] for t in s.targets]);self.vec=m.xyz(self.ra,self.dec)
        self.flux=np.array([t["feature_flux"] for t in s.targets]);self.weight=np.array([t["science_weight"] for t in s.targets]);self.required=np.array([t["required"] for t in s.targets])
        self.idxs={t["target_id"]:i for i,t in enumerate(s.targets)}
        self.weather=WeatherTruth(s.slots,[e for e in s.events if e.event_type=="instrument_fault"])
        self.report_settlement=sum(self.weather.report_fault(t,self.cfg) for t in report_times)
        self.report_times=report_times
        self.directional=[e for e in s.events if e.scope_type=="HORIZON_SECTOR"]
        self.slot_starts=[x.start_utc for x in s.slots]
        self.request_ids=[[self.idxs[t] for t in r["target_ids"]] for r in s.observation_requests]
        self.neighbors=m.radius_neighbors(self.vec,2*math.sin(math.radians(3)/2))
        self.reference_airmass=1/(1+.50572*96.07995**-1.6364)

    def qualities(self,start,end,idx):
        """Exact official mesh, vectorized over just a field's neighboring targets."""
        ra=self.ra[idx];dec=self.dec[idx];vec=self.vec[idx];length=(end-start).total_seconds()
        total=np.zeros(len(idx));btotal=np.zeros(len(idx));events=[e for e in self.directional if e.overlaps(start,end)]
        cursor=start
        for seconds,truth in self.weather.segments(start,end):
            segment_end=cursor+timedelta(seconds=seconds)
            for is_band in (False,True):
                cuts={cursor,segment_end}
                if not is_band:
                    for e in events:
                        if cursor<e.actual_start_utc<segment_end:cuts.add(e.actual_start_utc)
                        if cursor<e.actual_end_utc<segment_end:cuts.add(e.actual_end_utc)
                boundaries=sorted(cuts)
                for a,b in zip(boundaries,boundaries[1:]):
                    while a<b:
                        c=min(b,a+timedelta(seconds=120));moment=a+(c-a)/2
                        if truth is not None and truth.is_observable:
                            alt,az=m.altaz(ra,dec,moment,self.lat,self.lon)
                            z=90-np.maximum(alt,.01)
                            mass=1/(np.cos(np.deg2rad(z))+.50572*(96.07995-z)**-1.6364)/self.reference_airmass
                            mr,md,illum,ma=m._lunar_geometry(moment,self.lat,self.lon)
                            moon=m.xyz(np.array([mr]),np.array([md]))[0]
                            sep=np.rad2deg(np.arccos(np.clip((vec*moon).sum(axis=1),-1,1)))
                            lm=self.cfg["lunar_model"]
                            lum=1-lm["maximum_penalty"]*illum*math.sin(math.radians(max(0,ma)))**lm["altitude_exponent"]*np.exp(-sep/lm["angular_decay_scale_deg"])
                            val=(c-a).total_seconds()*truth.transparency*truth.sky_quality*lum/truth.seeing_arcsec/mass**self.cfg["airmass_exponent"]
                            if not is_band:
                                val*=self.weather._apply_fault(truth,moment)
                                for e in events:
                                    if not e.actual_start_utc<=moment<e.actual_end_utc:continue
                                    aa,bb=e.azimuth_start_deg,e.azimuth_end_deg
                                    inside=((az>=aa)&(az<=bb)) if aa<=bb else ((az>=aa)|(az<=bb))
                                    inside&=(alt>=e.min_altitude_deg)&(alt<=e.max_altitude_deg)
                                    if e.force_close or e.event_type in ("rocket_launch","terrain_obstruction"):val[inside]=0
                                    elif e.event_type in ("rainy","cloudy","smoggy","cold_wave","tornado"):
                                        val[inside]*=e.transparency_multiplier*e.sky_quality_multiplier*e.instrument_efficiency_multiplier/e.seeing_multiplier
                            if is_band:btotal+=val
                            else:total+=val
                        a=c
            cursor=segment_end
        return total/length/self.cfg["q0"],btotal/length/self.cfg["q0"]

    def row(self,start,end,action,exact_native=False):
        ids=np.full(16,self.n,np.int32);g=np.zeros(16);scores=np.zeros(16)
        if exact_native:
            events=[e for e in self.directional if e.overlaps(start,end)]
            for f,tid in action["assignments"].items():
                i=self.idxs[tid];t=self.s.targets[i]
                hit=self.grid.classify_target(t["ra_deg"],t["dec_deg"],start,action["pointing"]["alt_deg"],action["pointing"]["az_deg"],self.lat,self.lon)
                if hit.region!="glass" or hit.fiber_id!=int(f) or min_altitude_during(t["ra_deg"],t["dec_deg"],start,end,self.s.config)<30:continue
                fn=lambda moment,t=t:radec_to_altaz(t["ra_deg"],t["dec_deg"],moment,self.lat,self.lon)
                bq=self.weather.band_quality(start,end,self.cfg,lambda moment:fn(moment)[0],lambda moment,t=t:lunar_quality_factor(t["ra_deg"],t["dec_deg"],moment,self.s.site,self.cfg))
                mult=program_multiplier(action["program"],program_band(bq,self.cfg),self.cfg)
                score=score_target_exposure(t,list(self.weather.segments(start,end)),events,self.weather,int((end-start).total_seconds()),mult,self.cfg,start,fn,self.s.site)
                ids[int(f)]=i;g[int(f)]=score.factor;scores[int(f)]=score.score
        else:
            assigned=[(int(f),self.idxs[t]) for f,t in action["assignments"].items()]
            if not assigned:return None
            ff,ii=map(np.array,zip(*assigned));q,bq=self.qualities(start,end,ii)
            factor=np.minimum(1.,self.flux[ii]*(end-start).total_seconds()*q/450)
            actual=np.where(bq>=.65,0,np.where(bq>=.4,1,2));program=("DARK","BRIGHT","BACKUP").index(action["program"])
            mult=np.where(actual==program,(1.2,1.12,1.06)[program],1.)
            ids[ff]=ii;g[ff]=factor;scores[ff]=self.weight[ii]*factor*mult
        bits=[]
        for r,ri in zip(self.s.observation_requests,self.request_ids):
            mask=0
            if r["issued_at_utc"]<=start and end<=r["deadline_utc"]:
                for j,i in enumerate(ri):
                    if np.any((ids==i)&(g>=r["completion_factor_threshold"])):mask|=1<<j
            bits.append(mask)
        return {"start":int(start.timestamp()),"end":int(end.timestamp()),"ids":ids,"g":g,"scores":scores,"bits":bits,"action":action}

    def candidates(self,start,night_end,anchors,incumbent_best,incumbent_g,original=None):
        alt,az=m.altaz(self.ra,self.dec,start,self.lat,self.lon);step=self.grid.fiber_side_deg
        fields=[]
        if original is not None:fields.append((original["pointing"]["alt_deg"],original["pointing"]["az_deg"],None))
        for t,phase in anchors:
            ca=min(89.99,alt[t]-phase[0]*step);cz=(az[t]-phase[1]*step/max(.05,math.cos(math.radians(ca))))%360
            fields.append((ca,cz,self.neighbors[t]))
        for ca,cz,near in fields:
            if near is None:
                ar,zr=math.radians(ca),math.radians(cz)
                # Exact spherical center from official alt/az inverse avoids an
                # equatorial fixed-orientation approximation near the zenith.
                target_alt,target_az=np.deg2rad(alt),np.deg2rad(az)
                vv=np.column_stack((np.cos(target_alt)*np.cos(target_az),np.cos(target_alt)*np.sin(target_az),np.sin(target_alt)))
                center=np.array([math.cos(ar)*math.cos(zr),math.cos(ar)*math.sin(zr),math.sin(ar)])
                near=np.flatnonzero((vv*center).sum(axis=1)>=math.cos(math.radians(2.2)))
            ii=np.asarray(near,dtype=int);aa,zz=np.deg2rad(alt[ii]),np.deg2rad(az[ii]);ar,zr=math.radians(ca),math.radians(cz)
            vv=np.column_stack((np.cos(aa)*np.cos(zz),np.cos(aa)*np.sin(zz),np.sin(aa)))
            center=np.array([math.cos(ar)*math.cos(zr),math.cos(ar)*math.sin(zr),math.sin(ar)])
            up=np.array([-math.sin(ar)*math.cos(zr),-math.sin(ar)*math.sin(zr),math.cos(ar)]);right=np.array([-math.sin(zr),math.cos(zr),0])
            depth=(vv*center).sum(axis=1);x=(vv*right).sum(axis=1)/depth*180/np.pi;y=(vv*up).sum(axis=1)/depth*180/np.pi
            inside=(depth>0)&(np.abs(x)<2*step-.003)&(np.abs(y)<2*step-.003)&(alt[ii]>=30)
            ii,x,y=ii[inside],x[inside],y[inside]
            if not len(ii):continue
            ff=np.floor(y/step+2).astype(int)*4+np.floor(x/step+2).astype(int)
            maxdur=min(3600,int((night_end-start).total_seconds()))
            for report in self.report_times:
                if start<report<start+timedelta(seconds=maxdur):maxdur=int((report-start).total_seconds())
            if maxdur<60:continue
            # Duration proposals come from coverage/saturation breakpoints;
            # every scored column later uses exact integration, not this pilot.
            pilot_end=start+timedelta(seconds=min(maxdur,300));pq,_=self.qualities(start,pilot_end,ii)
            need=450/np.maximum(1e-7,self.flux[ii]*pq)
            duration_set={60,min(300,maxdur),min(900,maxdur),maxdur}
            if original:duration_set.add(min(original["duration_seconds"],maxdur))
            options=np.clip(np.ceil(np.concatenate((need,need[self.required[ii]]*.5))*1.01),60,maxdur).astype(int)
            if len(options):
                for p in (20,50,80):duration_set.add(int(np.percentile(options,p)))
            # Keep the four best frozen-density duration proposals plus the
            # original duration. This only restricts candidates; it is no proof.
            frozen=[]
            for d in duration_set:
                gg=np.minimum(1.,self.flux[ii]*pq*d/450);ss=self.weight[ii]*gg*1.2
                val=np.maximum(ss-incumbent_best[ii],0)+50*self.required[ii]*(incumbent_g[ii]<.5)*(gg>=.5)
                val+=.15*ss
                frozen.append((sum(max(val[ff==f]) for f in np.unique(ff))/d,d))
            durations={d for _,d in sorted(frozen,reverse=True)[:4]}
            if original:durations.add(min(original["duration_seconds"],maxdur))
            for dur in sorted(durations):
                end=start+timedelta(seconds=dur)
                ea,_=m.altaz(self.ra[ii],self.dec[ii],end,self.lat,self.lon)
                good=np.minimum(alt[ii],ea)>=30
                jj,fib=ii[good],ff[good]
                if not len(jj):continue
                q,bq=self.qualities(start,end,jj);gg=np.minimum(1.,self.flux[jj]*dur*q/450)
                actual=np.where(bq>=.65,0,np.where(bq>=.4,1,2))
                for mode in ("absolute","residual"):
                    choices=[]
                    for program,mult in enumerate((1.2,1.12,1.06)):
                        ss=self.weight[jj]*gg*np.where(actual==program,mult,1.)
                        utility=ss.copy() if mode=="absolute" else np.maximum(ss-incumbent_best[jj],0)+.1*ss
                        utility+=50*self.required[jj]*(gg>=.5)*(1 if mode=="absolute" else incumbent_g[jj]<.5)
                        for r,ri in zip(self.s.observation_requests,self.request_ids):
                            if r["issued_at_utc"]<=start and end<=r["deadline_utc"]:utility+=(r["completion_reward"]/r["minimum_completed"])*np.isin(jj,ri)*(gg>=r["completion_factor_threshold"])
                        choose=np.array([ix[np.argmax(utility[ix])] for f in np.unique(fib) for ix in [np.flatnonzero(fib==f)]])
                        choices.append((float(utility[choose].sum()),program,choose,ss))
                    _,program,choose,ss=max(choices,key=lambda x:x[0])
                    assignments={str(fib[j]):self.s.targets[jj[j]]["target_id"] for j in choose}
                    action={"action":"observe","pointing":{"alt_deg":float(ca),"az_deg":float(cz)},"assignments":assignments,"duration_seconds":dur,"program":("DARK","BRIGHT","BACKUP")[program]}
                    ids=np.full(16,self.n,np.int32);scores=np.zeros(16);factors=np.zeros(16)
                    ids[fib[choose]]=jj[choose];scores[fib[choose]]=ss[choose];factors[fib[choose]]=gg[choose]
                    bits=[]
                    for r,ri in zip(self.s.observation_requests,self.request_ids):
                        mask=0
                        if r["issued_at_utc"]<=start and end<=r["deadline_utc"]:
                            for j,i in enumerate(ri):
                                if np.any((ids==i)&(factors>=r["completion_factor_threshold"])):mask|=1<<j
                        bits.append(mask)
                    yield {"start":int(start.timestamp()),"end":int(end.timestamp()),"ids":ids,"g":factors,"scores":scores,"bits":bits,"action":action}


class ContinuousSearch:
    def __init__(self,s,columns,report_settlement,rng):
        self.s,self.cols,self.rng=s,columns,rng;self.n=len(s.targets);self.report=report_settlement
        self.start=np.array([c["start"] for c in columns],np.int64);self.end=np.array([c["end"] for c in columns],np.int64)
        self.atoms=np.unique(np.concatenate((self.start,self.end)));self.lo=np.searchsorted(self.atoms,self.start);self.hi=np.searchsorted(self.atoms,self.end)
        self.ids=np.array([c["ids"] for c in columns]);self.scores=np.array([c["scores"] for c in columns]);self.g=np.array([c["g"] for c in columns]);self.bits=np.array([c["bits"] for c in columns],np.int32)
        self.required=np.array([t["required"] for t in s.targets]+[False]);self.penalty=s.score_config["required"]["penalty_per_missing"]
        bands=np.array([int(t["ra_deg"]//s.score_config["uniformity"]["ra_band_width_deg"]) for t in s.targets]);_,self.binv,self.btotal=np.unique(bands,return_inverse=True,return_counts=True)
        ends={x.slot_id.split("-S")[0]:int(x.end_utc.timestamp()) for x in s.slots};begins={}
        for x in s.slots:begins.setdefault(x.slot_id.split("-S")[0],int(x.start_utc.timestamp()))
        self.night_names=np.array(list(begins));starts=np.array(list(begins.values()));self.night=np.searchsorted(starts,self.start,side="right")-1

    def state(self,selected):
        best=np.zeros(self.n+1);g=np.zeros(self.n+1);occ=np.zeros(len(self.atoms),bool)
        if selected:
            ii=np.asarray(selected,int);np.maximum.at(best,self.ids[ii].ravel(),self.scores[ii].ravel());np.maximum.at(g,self.ids[ii].ravel(),self.g[ii].ravel())
            for a in selected:occ[self.lo[a]:self.hi[a]]=True
            bits=np.bitwise_or.reduce(self.bits[ii],axis=0)
        else:bits=np.zeros(len(self.s.observation_requests),np.int32)
        return best,g,occ,bits

    def objective(self,selected):
        best,g,_,bits=self.state(selected);missing=int((self.required&(g<.5)).sum())
        ratios=np.bincount(self.binv,weights=(g[:self.n]>=.5))/self.btotal;den=ratios@ratios;jain=ratios.sum()**2/(len(ratios)*den) if den else 0
        requests=sum(r["completion_reward"] for r,b in zip(self.s.observation_requests,bits) if int(b).bit_count()>=r["minimum_completed"])
        uniform=self.s.score_config["uniformity"]["weight"]*(1-jain)
        return {"total":float(best.sum()-self.penalty*missing-uniform+requests+self.report),"science":float(best.sum()),"required_missing":missing,"uniformity_penalty":float(uniform),"request_reward":float(requests),"report_settlement":self.report,"observe_actions":len(selected)}

    def repair(self,retained,nights,noise):
        selected=list(retained);best,g,occ,bits=self.state(selected);pool=np.flatnonzero(np.isin(self.night,nights))
        while len(pool):
            prefix=np.concatenate(([0],np.cumsum(occ)));pool=pool[(prefix[self.hi[pool]]-prefix[self.lo[pool]])==0]
            if not len(pool):break
            ids=self.ids[pool];sg=self.scores[pool];gg=self.g[pool]
            gain=np.maximum(sg-best[ids],0).sum(axis=1)+self.penalty*((g[ids]<.5)&(gg>=.5)&self.required[ids]).sum(axis=1)
            for r,old,b in zip(self.s.observation_requests,bits,self.bits[pool].T):
                count=int(old).bit_count()
                if count<r["minimum_completed"]:
                    fresh=np.array([int(x&~int(old)).bit_count() for x in b]);gain+=r["completion_reward"]*np.minimum(fresh,r["minimum_completed"]-count)/r["minimum_completed"]
            gain/=self.end[pool]-self.start[pool]
            if gain.max()<=0:break
            priority=gain*np.exp(self.rng.normal(0,noise,len(pool))) if noise else gain;a=int(pool[np.argmax(priority)])
            selected.append(a);occ[self.lo[a]:self.hi[a]]=True;np.maximum.at(best,self.ids[a],self.scores[a]);np.maximum.at(g,self.ids[a],self.g[a]);bits|=self.bits[a]
        return selected

    def optimize(self,initial,seconds,out):
        best=list(initial);obj=self.objective(best);population=[(best,obj)];start=time.monotonic();it=0;history=[];operator_stats={str(w):{"tries":0,"improvements":0} for w in (1,2,4)}
        while time.monotonic()-start<seconds:
            parent,pobj=population[int(self.rng.integers(len(population)))]
            width=int(self.rng.choice([1,2,4],p=[.9,.08,.02]));nightset=self.rng.choice(len(self.night_names),width,replace=False)
            retained=[a for a in parent if self.night[a] not in nightset]
            trial=self.repair(retained,nightset,float(self.rng.choice([0.,.03,.1,.2])))
            tobj=self.objective(trial);operator_stats[str(width)]["tries"]+=1
            if tobj["total"]>obj["total"]:
                best,obj=trial,tobj;operator_stats[str(width)]["improvements"]+=1
                record={"iteration":it,"elapsed":time.monotonic()-start,"operator_nights":width,**obj};history.append(record);print(json.dumps({"improved":record}),flush=True)
                population.append((trial,tobj));population=sorted(population,key=lambda x:x[1]["total"],reverse=True)[:6]
                export(self.cols,best,out/"best_actions.jsonl")
                (out/"best_model.json").write_text(json.dumps(obj,indent=2))
            elif tobj["total"]>=pobj["total"] or self.rng.random()<math.exp(max(-700,(tobj["total"]-pobj["total"])/.3)):
                population.append((trial,tobj));population=sorted(population,key=lambda x:x[1]["total"],reverse=True)[:6]
            it+=1
            if it%250==0:
                (out/"progress.json").write_text(json.dumps({"pid":os.getpid(),"iteration":it,"elapsed":time.monotonic()-start,"best":obj,"population":len(population),"operator_stats":operator_stats},indent=2))
                print(json.dumps({"progress":it,"elapsed":time.monotonic()-start,"best":obj["total"]}),flush=True)
        (out/"history.json").write_text(json.dumps(history,indent=2));return best,obj,it,operator_stats


def export(columns,selected,path):
    actions=[{"start_utc":m.stamp(datetime.fromtimestamp(columns[a]["start"],timezone.utc)),**columns[a]["action"]} for a in sorted(selected,key=lambda a:columns[a]["start"])]
    path.write_text("".join(json.dumps(a,separators=(",",":"))+"\n" for a in actions));return actions


def replay_plan(scenario_path,s,actions,reports,out):
    plan={a["start_utc"]:{k:v for k,v in a.items() if k!="start_utc"} for a in actions};reportset={m.stamp(t) for t in reports};delivered=set();times=sorted(set(map(utc,plan))|set(reports))
    def factory(context):
        def agent(snapshot):
            now=utc(snapshot["now_utc"]);key=m.stamp(now)
            if key in reportset and key not in delivered:delivered.add(key);return {"action":"report"}
            if key in plan:return plan[key]
            nextidx=bisect.bisect_right(times,now)
            if nextidx<len(times):return {"action":"wait","until_utc":m.stamp(times[nextidx])}
            return {"action":"wait","until_utc":m.stamp(s.survey_end)}
        return agent
    return m.run_scenario(scenario_path,factory,out)


def main():
    ap=argparse.ArgumentParser();ap.add_argument("--card",choices=["L1","L2"],default="L1");ap.add_argument("--source",default="gpu_direct_20261003");ap.add_argument("--seconds",type=float,default=600);ap.add_argument("--anchors",type=int,default=3);ap.add_argument("--seed",type=int,default=407);ap.add_argument("--verify-only",action="store_true");args=ap.parse_args()
    out=m.ROOT/"results/cold_global_search_20261003"/f"continuous_{args.card}";out.mkdir(parents=True,exist_ok=True)
    (out/"run_state.json").write_text(json.dumps({"pid":os.getpid(),"stage":"incumbent replay","args":vars(args)},indent=2))
    src=m.ROOT/"results"/args.source/args.card;source_actions=[json.loads(x) for x in (src/"actions.jsonl").read_text().splitlines()]
    source_decisions=list(csv.DictReader((src/"decisions.csv").open()));expected=json.loads((src/"score_report.json").read_text())
    scenario_path=m.UPSTREAM/"local-cards"/args.card/"config/v4_scenario.json";s=m.load_scenario(scenario_path)
    cursor=iter(source_actions)
    reproduced=m.run_scenario(scenario_path,lambda context:lambda snapshot:next(cursor,{"action":"finish"}),out/"incumbent_replay")
    gate={"source":str(src),"expected_total":expected["total"],"reproduced_total":reproduced["total"],"score_exact":expected["total"]==reproduced["total"],"counts_exact":expected["counts"]==reproduced["counts"],"components_exact":expected["components"]==reproduced["components"]}
    # Source observations/decisions were written by the same release engine.
    gate["observation_bytes_exact"]=(src/"observations.csv").read_bytes()==(out/"incumbent_replay/observations.csv").read_bytes()
    gate["decision_bytes_exact"]=(src/"decisions.csv").read_bytes()==(out/"incumbent_replay/decisions.csv").read_bytes()
    def semantic_observations(path):
        records=list(csv.DictReader(path.open()))
        for record in records:record.pop("observation_id")
        return sorted(records,key=lambda record:(int(record["observe_index"]),record["target_id"],int(record["fiber_id"])))
    gate["observation_semantics_exact"]=semantic_observations(src/"observations.csv")==semantic_observations(out/"incumbent_replay/observations.csv")
    gate["observation_order_note"]="Source actions.jsonl sorted assignment keys. Per-action observation CSV row ordering can differ; every scored target/fiber/factor/quality/program/score/validity record is compared after sorting, ignoring only row observation_id."
    (out/"incumbent_gate.json").write_text(json.dumps(gate,indent=2));print(json.dumps({"incumbent_gate":gate}),flush=True)
    if not all(gate[k] for k in ("score_exact","counts_exact","components_exact","observation_semantics_exact","decision_bytes_exact")):raise RuntimeError("unmodified incumbent replay gate failed")
    if args.verify_only:return
    reports=[utc(x["start_utc"]) for x in source_decisions if x["action"]=="report"];oracle=Oracle(s,reports)
    rows=[x for x in source_decisions if x["action"]=="observe"];actions=[a for a in source_actions if a["action"]=="observe"]
    rng=np.random.default_rng(args.seed);cache=out/f"columns_a{args.anchors}_s{args.seed}.pkl";start_build=time.monotonic()
    source_hash=hashlib.sha256((src/"actions.jsonl").read_bytes()).hexdigest()
    cache_manifest=cache.with_suffix(".manifest.json")
    cache_valid=cache.exists() and cache_manifest.exists() and json.loads(cache_manifest.read_text()).get("source_actions_sha256")==source_hash
    if cache_valid:
        columns,initial,rng_state=pickle.loads(cache.read_bytes());rng.bit_generator.state=rng_state
    else:
        columns=[];initial=[]
        for row,action in zip(rows,actions):
            columns.append(oracle.row(utc(row["start_utc"]),utc(row["end_utc"]),action,exact_native=True));initial.append(len(columns)-1)
        baseline_best=np.zeros(oracle.n+1);baseline_g=np.zeros(oracle.n+1)
        for c in columns:np.maximum.at(baseline_best,c["ids"],c["scores"]);np.maximum.at(baseline_g,c["ids"],c["g"])
        original={utc(r["start_utc"]):a for r,a in zip(rows,actions)}
        nights={}
        for slot in s.slots:
            key=slot.slot_id.split("-S")[0];nights.setdefault(key,[slot.start_utc,slot.end_utc])[1]=slot.end_utc
        starts=sorted(set(original)|{slot.start_utc for slot in s.slots})
        observed=(baseline_best[:oracle.n]>0)
        for j,t in enumerate(starts):
            night_end=next(b for a,b in nights.values() if a<=t<b);alt,_=m.altaz(oracle.ra,oracle.dec,t,oracle.lat,oracle.lon)
            visible=np.flatnonzero(alt>=31);unreq=visible[oracle.required[visible]&(baseline_g[visible]<.5)];novel=visible[~observed[visible]]
            anchors=[]
            if len(unreq):anchors.append((int(rng.choice(unreq)),rng.choice([-1.5,-.5,.5,1.5],2)))
            if len(novel):anchors.append((int(rng.choice(novel)),rng.choice([-1.5,-.5,.5,1.5],2)))
            while len(anchors)<args.anchors:anchors.append((int(rng.choice(visible)),rng.choice([-1.5,-.5,.5,1.5],2)))
            columns.extend(oracle.candidates(t,night_end,anchors,baseline_best,baseline_g,original.get(t)))
            if j%100==0:
                print(json.dumps({"candidate_start":j,"total_starts":len(starts),"columns":len(columns),"elapsed":time.monotonic()-start_build}),flush=True)
                (out/"run_state.json").write_text(json.dumps({"pid":os.getpid(),"stage":"candidate generation","start":j,"columns":len(columns)},indent=2))
        cache.write_bytes(pickle.dumps((columns,initial,rng.bit_generator.state)))
        cache_manifest.write_text(json.dumps({"source_actions_sha256":source_hash,"source":str(src),"anchors":args.anchors,"seed":args.seed},indent=2))
    search=ContinuousSearch(s,columns,oracle.report_settlement,rng);baseline=search.objective(initial)
    if abs(baseline["total"]-expected["total"])>1e-5:raise RuntimeError(f"exact original column gate failed: {baseline} vs {expected['total']}")
    (out/"run_state.json").write_text(json.dumps({"pid":os.getpid(),"stage":"search","columns":len(columns),"incumbent":baseline},indent=2));print(json.dumps({"candidate_pool":len(columns),"build_seconds":time.monotonic()-start_build,"baseline":baseline}),flush=True)
    selected,obj,iters,stats=search.optimize(initial,args.seconds,out);plan=export(columns,selected,out/"optimized_actions.jsonl")
    native=replay_plan(scenario_path,s,plan,reports,out/"optimized_native")
    result={"model":"L1/L2 public local truth oracle; continuous integer seconds; original report times fixed; all original observe columns preserved","source":str(src),"incumbent_gate":gate,"columns":len(columns),"seed":args.seed,"search_seconds":args.seconds,"iterations":iters,"baseline_model":baseline,"optimized_model":obj,"native":native,"official_replay_total_delta":native["total"]-expected["total"],"native_model_abs_error":abs(native["total"]-obj["total"]),"operators":stats,"certificate":None}
    (out/"summary.json").write_text(json.dumps(result,indent=2));(out/"run_state.json").write_text(json.dumps({"pid":os.getpid(),"stage":"complete","total":native["total"],"delta":result["official_replay_total_delta"]},indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ("native","incumbent_gate")}),flush=True)


if __name__=="__main__":main()
