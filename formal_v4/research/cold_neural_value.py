#!/usr/bin/env python3
"""Independent small NN experiment: estimate deferred terminal target contribution.

Only upstream/public local cards L1--L4 are used. The training simulator deliberately
compresses fiber geometry into spatial groups, so its returns are training labels,
not official scores. `evaluate` uses the official v4 runner for whole-season scores.
Inference has no truth inputs and is pure NumPy after exporting a 3-layer MLP.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parents[1]
UPSTREAM = BASE / "upstream/gosim-observer-examples"
sys.path.insert(0, str(UPSTREAM))
from runner.challenge.v4_runner import load_scenario, run_scenario
from runner.challenge.v4_fiber_map import radec_to_altaz
from runner.challenge.v4_scorer import _lunar_geometry

OUT = BASE / "results/cold_neural_value_20261003"
FEATURES = ["log_flux", "science_weight", "required", "current_factor", "current_best_fraction",
            "remaining_visible_slots", "future_peak_geometry", "current_altitude",
            "local_missing_required", "required_pressure", "band_fraction", "global_fraction",
            "remaining_season", "local_missing_targets"]


def utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def rows(path):
    with Path(path).open(newline="") as h:
        return list(csv.DictReader(h))


def public_times(card):
    calendar = rows(UPSTREAM / "local-cards" / card / "public/v4_night_calendar.csv")
    slots = []
    for row in calendar:
        start, end = utc(row["observing_start_utc"]), utc(row["observing_end_utc"])
        while start < end:
            slots.append(start)
            start += timedelta(seconds=900)
    return slots


class Catalog:
    def __init__(self, targets, site, times, score):
        self.targets, self.site, self.times, self.score = targets, site, times, score
        self.ids = [x["target_id"] for x in targets]
        self.index = {s: i for i, s in enumerate(self.ids)}
        self.ra = np.array([x["ra_deg"] for x in targets], dtype=np.float64)
        self.dec = np.array([x["dec_deg"] for x in targets], dtype=np.float64)
        self.flux = np.array([x["feature_flux"] for x in targets], dtype=np.float32)
        self.weight = np.array([x["science_weight"] for x in targets], dtype=np.float32)
        self.req = np.array([x["required"] for x in targets], dtype=bool)
        self.band = (self.ra // score["uniformity"]["ra_band_width_deg"]).astype(int)
        self.bandtot = np.bincount(self.band, minlength=36)
        # Approximate static 3-deg spatial groups are used ONLY by training simulator.
        decbin = np.floor((self.dec + 90) / 3).astype(int)
        physra = self.ra * np.cos(np.radians(decbin * 3 - 88.5))
        key = decbin * 1000 + np.floor(physra / 3).astype(int)
        self.groupkeys, self.group = np.unique(key, return_inverse=True)
        self.groups = [np.where(self.group == k)[0] for k in range(len(self.groupkeys))]
        self.lat = math.radians(float(site["latitude_deg"]))
        self.lon = float(site["longitude_deg"])
        self.sin_dec, self.cos_dec = np.sin(np.radians(self.dec)), np.cos(np.radians(self.dec))
        self.alt_cache = np.stack([self.altaz(t)[0] for t in times]).astype(np.float32)
        ends = np.stack([self.altaz(t + timedelta(seconds=900))[0] for t in times]).astype(np.float32)
        self.visible = np.minimum(self.alt_cache, ends) >= 30
        self.futures = np.flip(np.cumsum(np.flip(self.visible, axis=0), axis=0), axis=0).astype(np.float32)
        geometry = self.geometric_quality(self.alt_cache) * self.visible
        self.futurepeak = np.flip(np.maximum.accumulate(np.flip(geometry, axis=0), axis=0), axis=0).astype(np.float32)
        self.stamps = np.array([t.timestamp() for t in times])

    def altaz(self, t):
        d = t.timestamp() / 86400 + 2440587.5 - 2451545.0
        lst = (280.46061837 + 360.98564736629 * d + self.lon) % 360
        hour = np.radians((lst - self.ra + 180) % 360 - 180)
        sa = math.sin(self.lat) * self.sin_dec + math.cos(self.lat) * self.cos_dec * np.cos(hour)
        alt = np.arcsin(np.clip(sa, -1, 1))
        ca = np.maximum(np.cos(alt), 1e-12)
        saz = -np.sin(hour) * self.cos_dec / ca
        caz = (self.sin_dec - np.sin(alt) * math.sin(self.lat)) / (ca * math.cos(self.lat))
        return np.degrees(alt), np.degrees(np.arctan2(saz, caz)) % 360

    def geometric_quality(self, alt):
        z = 90 - np.maximum(alt, 0)
        airmass = 1 / (np.cos(np.radians(z)) + 0.50572 * np.maximum(96.07995-z, .01)**(-1.6364))
        zen = 1 / (1 + .50572 * 96.07995**(-1.6364))
        return (airmass / zen) ** (-float(self.score["airmass_exponent"]))

    def features(self, t, factor, best, idx=None):
        if idx is None:
            idx = np.arange(len(self.ids))
        done = factor >= .5
        req_local = np.bincount(self.group, weights=self.req & ~done, minlength=len(self.groups))
        missing_local = np.bincount(self.group, weights=~done, minlength=len(self.groups))
        banddone = np.bincount(self.band, weights=done, minlength=36)
        frac = np.divide(banddone, self.bandtot, out=np.zeros(36), where=self.bandtot > 0)
        future = self.futures[min(t, len(self.times)-1), idx]
        local = req_local[self.group[idx]]
        return np.column_stack([
            np.log1p(self.flux[idx]), self.weight[idx], self.req[idx], factor[idx],
            best[idx] / np.maximum(self.weight[idx] * 1.2, 1e-6),
            np.log1p(future) / np.log1p(len(self.times)),
            self.futurepeak[min(t, len(self.times)-1), idx],
            self.alt_cache[min(t, len(self.times)-1), idx] / 90,
            np.log1p(local) / np.log(101), local / (1+future/10), frac[self.band[idx]],
            np.full(len(idx), done.mean()), np.full(len(idx), (len(self.times)-t)/len(self.times)),
            np.log1p(missing_local[self.group[idx]]) / np.log(101),
        ]).astype(np.float32)

    def terminal(self, factor, best):
        done = factor >= .5
        missing = np.count_nonzero(self.req & ~done)
        bd = np.bincount(self.band, weights=done, minlength=36)
        r = bd[self.bandtot > 0] / self.bandtot[self.bandtot > 0]
        jain = float(r.sum()**2 / (len(r)*np.square(r).sum())) if np.square(r).sum() else 0.
        return float(best.sum() - missing * self.score["required"]["penalty_per_missing"]
                     - self.score["uniformity"]["weight"] * (1-jain))


def make_catalog(card):
    scenario = load_scenario(UPSTREAM / "local-cards" / card / "config/v4_scenario.json")
    return Catalog(scenario.targets, scenario.site, public_times(card), scenario.score_config), scenario


def generate(episodes=12):
    OUT.mkdir(parents=True, exist_ok=True)
    all_x, all_y, all_cards, reports = [], [], [], []
    begin = time.monotonic()
    for ci, card in enumerate(["L1", "L2", "L3"]):
        cat, scenario = make_catalog(card)
        # Allowed public local-card truth gives realized training transitions. The NN
        # never sees future weather numerics as an input. Events/stress are omitted in
        # this compressed simulator and handled by the official evaluation later.
        weather = np.array([
            (s.instrument_efficiency*s.transparency*s.sky_quality/s.seeing_arcsec/cat.score["q0"])
            if s.is_observable else 0 for s in scenario.slots], dtype=np.float32)
        card_eps = episodes if card != "L3" else max(3, episodes//3)
        for ep in range(card_eps):
            rng = np.random.default_rng(20261003 + ci*1000 + ep)
            n = len(cat.ids)
            factor, best = np.zeros(n, np.float32), np.zeros(n, np.float32)
            completed_at = np.full(n, len(cat.times)+1, int)
            traces = []
            reward_scale = float(rng.choice([0.3, 1., 5., 15., 50.]))
            quota = float(rng.choice([.35, .55, .8, 1.]))
            for t in range(len(cat.times)):
                if t % 12 == 0:
                    ix = rng.choice(n, 96, replace=False)
                    traces.append((cat.features(t, factor, best, ix), ix, t, best[ix].copy(), factor[ix].copy()))
                if rng.random() > quota:
                    continue
                quality = weather[t] * cat.geometric_quality(cat.alt_cache[t])
                f = np.minimum(1., cat.flux*quality/.5) * cat.visible[t]
                s = cat.weight*f*1.12
                utility = np.maximum(s-best, 0) + reward_scale * cat.req * (factor < .5) * (f >= .5)
                # Randomized urgency curricula expose recoverable and scarce demand.
                utility *= (1 + float(rng.uniform(0, 5)) / (1+cat.futures[t]/20))
                utility *= rng.lognormal(0, .12, n)
                group_sum = np.bincount(cat.group, weights=utility, minlength=len(cat.groups))
                g = int(np.argmax(group_sum))
                ix = cat.groups[g]
                ix = ix[np.argsort(utility[ix])[-16:]]
                newly = (factor[ix] < .5) & (f[ix] >= .5)
                completed_at[ix[newly]] = np.minimum(completed_at[ix[newly]], t)
                factor[ix] = np.maximum(factor[ix], f[ix])
                best[ix] = np.maximum(best[ix], s[ix])
            for x, ix, t, oldbest, oldfactor in traces:
                # Label 1 is terminal completion if this target was not yet complete;
                # label 2 is its remaining terminal science contribution. Labels come
                # from realized rollout endpoints, never from instantaneous factors.
                complete = ((completed_at[ix] >= t) & (completed_at[ix] < len(cat.times))).astype(np.float32)
                complete[oldfactor >= .5] = 1.
                additional = np.clip((best[ix]-oldbest)/(cat.weight[ix]*1.2), 0, 1)
                all_x.append(x); all_y.append(np.column_stack([complete, additional]))
                all_cards.append(np.full(len(ix), ci, np.int8))
            reports.append({"card":card, "episode":ep, "req_priority":reward_scale,
                            "quota":quota, "compressed_terminal":cat.terminal(factor,best),
                            "completed":int((factor >= .5).sum()), "required_missing":int((cat.req & (factor < .5)).sum())})
            print(json.dumps(reports[-1]), flush=True)
    x, y, card = np.concatenate(all_x), np.concatenate(all_y), np.concatenate(all_cards)
    np.savez_compressed(OUT / "samples.npz", x=x, y=y, card=card)
    (OUT/"dataset.json").write_text(json.dumps({"features":FEATURES,"samples":len(x),"seconds":time.monotonic()-begin,
         "split":{"train":["L1","L2"],"validation":["L3"],"official_final_test":["L4"]},
         "labels":"realized terminal per-target completion and remaining science under randomized compressed continuation",
         "episodes":reports,"limitations":["training groups replace fiber grid", "training omits event/stress/request reward",
         "not an optimal controller", "compressed returns are not official scores"]}, indent=2))
    return x,y,card


def train(epochs=24):
    import torch
    torch.set_num_threads(2)
    torch.manual_seed(20261003)
    d = np.load(OUT/"samples.npz")
    x,y,c = d["x"],d["y"],d["card"]
    mask = c < 2
    mean,std = x[mask].mean(0),np.maximum(x[mask].std(0),.05)
    xt = torch.from_numpy((x[mask]-mean)/std)
    yt = torch.from_numpy(y[mask])
    xv = torch.from_numpy((x[~mask]-mean)/std)
    yv = torch.from_numpy(y[~mask])
    net = torch.nn.Sequential(torch.nn.Linear(len(FEATURES),48),torch.nn.ReLU(),
        torch.nn.Linear(48,32),torch.nn.ReLU(),torch.nn.Linear(32,2))
    optim = torch.optim.AdamW(net.parameters(),lr=.002,weight_decay=.001)
    begin = time.monotonic(); history=[]
    for epoch in range(epochs):
        net.train(); perm=torch.randperm(len(xt)); losses=[]
        for i in range(0,len(xt),2048):
            ix=perm[i:i+2048]; logits=net(xt[ix])
            loss=torch.nn.functional.binary_cross_entropy_with_logits(logits[:,0],yt[ix,0]) + \
                torch.nn.functional.mse_loss(torch.sigmoid(logits[:,1]),yt[ix,1])
            optim.zero_grad();loss.backward();optim.step();losses.append(float(loss.detach()))
        net.eval()
        with torch.no_grad():
            p=torch.sigmoid(net(xv)); p0=y[mask,0].mean()
            brier=float(((p[:,0]-yv[:,0])**2).mean())
            mse=float(((p[:,1]-yv[:,1])**2).mean())
            constant_brier=float(((yv[:,0]-p0)**2).mean())
            history.append({"epoch":epoch+1,"loss":float(np.mean(losses)),"validation_brier":brier,
                            "validation_science_mse":mse,"constant_brier":constant_brier})
        print(json.dumps(history[-1]),flush=True)
    weights={"mean":mean,"std":std}
    layers=[net[0],net[2],net[4]]
    for i,layer in enumerate(layers):
        weights[f"w{i}"]=layer.weight.detach().numpy();weights[f"b{i}"]=layer.bias.detach().numpy()
    np.savez_compressed(OUT/"model.npz",**weights)
    (OUT/"training.json").write_text(json.dumps({"seconds":time.monotonic()-begin,"history":history,
        "network":"14-48-32-2; sigmoid completion and residual science", "runtime":"NumPy inference; torch used only training",
        "parameters":sum(p.numel() for p in net.parameters())},indent=2))


class NumpyValue:
    def __init__(self,path):
        self.p={k:v for k,v in np.load(path).items()}
    def __call__(self,x):
        p=self.p;x=(x-p["mean"])/p["std"]
        for i in range(3):
            x=x@p[f"w{i}"].T+p[f"b{i}"]
            if i<2:x=np.maximum(x,0)
        return 1/(1+np.exp(-np.clip(x,-30,30)))


class ColdAgent:
    def __init__(self,context,card,neural=True,strength=.75,control="boost"):
        self.cat=Catalog(context["targets"],context["site"],public_times(card),context["score"])
        self.best=np.zeros(len(self.cat.ids),np.float32)
        self.factor=np.zeros(len(self.cat.ids),np.float32)
        self.nn=NumpyValue(OUT/"model.npz") if neural else None
        self.strength=strength
        self.control=control
        self.last_index=-1;self.pending={};self.reported=set();self.history=[]
        self.seen_factor_note="last_result omits factor; conservative factor=score/(weight*maximum program multiplier)"

    def __call__(self,snapshot):
        c=self.cat;now=utc(snapshot["now_utc"]);ts=now.timestamp()
        result=snapshot.get("last_result") or {}
        if result.get("action")=="observe" and result.get("observe_index",-1)!=self.last_index:
            self.last_index=result["observe_index"]
            observations=[]
            for hit in result.get("hits",[]):
                i=c.index[hit["target_id"]];s=float(hit["score"])
                self.best[i]=max(self.best[i],s)
                f=min(1.,s/(c.weight[i]*1.2));self.factor[i]=max(self.factor[i],f)
                observations.append((i,s,f))
            self.history.append((self.last_index,observations))
        for msg in snapshot.get("new_messages",[]):
            if msg.get("record_type")=="state_resync":
                # Replay valid history after invalidation, using participant-visible range.
                w=msg.get("invalidated_window",{})
                first=w.get("action_index_start",0)
                last=w.get("action_index_end_exclusive",0)
                self.history=[h for h in self.history if not first <= h[0] < last]
                self.best.fill(0);self.factor.fill(0)
                for _,observations in self.history:
                    for i,s,f in observations:self.best[i]=max(self.best[i],s);self.factor[i]=max(self.factor[i],f)
        bulletin=snapshot.get("latest_bulletin") or {}
        stamp=bulletin.get("issued_at_utc","")
        if stamp not in self.reported and any(x.get("event_kind")=="instrument_fault" for x in bulletin.get("notices",[])):
            self.reported.add(stamp);return {"action":"report"}
        t=int(np.searchsorted(c.stamps,ts,side="right")-1)
        if t<0:return {"action":"wait","until_utc":c.times[0].strftime("%Y-%m-%dT%H:%M:%SZ")}
        if ts >= c.stamps[t]+900:
            if t+1>=len(c.times):return {"action":"finish"}
            return {"action":"wait","until_utc":c.times[t+1].strftime("%Y-%m-%dT%H:%M:%SZ")}
        alt,az=c.altaz(now)
        altend,_=c.altaz(now+timedelta(seconds=900))
        visible=np.minimum(alt,altend)>=30
        # No weather truth: generic posterior mean until enough direct observation
        # feedback is available. Lunar factor is public astronomy and can be computed.
        geom=c.geometric_quality((alt+altend)/2)
        mra,mdec,illum,malt=_lunar_geometry(now+timedelta(seconds=450),float(c.site["latitude_deg"]),c.lon)
        rho=np.degrees(np.arccos(np.clip(np.sin(np.radians(mdec))*c.sin_dec+
            np.cos(np.radians(mdec))*c.cos_dec*np.cos(np.radians(mra-c.ra)),-1,1)))
        lunar=1-.75*illum*np.sin(np.radians(max(0,malt)))*np.exp(-rho/35)
        q=.8*geom*lunar
        predicted_factor=np.minimum(1,c.flux*q/.5)
        program="DARK" if np.median(q[visible])>=.65 else "BRIGHT" if np.median(q[visible])>=.4 else "BACKUP"
        mult=c.score["program"]["multipliers"][program]
        science=np.maximum(c.weight*predicted_factor*mult-self.best,0)
        req=c.req*(self.factor<.5)*(predicted_factor>=.5)
        if self.nn:
            pred=self.nn(c.features(t,self.factor,self.best))
            # Estimated loss from postponement; lower future recoverability raises
            # current completion priority. Science head discounts easy repeat gains.
            scarcity=1+self.strength*(1-pred[:,0]) if self.control=="boost" else np.clip(1-self.strength*pred[:,0],.15,1)
            utility=science*(1-.25*pred[:,1])+50*req*scarcity
        else:utility=science+50*req
        # Required bonus only crosses the threshold; real terminal Jain derivative.
        done=self.factor>=.5
        banddone=np.bincount(c.band,weights=done,minlength=36)
        ratios=np.divide(banddone,c.bandtot,out=np.zeros(36),where=c.bandtot>0)
        active=c.bandtot>0;nb=active.sum();a=ratios[active].sum();b=(ratios[active]**2).sum()
        if b>0:
            grad=np.maximum(0,200*(2*a/(nb*b)-2*a*a*ratios/(nb*b*b)))
            ugrad=np.divide(grad,c.bandtot,out=np.zeros(36),where=c.bandtot>0)
        else:ugrad=np.ones(36)
        utility+=ugrad[c.band]*(~done)*(predicted_factor>=.5)
        for reqmsg in snapshot.get("active_requests",[]):
            left=int(reqmsg["minimum_completed"])-int(reqmsg.get("completed_count",0))
            if left<=0:continue
            comp=set(reqmsg.get("completed_target_ids",[]))
            hrs=max(1.,(utc(reqmsg["deadline_utc"])-now).total_seconds()/3600)
            for sid in reqmsg["target_ids"]:
                if sid not in comp and sid in c.index:
                    i=c.index[sid]
                    if predicted_factor[i]>=reqmsg["completion_factor_threshold"]:
                        utility[i]+=float(reqmsg["completion_reward"])/max(1,left)*(1+2/hrs)
        utility*=visible
        # Shortlist field anchors by individual and neighborhood utility. Spatial
        # groups shortlist only; final assignments use exact gnomonic projection.
        gscore=np.bincount(c.group,weights=utility,minlength=len(c.groups))
        topgroups=np.argsort(gscore)[-12:]
        anchors=[]
        for g in topgroups:
            ix=c.groups[int(g)];anchors.extend(ix[np.argsort(utility[ix])[-2:]].tolist())
        anchors.extend(np.argsort(utility)[-8:].tolist())
        bestval=-1;bestaction=None
        a=np.radians(alt);z=np.radians(az)
        vec=np.column_stack([np.cos(a)*np.cos(z),np.cos(a)*np.sin(z),np.sin(a)])
        half=math.sqrt(.4)*2;pitch=math.sqrt(.4)
        for anchor in set(anchors):
            if utility[anchor]<=0:continue
            # Put anchor into one of the central fibers instead of on a seam.
            for da,dz in [(pitch/2,pitch/2),(-pitch/2,-pitch/2)]:
                ca=float(np.clip(alt[anchor]+da,0,89.999));cz=float((az[anchor]+dz/max(.05,math.cos(a[anchor])))%360)
                ar,zr=math.radians(ca),math.radians(cz)
                center=np.array([math.cos(ar)*math.cos(zr),math.cos(ar)*math.sin(zr),math.sin(ar)])
                depth=vec@center
                ix=np.where((depth>math.cos(math.radians(1.9)))&visible&(utility>0))[0]
                if not len(ix):continue
                up=np.array([-math.sin(ar)*math.cos(zr),-math.sin(ar)*math.sin(zr),math.cos(ar)])
                right=np.array([-math.sin(zr),math.cos(zr),0.])
                y=(vec[ix]@up/depth[ix])*180/math.pi;x=(vec[ix]@right/depth[ix])*180/math.pi
                ins=(np.abs(y)<half-1e-7)&(np.abs(x)<half-1e-7)
                ix=ix[ins];x=x[ins];y=y[ins]
                fiber=np.floor(y/pitch+2).astype(int)*4+np.floor(x/pitch+2).astype(int)
                assignments={};val=0.
                for f in np.unique(fiber):
                    candidates=ix[fiber==f];i=int(candidates[np.argmax(utility[candidates])])
                    assignments[str(int(f))]=c.ids[i];val+=float(utility[i])
                if val>bestval:
                    bestval=val;bestaction={"action":"observe","pointing":{"alt_deg":ca,"az_deg":cz},
                        "assignments":assignments,"duration_seconds":900,"program":program}
        return bestaction or {"action":"wait","duration_seconds":900}


def evaluate(cards, strength=.75,control="boost"):
    OUT.mkdir(parents=True,exist_ok=True)
    summary=[]
    for card in cards:
        for mode in ["greedy","neural"]:
            begin=time.monotonic()
            path=UPSTREAM/"local-cards"/card/"config/v4_scenario.json"
            report=run_scenario(path,lambda ctx:ColdAgent(ctx,card,mode=="neural",strength,control),OUT/f"official_{mode}_{control}_{card}")
            entry={"card":card,"mode":mode,"control":control,"strength":strength,"total":report["total"],"components":report["components"],
                "counts":report["counts"],"termination":report["termination"],"seconds":time.monotonic()-begin}
            summary.append(entry);print(json.dumps(entry),flush=True)
            (OUT/"official_summary.json").write_text(json.dumps(summary,indent=2))


def main():
    p=argparse.ArgumentParser();p.add_argument("command",choices=["generate","train","evaluate","all"])
    p.add_argument("--episodes",type=int,default=12);p.add_argument("--epochs",type=int,default=24)
    p.add_argument("--cards",nargs="+",default=["L3","L4"]);p.add_argument("--strength",type=float,default=.75)
    p.add_argument("--control",choices=["boost","discount"],default="boost")
    a=p.parse_args()
    if a.command in ["generate","all"]:generate(a.episodes)
    if a.command in ["train","all"]:train(a.epochs)
    if a.command in ["evaluate","all"]:evaluate(a.cards,a.strength,a.control)


if __name__=="__main__":main()
