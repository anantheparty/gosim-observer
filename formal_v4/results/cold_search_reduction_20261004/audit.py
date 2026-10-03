#!/usr/bin/env python3
"""Public-geometry target retirement and official-ledger quotient micro audit.

No agent run, submission, remote task, or truth-driven candidate selection. Local
raw factors are used solely to check payoff bookkeeping against recorded ledgers.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from datetime import datetime, timedelta

import numpy as np

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
UP = ROOT / "upstream/gosim-observer-examples"
sys.path.insert(0, str(UP / "runner"))
from challenge.v4_runner import load_scenario
from challenge.v4_scorer import BestLedger, required_penalty, uniformity_penalty, observation_request_status
from challenge.tile_geometry_simulator import _local_sidereal_deg
from challenge.v4_fiber_map import SIDEREAL_DEGREES_PER_DAY, radec_to_altaz


def utc(x):
    return datetime.fromisoformat(x.replace("Z", "+00:00"))


def rows(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def max_altitudes(targets, start, end, site):
    """Endpoint / upper-culmination analytic upper bound for this exact LST model."""
    ra = np.array([float(t["ra_deg"]) for t in targets])
    dec = np.radians([float(t["dec_deg"]) for t in targets])
    lat = math.radians(float(site["latitude_deg"]))
    a = math.sin(lat) * np.sin(dec)
    b = math.cos(lat) * np.cos(dec)
    h0 = (_local_sidereal_deg(start, site["longitude_deg"]) - ra) % 360
    h1 = (_local_sidereal_deg(end, site["longitude_deg"]) - ra) % 360
    sine = np.maximum(a + b*np.cos(np.radians(h0)), a + b*np.cos(np.radians(h1)))
    sweep = SIDEREAL_DEGREES_PER_DAY * (end-start).total_seconds() / 86400
    transit = ((-h0) % 360) <= sweep + 1e-8
    sine[transit] = a[transit] + b[transit]
    return np.degrees(np.arcsin(np.clip(sine, -1, 1)))


def retirement(targets, now, nights, site, min_alt, max_duration):
    # Observe can start in a daytime gap and finish after observing_start, hence
    # expand the start of every positive-weather interval by max_duration.
    highest = np.full(len(targets), -90.)
    intervals = []
    for night in nights:
        end = utc(night["observing_end_utc"])
        if end <= now:
            continue
        start = max(now, utc(night["observing_start_utc"])-timedelta(seconds=max_duration))
        if start < end:
            intervals.append((start, end))
            highest = np.maximum(highest, max_altitudes(targets, start, end, site))
    # A 1e-7 degree tolerance conservatively retains boundary targets. This is a
    # float64 implementation of the analytic proof, not interval arithmetic.
    return highest < min_alt - 1e-7, highest, intervals


def make_ledger(obs, decisions, cut=None):
    ledger = BestLedger()
    for r in obs:
        d = decisions[int(r["observe_index"])]
        if r["valid"] != "true" or (cut is not None and utc(d["end_utc"]) > cut):
            continue
        ledger.record(int(r["observe_index"]), r["target_id"], float(r["factor"]), float(r["score"]),
                      utc(d["start_utc"]), utc(d["end_utc"]))
    return ledger


def terminal(ledger, targets, cfg, requests):
    science = sum(x[1] for x in ledger.best().values())
    f = ledger.max_factors()
    missing, req = required_penalty(targets, f, cfg)
    band, unif = uniformity_penalty(targets, f, cfg)
    reward = sum(observation_request_status(q, ledger)["reward"] for q in requests)
    return dict(science=science, required_missing=missing, required_cost=req,
                bands=band, uniformity_cost=unif, request_reward=reward,
                payoff=science-req-unif+reward)


def summary(ledger, targets, cfg, requests, now, retired):
    ids = [t["target_id"] for t in targets]
    best = ledger.best()
    factors = ledger.max_factors()
    b = np.array([best.get(i, (0., 0.))[1] for i in ids], dtype=np.float64)
    r = np.array([factors.get(i, 0.) >= cfg["required"]["observed_factor_threshold"] for i in ids])
    u = np.array([factors.get(i, 0.) >= cfg["uniformity"]["observed_factor_threshold"] for i in ids])
    required = np.array([t["required"] for t in targets])
    band = np.array([int(t["ra_deg"] // cfg["uniformity"]["ra_band_width_deg"]) for t in targets])
    groups = np.unique(band)
    totals = np.array([np.sum(band == k) for k in groups], dtype=np.int32)
    fixed_obs = np.array([np.sum(retired & (band == k) & u) for k in groups], dtype=np.int32)
    fixed_missing = int(np.sum(retired & required & ~r))
    fixed_science = float(np.sum(b[retired]))
    expired_reward = 0.
    active = []
    for q in requests:
        if q["issued_at_utc"] > now:
            continue
        stat = observation_request_status(q, ledger)
        if q["deadline_utc"] <= now or stat["completed"]:
            expired_reward += stat["reward"]
            continue
        qf = ledger.request_factors(q["issued_at_utc"], q["deadline_utc"])
        members = set(q["target_ids"])
        done = np.array([i in members and qf.get(i, 0.) >= q["completion_factor_threshold"] for i in ids])
        fixed_done = int(np.sum(retired & done))
        pending_live = sum((not retired[j]) and ids[j] in members and not done[j] for j in range(len(ids)))
        if stat["completed_count"] + pending_live < q["minimum_completed"]:
            continue  # permanently impossible request, zero payoff
        active.append((q, done[~retired].copy(), fixed_done))
    live = ~retired
    state = dict(ids=np.array(ids)[live], b=b[live].copy(), r=r[live].copy(), u=u[live].copy(),
                 required=required[live], band=band[live], groups=groups, totals=totals,
                 fixed_obs=fixed_obs, fixed_missing=fixed_missing, fixed_science=fixed_science,
                 request_constant=expired_reward, active=active)
    # Static ID/required/band/total/membership maps are shared between search nodes.
    full_nbytes = b.nbytes+r.nbytes+u.nbytes+sum(len(ids) for _ in active)
    compressed_nbytes = state["b"].nbytes+state["r"].nbytes+state["u"].nbytes+fixed_obs.nbytes+24
    compressed_nbytes += sum(done.nbytes+4 for q,done,c in active)
    state["full_dynamic_nbytes"] = full_nbytes
    state["compressed_dynamic_nbytes"] = compressed_nbytes
    return state


def state_terminal(state, cfg):
    science = state["fixed_science"] + float(np.sum(state["b"]))
    missing = state["fixed_missing"] + int(np.sum(state["required"] & ~state["r"]))
    counts = state["fixed_obs"].copy()
    for j,k in enumerate(state["groups"]):
        counts[j] += np.sum((state["band"] == k) & state["u"])
    ratios = counts / state["totals"]
    squares = float(np.sum(ratios**2))
    jain = 0. if squares == 0 else float(np.sum(ratios)**2 / (len(ratios)*squares))
    unif = cfg["uniformity"]["weight"] * (1-jain)
    reward = state["request_constant"] + sum(q["completion_reward"] for q,d,c in state["active"]
                                              if c+int(np.sum(d)) >= q["minimum_completed"])
    return science - missing*cfg["required"]["penalty_per_missing"] - unif + reward


def geometry_dense_check(targets, intervals, site, highest):
    worst = 0.
    samples = 0
    for start,end in intervals:
        for t in targets[::53]:
            idx = int(t["_index"])
            for k in range(31):
                moment = start+(end-start)*k/30
                alt,_ = radec_to_altaz(t["ra_deg"],t["dec_deg"],moment,
                                      site["latitude_deg"],site["longitude_deg"])
                worst = max(worst, alt-highest[idx])
                samples += 1
    assert worst < 1e-7, worst
    return samples,worst


def run_card(card, folder):
    begun = time.perf_counter()
    sc = load_scenario(UP/"local-cards"/card/"config/v4_scenario.json")
    targets = [dict(t,_index=i) for i,t in enumerate(sc.targets)]
    nights_path = UP/"local-cards"/card/"public/v4_night_calendar.csv"
    nights = rows(nights_path)
    obs = rows(folder/"observations.csv")
    decisions = {int(d["observe_index"]):d for d in rows(folder/"decisions.csv") if d["action"] == "observe"}
    messages = [json.loads(x) for x in (folder/"messages.jsonl").read_text().splitlines()]
    loss_times = [utc(m["issued_at_utc"]) for m in messages if m.get("record_type") == "state_resync"]
    final = make_ledger(obs, decisions)
    final_terminal = terminal(final, targets, sc.score_config, sc.observation_requests)
    calendar_end = utc(nights[-1]["observing_end_utc"])
    probes = [("last_7_nights",utc(nights[-7]["observing_start_utc"])),
              ("last_night_start",utc(nights[-1]["observing_start_utc"])),
              ("4h_remaining",calendar_end-timedelta(hours=4)),
              ("1h_remaining",calendar_end-timedelta(hours=1)),
              ("15m_remaining",calendar_end-timedelta(minutes=15))]
    results = []
    for label,requested_now in probes:
        # Choose an actual decision boundary, so no exposure is partly in prefix.
        now = min((utc(d["start_utc"]) for d in decisions.values() if utc(d["start_utc"])>=requested_now), default=calendar_end)
        if loss_times and now < max(loss_times):
            results.append(dict(label=label,status="skipped_pre_loss"))
            continue
        retired,highest,intervals = retirement(targets,now,nights,sc.site,sc.minimum_altitude_deg,
                sc.fiber_config["exposure"]["max_duration_seconds"])
        samples,worst = geometry_dense_check(targets,intervals,sc.site,highest)
        prefix = make_ledger(obs, decisions, now)
        state = summary(prefix,targets,sc.score_config,sc.observation_requests,now,retired)
        prefix_payoff = terminal(prefix,targets,sc.score_config,[q for q in sc.observation_requests if q["issued_at_utc"]<=now])["payoff"]
        assert abs(prefix_payoff-state_terminal(state,sc.score_config)) < 1e-8
        lookup = {t["target_id"]:i for i,t in enumerate(targets)}
        violations = [r for r in obs if r["valid"]=="true" and utc(decisions[int(r["observe_index"])]["start_utc"])>=now
                      and retired[lookup[r["target_id"]]] and float(r["factor"])>0]
        assert not violations
        final_state = summary(final,targets,sc.score_config,sc.observation_requests,calendar_end,retired)
        assert abs(final_terminal["payoff"]-state_terminal(final_state,sc.score_config)) < 1e-8
        # Arbitrary positive updates on all live targets supersets the legal future
        # actions. This checks nonlinear Jain and raw-factor threshold bookkeeping.
        rng = np.random.default_rng(20261004)
        ids = state["ids"].tolist()
        error = 0.
        arbitrary_cases = 100
        for trial in range(arbitrary_cases):
            candidate = make_ledger(obs,decisions,now)
            for z in range(min(100,len(ids))):
                target = ids[int(rng.integers(len(ids)))]
                g = float(rng.choice([0.,.49,.5,.51,1.]))
                c = float(rng.uniform(0,3))
                candidate.record(100000+trial*100+z,target,g,c,now,now+timedelta(seconds=60))
            compressed = summary(candidate,targets,sc.score_config,sc.observation_requests,now,retired)
            a = terminal(candidate,targets,sc.score_config,[q for q in sc.observation_requests if q["issued_at_utc"]<=now])["payoff"]
            error = max(error,abs(a-state_terminal(compressed,sc.score_config)))
        assert error < 1e-8
        results.append(dict(label=label,now_utc=now.isoformat(),retired_targets=int(np.sum(retired)),
                            live_targets=int(np.sum(~retired)),total_targets=len(targets),
                            retired_fraction=float(np.mean(retired)),
                            full_dynamic_nbytes=state["full_dynamic_nbytes"],
                            compressed_dynamic_nbytes=state["compressed_dynamic_nbytes"],
                            storage_reduction=1-state["compressed_dynamic_nbytes"]/state["full_dynamic_nbytes"],
                            active_unresolved_requests=len(state["active"]),
                            future_positive_retired_hit_violations=0,geometry_samples=samples,
                            sampled_altitude_excess_deg=worst,arbitrary_future_cases=arbitrary_cases,
                            max_payoff_error=error))
    return dict(card=card,seconds=time.perf_counter()-begun,loss_messages=len(loss_times),
                scope="Public-geometry certificate; recorded six-decimal factors used only as offline bookkeeping teacher; no fresh full replay or policy gain.",
                cases=results,input_sha256={str(p.relative_to(ROOT)):sha(p) for p in
                    [nights_path,UP/"local-cards"/card/"public/targets.csv",folder/"observations.csv",folder/"decisions.csv",folder/"messages.jsonl"]})


def counterexamples():
    # RA counts, not merely total completions, are essential for future Jain.
    def jain(x):
        return sum(x)**2/(len(x)*sum(a*a for a in x))
    # Equal current Jain=.9, but identical future additions have different values.
    left = [.5,.25]
    right = [.25,.5]
    return dict(equal_current_jain=jain(left),same_current_jain=jain(right),
                after_adding_second_band_left=jain([.5,.5]),
                after_adding_second_band_right=jain([.25,.75]),
                conclusion="Scalar Jain/current payoff cannot replace per-band retired counts.")


def main():
    began=time.perf_counter()
    folders={"L1":ROOT/"results/geometry_native_20261003/protocol_gate_remaining/L1",
             "L2":ROOT/"results/geometry_native_20261003/protocol_gate_retry/L2",
             "L3":ROOT/"results/geometry_native_20261003/protocol_gate_remaining/L3",
             "L4":ROOT/"results/geometry_native_20261003/protocol_gate_retry/L4"}
    result=dict(scope="Exact conditional payoff quotient micro audit; prior single-window theorem was duplicate and not rerun.",
                counterexamples=counterexamples(),cases=[run_card(c,p) for c,p in folders.items()])
    result["seconds"]=time.perf_counter()-began
    result["source_sha256"]=sha(Path(__file__))
    (OUT/"summary.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(dict(seconds=result["seconds"],cases=[dict(card=x["card"],cases=x["cases"]) for x in result["cases"]]),indent=2))


if __name__ == "__main__":
    main()
