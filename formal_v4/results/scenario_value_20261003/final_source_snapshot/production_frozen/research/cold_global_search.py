#!/usr/bin/env python3
"""Independent cold-start whole-season exposure-set experiment.

Derivation made from official guide/scorer before inspecting existing strategies:
  * For a fixed exposure column e, c_ie and g_ie are constants. Science is
    sum_i max_{e in A} c_ie, a monotone submodular set function.
  * Required completion is weighted coverage by columns with g_ie >= threshold,
    also submodular. Request quota rewards create genuine complementarities;
    terminal Jain uniformity is another global coupling.
  * Feasibility is packing time intervals, with no slew/setup cost. A long action
    can therefore lose to several short actions covering different targets.
    Chronological one-step density selection cannot move an early action into a
    later window or exchange actions in different nights.
  * The experiment samples valid pointing/assignment/duration columns and uses
    randomized large-neighborhood destruction and repair over the WHOLE season.
    Exact terminal objective decides acceptance. This is neither DP nor MIP and
    provides no global certificate. Candidate restriction and 900s starts are
    experimental limitations, not claims about attainable contest performance.

This first experiment explicitly uses ONLY public local-card truth as an oracle
to isolate scheduling quality. It is NOT an online submission policy. Practice
truth is never opened. Optional native runner replay checks numerical agreement.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import pickle
import sys
import time
from datetime import timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "upstream/gosim-observer-examples"
sys.path.insert(0, str(UPSTREAM / "runner"))
from challenge.v4_runner import load_scenario, run_scenario
from challenge.v4_scorer import _lunar_geometry
from challenge.v4_fiber_map import radec_to_altaz


def stamp(x):
    return x.strftime("%Y-%m-%dT%H:%M:%SZ")


def altaz(ra, dec, moment, lat, lon):
    d = moment.timestamp() / 86400 + 2440587.5 - 2451545.0
    h = np.deg2rad((280.46061837 + 360.98564736629 * d + lon - ra + 180) % 360 - 180)
    dr = np.deg2rad(dec)
    p = math.radians(lat)
    sa = np.sin(dr) * math.sin(p) + np.cos(dr) * math.cos(p) * np.cos(h)
    a = np.arcsin(np.clip(sa, -1, 1))
    az = np.arctan2(-np.sin(h) * np.cos(dr), (np.sin(dr) - sa * math.sin(p)) / math.cos(p))
    return np.rad2deg(a), np.rad2deg(az) % 360


def xyz(ra, dec):
    r, d = np.deg2rad(ra), np.deg2rad(dec)
    return np.column_stack((np.cos(d) * np.cos(r), np.cos(d) * np.sin(r), np.sin(d)))


def radius_neighbors(vectors, radius):
    """Small local cards need no optional spatial-index dependency."""
    threshold=1-radius*radius/2
    result=[]
    for k in range(0,len(vectors),128):
        v=vectors[k:k+128]
        dot=v[:,0,None]*vectors[None,:,0]+v[:,1,None]*vectors[None,:,1]+v[:,2,None]*vectors[None,:,2]
        result.extend(np.flatnonzero(row>=threshold).tolist() for row in dot)
    return result


def pieces(slot, events, split_events=True):
    cuts = {slot.start_utc, slot.end_utc}
    if split_events:
        for e in events:
            if slot.start_utc < e.actual_start_utc < slot.end_utc:
                cuts.add(e.actual_start_utc)
            if slot.start_utc < e.actual_end_utc < slot.end_utc:
                cuts.add(e.actual_end_utc)
    edges = sorted(cuts)
    for a, b in zip(edges, edges[1:]):
        while a < b:
            c = min(b, a + timedelta(seconds=120))
            yield a + (c - a) / 2, (c - a).total_seconds()
            a = c


def build_quality(s, out):
    """Vector reproduction of official per-slot <=120s integration."""
    targets = s.targets
    ra = np.array([t["ra_deg"] for t in targets])
    dec = np.array([t["dec_deg"] for t in targets])
    vec = xyz(ra, dec)
    lat, lon = s.site["latitude_deg"], s.site["longitude_deg"]
    q = np.zeros((len(s.slots), len(targets)), np.float32)
    band = np.zeros_like(q)
    alt_edges = np.empty((len(s.slots), 2, len(targets)), np.float32)
    directional = [e for e in s.events if e.scope_type == "HORIZON_SECTOR"]
    faults = [e for e in s.events if e.event_type == "instrument_fault"]
    reference_airmass = 1 / (1 + .50572 * 96.07995 ** -1.6364)
    lunar = s.score_config["lunar_model"]
    beta = s.score_config["airmass_exponent"]
    q0 = s.score_config["q0"]
    for k, slot in enumerate(s.slots):
        alt_edges[k, 0] = altaz(ra, dec, slot.start_utc, lat, lon)[0]
        alt_edges[k, 1] = altaz(ra, dec, slot.end_utc, lat, lon)[0]
        if not slot.is_observable:
            continue
        events = [e for e in directional if e.overlaps(slot.start_utc, slot.end_utc)]
        eff = slot.instrument_efficiency
        # Oracle reports repair every fault at its actual first decision slot.
        for f in faults:
            if f.actual_start_utc <= slot.start_utc < f.actual_end_utc and f.instrument_efficiency_multiplier > 0:
                eff = min(1., eff / f.instrument_efficiency_multiplier)
        for target_array, event_split in ((q, True), (band, False)):
            total = np.zeros(len(targets))
            for moment, seconds in pieces(slot, events, event_split):
                alt, az = altaz(ra, dec, moment, lat, lon)
                z = 90 - np.maximum(alt, .01)
                mass = 1 / (np.cos(np.deg2rad(z)) + .50572 * (96.07995 - z) ** -1.6364) / reference_airmass
                mr, md, illum, ma = _lunar_geometry(moment, lat, lon)
                mvec = xyz(np.array([mr]), np.array([md]))[0]
                sep = np.rad2deg(np.arccos(np.clip((vec*mvec).sum(axis=1), -1, 1)))
                lum = 1 - lunar["maximum_penalty"] * illum * math.sin(math.radians(max(0, ma))) ** lunar["altitude_exponent"] * np.exp(-sep / lunar["angular_decay_scale_deg"])
                value = seconds * slot.transparency * slot.sky_quality * lum / slot.seeing_arcsec / mass ** beta
                if event_split:
                    value *= eff
                    for e in events:
                        if not e.actual_start_utc <= moment < e.actual_end_utc:
                            continue
                        a, b = e.azimuth_start_deg, e.azimuth_end_deg
                        inside = ((az >= a) & (az <= b)) if a <= b else ((az >= a) | (az <= b))
                        inside &= (alt >= e.min_altitude_deg) & (alt <= e.max_altitude_deg)
                        if e.force_close or e.event_type in ("rocket_launch", "terrain_obstruction"):
                            value[inside] = 0
                        elif e.event_type in ("rainy", "cloudy", "smoggy", "cold_wave", "tornado"):
                            value[inside] *= e.transparency_multiplier * e.sky_quality_multiplier * e.instrument_efficiency_multiplier / e.seeing_multiplier
                total += value
            target_array[k] = total / 900 / q0
        if k % 200 == 0:
            print(json.dumps({"quality_slot": k, "total_slots": len(s.slots)}), flush=True)
    np.savez_compressed(out / "quality_oracle.npz", quality=q, band=band, alt_edges=alt_edges)
    return q, band, alt_edges


def make_columns(s, q, band, edges, anchor_count, rng):
    targets, cfg = s.targets, s.score_config
    ra = np.array([t["ra_deg"] for t in targets]); dec = np.array([t["dec_deg"] for t in targets])
    flux = np.array([t["feature_flux"] for t in targets]); weight = np.array([t["science_weight"] for t in targets])
    required = np.array([t["required"] for t in targets])
    vec = xyz(ra, dec)
    neighbors = radius_neighbors(vec, 2 * math.sin(math.radians(3.) / 2))
    lat, lon = s.site["latitude_deg"], s.site["longitude_deg"]
    step = math.sqrt(s.fiber_config["field"]["fiber_area_deg2"])
    req_idx = np.flatnonzero(required)
    # Visibility scarcity only changes the column sampling distribution.
    avail = ((edges[:, 0] >= 30) & (edges[:, 1] >= 30) & (q * flux[None, :] * 3600 / 450 >= .5)).sum(axis=0)
    tidx = {t["target_id"]: i for i, t in enumerate(targets)}
    requests = s.observation_requests
    request_arrays = [[tidx[t] for t in r["target_ids"]] for r in requests]
    rows, padded_ids, padded_scores, padded_factors, bitrows = [], [], [], [], []
    for k, slot in enumerate(s.slots):
        if not slot.is_observable:
            continue
        alt, az = altaz(ra, dec, slot.start_utc, lat, lon)
        visible = (alt > 31) & (q[k] > .05)
        vr = req_idx[visible[req_idx]]
        top_req = vr[np.argsort(avail[vr])[:anchor_count // 3]]
        random_req = rng.choice(vr, min(len(vr), anchor_count // 3), replace=False) if len(vr) else vr
        science = np.flatnonzero(visible)
        probs = weight[science] * np.minimum(flux[science] * q[k, science] * 900 / 450, 1.)
        random_science = rng.choice(science, min(len(science), anchor_count // 3), replace=False, p=probs / probs.sum()) if len(science) else science
        active_targets = [t for r, ii in zip(requests, request_arrays) if r["issued_at_utc"] <= slot.start_utc < r["deadline_utc"] for t in ii if visible[t]]
        anchors = np.unique(np.concatenate((top_req, random_req, random_science, np.asarray(active_targets,dtype=int)))).astype(int)
        for anchor in anchors:
            # Anchor sits at a cell center instead of the central four-cell seam.
            phase = rng.choice([-1.5, -.5, .5, 1.5], size=2)
            ca = min(89.99, alt[anchor] - phase[0] * step)
            cz = (az[anchor] - phase[1] * step / max(.05, math.cos(math.radians(ca)))) % 360
            ii = np.array(neighbors[anchor], dtype=np.int32)
            aa, zz = np.deg2rad(alt[ii]), np.deg2rad(az[ii])
            ar, zr = math.radians(ca), math.radians(cz)
            vv = np.column_stack((np.cos(aa)*np.cos(zz), np.cos(aa)*np.sin(zz), np.sin(aa)))
            center = np.array([math.cos(ar)*math.cos(zr), math.cos(ar)*math.sin(zr), math.sin(ar)])
            up = np.array([-math.sin(ar)*math.cos(zr), -math.sin(ar)*math.sin(zr), math.cos(ar)])
            right = np.array([-math.sin(zr), math.cos(zr), 0])
            depth = (vv*center).sum(axis=1)
            x, y = (vv*right).sum(axis=1) / depth * 180 / np.pi, (vv*up).sum(axis=1) / depth * 180 / np.pi
            glass = (depth > 0) & (np.abs(x) < 2*step-.005) & (np.abs(y) < 2*step-.005)
            ii, x, y = ii[glass], x[glass], y[glass]
            fibers = np.floor(y / step + 2).astype(int)*4 + np.floor(x / step + 2).astype(int)
            for dur in (1, 2, 3, 4):
                if k+dur > len(s.slots) or s.slots[k+dur-1].end_utc-slot.start_utc != timedelta(seconds=dur*900):
                    continue
                if any(e.event_type=="instrument_fault" and slot.start_utc<e.actual_start_utc<s.slots[k+dur-1].end_utc for e in s.events):
                    continue
                valid = np.min(edges[k:k+dur, :, ii], axis=(0, 1)) >= 30
                if not valid.any():
                    continue
                jj, ff = ii[valid], fibers[valid]
                quality = q[k:k+dur, jj].mean(axis=0)
                bq = band[k:k+dur, jj].mean(axis=0)
                g = np.minimum(1., flux[jj]*dur*900*quality/450)
                actual = np.where(bq >= cfg["program"]["bands"]["DARK"], 0, np.where(bq >= cfg["program"]["bands"]["BRIGHT"], 1, 2))
                for required_bonus in (0., 50.):
                    best_choice = None
                    for program, mult in enumerate((1.2, 1.12, 1.06)):
                        scores = weight[jj]*g*np.where(actual == program, mult, 1.)
                        utility = scores + required_bonus*required[jj]*(g >= .5)
                        # Request-target coverage gets sampling value, terminal reward
                        # still only pays when the entire exact quota is satisfied.
                        for r, ri in zip(requests, request_arrays):
                            if r["issued_at_utc"] <= slot.start_utc and s.slots[k+dur-1].end_utc <= r["deadline_utc"]:
                                utility += (r["completion_reward"]/r["minimum_completed"])*np.isin(jj, ri)*(g >= r["completion_factor_threshold"])
                        choose = [ix[np.argmax(utility[ix])] for f in np.unique(ff) for ix in [np.flatnonzero(ff == f)]]
                        val = float(utility[choose].sum())
                        if best_choice is None or val > best_choice[0]:
                            best_choice = (val, program, np.array(choose), scores)
                    _, program, choose, scores = best_choice
                    ids = np.full(16, len(targets), np.int32); ss = np.zeros(16,np.float32); gg = np.zeros(16,np.float32)
                    ids[ff[choose]]=jj[choose]; ss[ff[choose]]=scores[choose]; gg[ff[choose]]=g[choose]
                    bits=[]
                    for r, ri in zip(requests, request_arrays):
                        mask=0
                        if r["issued_at_utc"] <= slot.start_utc and s.slots[k+dur-1].end_utc <= r["deadline_utc"]:
                            for j,t in enumerate(ri):
                                if np.any((ids==t)&(gg>=r["completion_factor_threshold"])):mask |= 1<<j
                        bits.append(mask)
                    rows.append((k,dur,ca,cz,program));padded_ids.append(ids);padded_scores.append(ss);padded_factors.append(gg);bitrows.append(bits)
        if k % 200 == 0:
            print(json.dumps({"column_slot":k,"columns":len(rows)}),flush=True)
    return {"rows":np.array(rows),"ids":np.array(padded_ids),"scores":np.array(padded_scores),"factors":np.array(padded_factors),"request_bits":np.array(bitrows,np.int32),"availability":avail}


class Search:
    def __init__(self,s,c,rng):
        self.s,self.c,self.rng=s,c,rng
        self.n=len(s.targets);self.slots=len(s.slots)
        self.required=np.array([t["required"] for t in s.targets]+[False])
        ra=np.array([t["ra_deg"] for t in s.targets]);self.bands=np.floor(ra/s.score_config["uniformity"]["ra_band_width_deg"]).astype(int)
        self.band_unique,self.band_inverse,self.band_total=np.unique(self.bands,return_inverse=True,return_counts=True)
        self.starts=c["rows"][:,0].astype(int);self.durations=c["rows"][:,1].astype(int)
        self.by_start=[np.flatnonzero(self.starts==k) for k in range(self.slots)]
        self.nights=np.array([x.slot_id.split("-S")[0] for x in s.slots]);self.night_unique=np.unique(self.nights)
        self.penalty=s.score_config["required"]["penalty_per_missing"]

    def state(self,selected):
        best=np.zeros(self.n+1);factors=np.zeros(self.n+1);occupied=np.zeros(self.slots,bool)
        if selected:
            ii=np.array(selected,dtype=int)
            np.maximum.at(best,self.c["ids"][ii].ravel(),self.c["scores"][ii].ravel())
            np.maximum.at(factors,self.c["ids"][ii].ravel(),self.c["factors"][ii].ravel())
            for a in selected:occupied[self.starts[a]:self.starts[a]+self.durations[a]]=True
        bits=np.bitwise_or.reduce(self.c["request_bits"][selected],axis=0) if selected else np.zeros(len(self.s.observation_requests),np.int32)
        return best,factors,occupied,bits

    def objective(self,selected):
        best,g,_,bits=self.state(selected)
        missing=int((self.required&(g<self.s.score_config["required"]["observed_factor_threshold"])).sum())
        ratios=np.bincount(self.band_inverse,weights=(g[:self.n]>=self.s.score_config["uniformity"]["observed_factor_threshold"]))/self.band_total
        jain=ratios.sum()**2/(len(ratios)*(ratios@ratios)) if ratios@ratios else 0.
        requests=sum(r["completion_reward"] for r,b in zip(self.s.observation_requests,bits) if int(b).bit_count()>=r["minimum_completed"])
        uniform=self.s.score_config["uniformity"]["weight"]*(1-jain)
        return {"score":float(best.sum()-self.penalty*missing-uniform+requests),"science":float(best.sum()),"required_missing":missing,"uniformity_penalty":float(uniform),"request_reward":float(requests),"actions":len(selected)}

    def gains(self,pool,best,g,bits):
        ids=self.c["ids"][pool];sg=self.c["scores"][pool];gg=self.c["factors"][pool]
        value=np.maximum(sg-best[ids],0).sum(axis=1)
        value+=self.penalty*((g[ids]<.5)&(gg>=.5)&self.required[ids]).sum(axis=1)
        for r,old,b in zip(self.s.observation_requests,bits,self.c["request_bits"][pool].T):
            current=int(old).bit_count()
            if current<r["minimum_completed"]:
                fresh=np.array([int(x & ~int(old)).bit_count() for x in b])
                value+=r["completion_reward"]*np.minimum(fresh,r["minimum_completed"]-current)/r["minimum_completed"]
        return value/self.durations[pool]

    def chronological(self):
        selected=[];best,g,occupied,bits=self.state([])
        for k in range(self.slots):
            if occupied[k]:continue
            pool=self.by_start[k]
            if not len(pool):continue
            gains=self.gains(pool,best,g,bits)
            a=int(pool[np.argmax(gains)])
            if gains.max()<=0:continue
            selected.append(a);occupied[k:k+self.durations[a]]=True
            np.maximum.at(best,self.c["ids"][a],self.c["scores"][a]);np.maximum.at(g,self.c["ids"][a],self.c["factors"][a]);bits|=self.c["request_bits"][a]
        return selected

    def repair(self,retained,allowed,noise):
        selected=list(retained);best,g,occupied,bits=self.state(selected)
        pool=np.flatnonzero(allowed[self.starts])
        # Pool has starts in destroyed nights, but duration may extend across
        # retained actions. Every insertion rechecks occupied interval capacity.
        while len(pool):
            free=np.ones(len(pool),bool)
            for offset in range(4):
                rows=self.durations[pool]>offset
                free[rows]&=~occupied[self.starts[pool[rows]]+offset]
            pool=pool[free]
            if not len(pool):break
            gains=self.gains(pool,best,g,bits)
            if gains.max()<=0:break
            priority=gains*np.exp(self.rng.normal(0,noise,len(pool))) if noise else gains
            a=int(pool[np.argmax(priority)])
            selected.append(a);occupied[self.starts[a]:self.starts[a]+self.durations[a]]=True
            np.maximum.at(best,self.c["ids"][a],self.c["scores"][a]);np.maximum.at(g,self.c["ids"][a],self.c["factors"][a]);bits|=self.c["request_bits"][a]
        return selected

    def optimize(self,selected,seconds,out,widths=(1,2,3,5)):
        incumbent=list(selected);incobj=self.objective(selected);current=list(selected);curobj=incobj
        history=[];start=time.monotonic();iteration=0
        while time.monotonic()-start<seconds:
            width=int(self.rng.choice(widths));nights=self.rng.choice(self.night_unique,min(width,len(self.night_unique)),replace=False)
            allowed=np.isin(self.nights,nights)
            retained=[a for a in current if not allowed[self.starts[a]]]
            trial=self.repair(retained,allowed,float(self.rng.choice([0.,.05,.12,.25])))
            obj=self.objective(trial);delta=obj["score"]-curobj["score"]
            temp=max(.1,2*(1-(time.monotonic()-start)/seconds))
            if delta>=0 or self.rng.random()<math.exp(max(-700,delta/temp)):
                current,curobj=trial,obj
            if obj["score"]>incobj["score"]:
                incumbent,incobj=trial,obj
                record={"iteration":iteration,"elapsed":time.monotonic()-start,**obj};history.append(record);print(json.dumps({"improved":record}),flush=True)
            iteration+=1
        (out/"search_history.json").write_text(json.dumps(history,indent=2))
        return incumbent,incobj,iteration


def export_actions(s,c,selected,path):
    actions=[]
    for a in sorted(selected,key=lambda a:c["rows"][a,0]):
        k,dur,alt,az,program=c["rows"][a]
        assignments={str(f):s.targets[int(t)]["target_id"] for f,t in enumerate(c["ids"][a]) if t<len(s.targets)}
        actions.append({"start_utc":stamp(s.slots[int(k)].start_utc),"action":"observe","pointing":{"alt_deg":float(alt),"az_deg":float(az)},"assignments":assignments,"duration_seconds":int(dur)*900,"program":("DARK","BRIGHT","BACKUP")[int(program)]})
    path.write_text("".join(json.dumps(x,separators=(",",":"))+"\n" for x in actions))
    return actions


def replay(scenario_path,s,actions,out):
    planned={x["start_utc"]:{k:v for k,v in x.items() if k!="start_utc"} for x in actions}
    faults={stamp(e.actual_start_utc) for e in s.events if e.event_type=="instrument_fault"}
    reported=set()
    def factory(context):
        def decide(snapshot):
            now=snapshot["now_utc"]
            if now in faults and now not in reported:
                reported.add(now);return {"action":"report"}
            if now in planned:return planned[now]
            return {"action":"wait","duration_seconds":900}
        return decide
    return run_scenario(scenario_path,factory,out)


def main():
    ap=argparse.ArgumentParser();ap.add_argument("--card",choices=["L1","L2"],default="L1");ap.add_argument("--seconds",type=float,default=180);ap.add_argument("--anchors",type=int,default=36);ap.add_argument("--seed",type=int,default=91);ap.add_argument("--replay",action="store_true");args=ap.parse_args()
    out=ROOT/"results/cold_global_search_20261003"/args.card;out.mkdir(parents=True,exist_ok=True)
    scenario_path=UPSTREAM/"local-cards"/args.card/"config/v4_scenario.json";s=load_scenario(scenario_path);rng=np.random.default_rng(args.seed);started=time.monotonic()
    qp=out/"quality_oracle.npz"
    if qp.exists():
        data=np.load(qp);q,band,edges=(data[k] for k in ("quality","band","alt_edges"))
    else:q,band,edges=build_quality(s,out)
    cp=out/f"columns_v2_a{args.anchors}_s{args.seed}.pkl"
    if cp.exists():c=pickle.loads(cp.read_bytes())
    else:
        c=make_columns(s,q,band,edges,args.anchors,rng);cp.write_bytes(pickle.dumps(c))
    build_seconds=time.monotonic()-started;search=Search(s,c,rng);baseline=search.chronological();baseline_obj=search.objective(baseline);print(json.dumps({"baseline":baseline_obj,"columns":len(c["rows"]),"build_seconds":build_seconds}),flush=True)
    optimized,obj,iters=search.optimize(baseline,args.seconds,out)
    base_actions=export_actions(s,c,baseline,out/"baseline_actions.jsonl");opt_actions=export_actions(s,c,optimized,out/"optimized_actions.jsonl")
    result={"model":"public local truth oracle; 900s start grid; 900/1800/2700/3600s duration columns; whole-season randomized LNS","card":args.card,"seed":args.seed,"columns":len(c["rows"]),"build_seconds":build_seconds,"search_seconds":args.seconds,"iterations":iters,"baseline":baseline_obj,"optimized":obj,"improvement":obj["score"]-baseline_obj["score"],"certificate":None}
    (out/"summary.json").write_text(json.dumps(result,indent=2))
    if args.replay:
        for label,actions in (("baseline",base_actions),("optimized",opt_actions)):
            report=replay(scenario_path,s,actions,out/f"native_{label}");result[f"native_{label}"]=report
        (out/"summary.json").write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if not k.startswith("native_")}),flush=True)


if __name__=="__main__":main()
