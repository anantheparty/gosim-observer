"""One predeclared action intervention followed by complete native replanning.

Participant features use only initialization, delivered snapshots, and the
native policy's public-feedback ledger. Truth is never mounted here.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np
import policy
from research.candidate_geometry_sweep import CandidateGeometryPlanner, PROGRAMS, DEG
from research.geometry import parse_utc, local_sidereal_deg
from research.geometry_native import load_library
from research.spatial_candidates import SpatialPlanner

load_library()
CASE = os.environ.get("POLICY_ITERATION_CASE", "control")
RANK = int(os.environ.get("POLICY_ITERATION_RANK", "64"))
TRACE = os.environ.get("POLICY_ITERATION_TRACE", "0") == "1"
PREFIX_PATH = os.environ.get("POLICY_ITERATION_PREFIX")
PREFIX = [json.loads(line) for line in Path(PREFIX_PATH).read_text().splitlines()] if PREFIX_PATH else []
assert all(int(row["rank"]) < RANK for row in PREFIX), "Prefix tape includes cut/future metadata"
CAPTURE_DIR=Path(os.environ["POLICY_ITERATION_CAPTURE_DIR"]) if "POLICY_ITERATION_CAPTURE_DIR" in os.environ else None
ORIGINAL_EVALUATE = SpatialPlanner._evaluate


def snapshot_hash(snapshot):
    public = {k:v for k,v in snapshot.items() if k != "wallclock"}
    return hashlib.sha256(json.dumps(public,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def public_output(record):
    """Write only the currently reached participant public record to /capture."""
    event=record["event"]
    if CAPTURE_DIR:
        if event=="policy_iteration_public_trace":
            with (CAPTURE_DIR/"public_trace.jsonl").open("a") as handle:
                handle.write(json.dumps(record,separators=(",",":"))+"\n")
        elif event=="policy_iteration_capture":
            capture=dict(record)
            blob=base64.b64decode(capture.pop("feature_blob"))
            (CAPTURE_DIR/"public_features.npz").write_bytes(blob)
            capture["feature_blob_sha256"]=hashlib.sha256(blob).hexdigest()
            (CAPTURE_DIR/"capture.json").write_text(json.dumps(capture,separators=(",",":"))+"\n")
        elif event=="policy_iteration_post_feedback":
            (CAPTURE_DIR/"post_feedback.json").write_text(json.dumps(record,separators=(",",":"))+"\n")
    # Keep stderr comfortably inside the official 64 KiB rolling tail.
    if event!="policy_iteration_public_trace":
        small={k:record[k] for k in ("event","case","rank") if k in record}
        print(json.dumps(small,separators=(",",":")),file=sys.stderr,flush=True)


def recorded_evaluate(self, center, pool, *frame):
    result = ORIGINAL_EVALUATE(self, center, pool, *frame)
    if getattr(self, "pi_capture_evaluations", False) and result is not None:
        self.pi_evaluations.append(result)
    return result


SpatialPlanner._evaluate = recorded_evaluate


class CapturePlanner(CandidateGeometryPlanner):
    def choose(self, snapshot, scores, factors, env_estimate=None, active_requests=None):
        if PREFIX and int(snapshot["observe_action_index"]) < RANK:
            row = PREFIX[self.pi_step]
            assert row["snapshot_sha256"] == snapshot_hash(snapshot), "forced-prefix public snapshot mismatch"
            self.last_prediction = row["prediction"]
            self.terrain_directions = set(row["planner_terrain"])
            self.stats = row["planner_stats"]
            return row["planner_action"]
        self.pi_capture_evaluations = int(snapshot["observe_action_index"]) == RANK
        self.pi_evaluations = []
        self.pi_env = dict(env_estimate or {})
        try:
            return super().choose(snapshot, scores, factors, env_estimate, active_requests)
        finally:
            self.pi_capture_evaluations = False


policy.SpatialPlanner = CapturePlanner
BasePolicy = policy.Policy


def action_hash(action):
    return hashlib.sha256(json.dumps(action, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ReplanningTeacher(BasePolicy):
    def __init__(self, initial):
        super().__init__(initial)
        assert self.remote is None, "Teacher must be the locked native offline policy"
        self.pi_prefix = hashlib.sha256()
        self.pi_done = False
        self.pi_post_feedback = False
        self.pi_suffix = hashlib.sha256()
        self.pi_suffix_calls = 0
        self.pi_capture = None
        self.pi_public_history = []

    def _tuple_action(self, candidate):
        p = self.planner
        _, center, duration, program, chosen, fibers = candidate
        oa = float(p.pi_env.get("pointing_offset_alt_deg", 0))
        oz = float(p.pi_env.get("pointing_offset_az_deg", 0))
        return dict(action="observe", pointing=dict(alt_deg=round(center[0]-oa, 7),
                    az_deg=round((center[1]-oz) % 360, 7)), duration_seconds=int(duration),
                    program=PROGRAMS[int(program)], assignments={str(int(f)):p.ids[int(i)] for i,f in zip(chosen,fibers)})

    def _actions(self, base):
        p = self.planner
        actions = {"control": base}
        # Rank all evaluated physical actions by the frozen public utility.
        # Distinct field choice is declared before seeing any branch feedback.
        for candidate in sorted(p.pi_evaluations, key=lambda x:-x[0]):
            action = self._tuple_action(candidate)
            if not 0 <= action["pointing"]["alt_deg"] <= 90 or not action["assignments"]:
                continue
            dz = abs((action["pointing"]["az_deg"]-base["pointing"]["az_deg"]+180) % 360-180)
            da = abs(action["pointing"]["alt_deg"]-base["pointing"]["alt_deg"])
            if da+dz*np.cos(base["pointing"]["alt_deg"]*DEG) >= .45*p.pitch:
                actions["field"] = action
                break
        for name, scale in (("short", .6), ("long", 1.5)):
            duration = max(p.tmin, min(int(p.frame[12]), int(round(base["duration_seconds"]*scale))))
            assignments = {f:t for f,t in base["assignments"].items() if p.frame[1][p.index[t]]+1e-9 >= duration}
            if assignments and duration != base["duration_seconds"]:
                actions[name] = {**base, "duration_seconds":duration, "assignments":assignments}
        program = PROGRAMS[(PROGRAMS.index(base["program"])+1) % len(PROGRAMS)]
        actions["program"] = {**base, "program":program}
        seen, unique, rejected = set(), {}, []
        for name, action in actions.items():
            key = action_hash(action)
            if key in seen:
                rejected.append({"case":name,"reason":"duplicate_exact_action","hash":key})
            else:
                unique[name]=action
                seen.add(key)
        return unique, rejected

    def _prediction(self, action):
        p = self.planner
        frame, env = p.frame, p.pi_env
        vectors, k = frame[0], frame[2]
        now = self.pending["start"]
        lst = local_sidereal_deg(now, p.lon)
        alt = np.arcsin(np.clip(vectors[:,2], -1, 1))/DEG
        az = np.arctan2(vectors[:,1],vectors[:,0])/DEG % 360
        public = p._public_quality(now, lst, alt)
        qs = max(.005,float(env.get("quality_scale", .55)))
        bs = max(.005,float(env.get("program_band_quality_scale", qs/.95)))
        bands = np.where(public*bs>=p.dark_threshold,0,np.where(public*bs>=p.bright_threshold,1,2))
        quality = k*p.f0t0/np.maximum(p.flux,1e-12)
        tq = np.asarray(env.get("target_quality_scale",np.ones(p.n)))
        directional = quality/np.maximum(1e-12,public*qs*tq)
        return {t:dict(index=p.index[t], fiber_id=int(f), factor=min(1.,float(k[p.index[t]]*action["duration_seconds"])),
                       public_quality=float(public[p.index[t]]), quality=float(quality[p.index[t]]),
                       directional_scale=float(directional[p.index[t]]), predicted_band=PROGRAMS[int(bands[p.index[t]])],
                       alt_deg=float(alt[p.index[t]]),az_deg=float(az[p.index[t]])) for f,t in action["assignments"].items()}

    def _evaluated_utilities(self, actions):
        evaluated={}
        for candidate in self.planner.pi_evaluations:
            key=action_hash(self._tuple_action(candidate))
            evaluated[key]=float(candidate[0])
        return {action_hash(action):dict(evaluated=action_hash(action) in evaluated,
                    native_utility_rate=evaluated.get(action_hash(action)),
                    missing_reason=None if action_hash(action) in evaluated else "This exact pointing/duration/program/assignment was not evaluated")
                for action in actions.values()}

    def _feature_blob(self, snapshot, actions):
        p = self.planner
        now = parse_utc(snapshot["now_utc"])
        alt, az, _, _ = p._altaz(local_sidereal_deg(now,p.lon))
        # Every valid c=w*g*m has m>=m_min, hence max valid g <= best c/(w*m_min).
        # Request completion proofs can strengthen the public lower bound.
        # The existing ledger factor estimate is also public-derived, not truth.
        program_config=self.initial.get("scoring",{}).get("program",{})
        multipliers=list(program_config.get("multipliers",{}).values())+[program_config.get("mismatch_multiplier",1.)]
        minimum_multiplier=min(float(value) for value in multipliers)
        assert minimum_multiplier > 0, "Factor upper bound requires positive public program multipliers"
        factor_upper=np.minimum(1.,np.maximum(self.factor_lower,self.scores/np.maximum(p.weight*minimum_multiplier,1e-12)))
        remaining = np.zeros(p.n)
        visible_nights = np.zeros(p.n)
        # Public geometry support sampled at future night start/middle/end.
        for start,end in p.nights:
            if end <= now:
                continue
            start = max(start,now)
            samples = [start,start+(end-start)/2,end]
            support = np.zeros(p.n,dtype=bool)
            for moment in samples:
                aa,_,_,_ = p._altaz(local_sidereal_deg(moment,p.lon))
                support |= aa >= p.min_alt
            visible_nights += support
            remaining += support*(end-start).total_seconds()
        target = np.column_stack((p.ra/360,p.dec/90,p.flux,p.weight,p.required.astype(float),self.scores,
                    self.factor_lower,self.factors,factor_upper,alt/90,np.sin(az*DEG),np.cos(az*DEG),
                    remaining/86400,visible_nights/len(p.nights)))
        ledger = self.ledger
        nodes = {"target_features":target.astype(np.float32), "scores":self.scores,"factor_lower":self.factor_lower,
                 "factor_estimate":self.factors,"ledger_rank":np.concatenate([np.full(len(x["idx"]),x["observe_index"]) for x in ledger]) if ledger else np.array([],int),
                 "ledger_target":np.concatenate([x["idx"] for x in ledger]) if ledger else np.array([],int),
                 "ledger_score":np.concatenate([x["score"] for x in ledger]) if ledger else np.array([]),
                 "ledger_factor_estimate":np.concatenate([x["factor"] for x in ledger]) if ledger else np.array([]),
                 "ledger_lower":np.concatenate([x["lower"] for x in ledger]) if ledger else np.array([]),
                 "ledger_valid":np.concatenate([np.full(len(x["idx"]),x["valid"]) for x in ledger]) if ledger else np.array([],bool)}
        for name,action in actions.items():
            nodes[name+"_assignment"] = np.asarray([[int(f),p.index[t]] for f,t in action["assignments"].items()],dtype=np.int32)
        stream=io.BytesIO()
        np.savez_compressed(stream,**nodes)
        return base64.b64encode(stream.getvalue()).decode()

    def decide(self, snapshot):
        self.planner.pi_step = self.count
        if PREFIX and int(snapshot["observe_action_index"]) < RANK:
            assert PREFIX[self.count]["snapshot_sha256"] == snapshot_hash(snapshot), "forced-prefix public snapshot mismatch"
        action = super().decide(snapshot)
        rank = int(snapshot["observe_action_index"])
        self.pi_public_history.append(dict(now_utc=snapshot["now_utc"],observe_action_index=rank,
            last_result=snapshot.get("last_result"),new_messages=snapshot.get("new_messages",[]),
            action=action))
        if TRACE:
            public_output(dict(event="policy_iteration_public_trace",step=self.count-1,rank=rank,
                snapshot_sha256=snapshot_hash(snapshot),action=action,
                planner_action=action if self.pending and action.get("action")=="observe" else None,
                prediction=self.pending.get("prediction",{}) if self.pending else {},
                planner_terrain=sorted(self.planner.terrain_directions),planner_stats=self.planner.stats))
        if action.get("action") == "observe" and rank == RANK and not self.pi_done:
            actions,rejected = self._actions(action)
            assert CASE in actions, (CASE, "predeclared candidate unavailable",list(actions))
            evaluated_utilities=self._evaluated_utilities(actions)
            capture = dict(event="policy_iteration_capture",case=CASE,rank=rank,now_utc=snapshot["now_utc"],
                prefix_sha256=self.pi_prefix.hexdigest(),snapshot=snapshot,actions=actions,rejected=rejected,
                baseline_action=action,selected_action=actions[CASE],C=float(self.C),E=float(self.E),
                candidate_predictions={name:self._prediction(candidate) for name,candidate in actions.items()},
                candidate_prediction_provenance="Frozen native public belief, delivered feedback and known geometry; no runner truth",
                candidate_utilities={name:evaluated_utilities[action_hash(candidate)]["native_utility_rate"] for name,candidate in actions.items()},
                evaluated_native_utility_by_action_hash=evaluated_utilities,
                target_ids=list(self.planner.ids),
                target_feature_names=["ra_fraction","dec_fraction","feature_flux","science_weight","required","best_science_score",
                    "max_factor_lower","max_factor_estimate","max_factor_upper_approx","alt_fraction","az_sin","az_cos",
                    "future_visible_days_approx","future_visible_night_fraction_approx"],
                pending_prior_C=float(self.pending["prior_C"]),pending_prior_E=float(self.pending["prior_E"]),
                notices=self.notices,terrain=sorted(self.terrain),false_since_correct=self.false_since_correct,
                request_thresholds=self.request_thresholds,request_completed={k:sorted(v) for k,v in self.request_completed.items()},
                public_history=list(self.pi_public_history),
                calibrator_estimate=list(self.calibrator.estimate) if self.calibrator else None,
                rng_state=self.planner.rng.bit_generator.state if hasattr(self.planner,"rng") else None,
                feature_schema="public-target-ledger-v1",feature_blob=self._feature_blob(snapshot,actions))
            self.pi_capture=copy.deepcopy({k:v for k,v in capture.items() if k!="feature_blob"})
            public_output(capture)
            if CASE != "control":
                action = actions[CASE]
                self.pending["action"] = action
                prediction = self._prediction(action)
                self.pending["prediction"] = prediction
                self.planner.last_prediction = prediction
            self.pi_done = True
        result = snapshot.get("last_result") or {}
        if self.pi_done and not self.pi_post_feedback and result.get("action") == "observe" and result.get("observe_index") == RANK:
            public_output(dict(event="policy_iteration_post_feedback",case=CASE,rank=rank,last_result=result,
                               C=float(self.C),E=float(self.E),scores_sum=float(self.scores.sum())))
            self.pi_post_feedback=True
        canonical = (json.dumps(action,sort_keys=True,separators=(",",":"))+"\n").encode()
        self.pi_prefix.update(canonical)
        if self.pi_done:
            self.pi_suffix.update(canonical)
            self.pi_suffix_calls += 1
        return action

    def summary(self):
        compact_capture={k:self.pi_capture[k] for k in ("case","rank","now_utc","prefix_sha256","feature_schema")} if self.pi_capture else {}
        return {**super().summary(),"pi_case":CASE,"pi_done":self.pi_done,"pi_post_feedback":self.pi_post_feedback,
                "pi_capture":compact_capture,"pi_suffix_sha256":self.pi_suffix.hexdigest(),"pi_suffix_calls":self.pi_suffix_calls,
                "suffix_mode":"natural_locked_native_teacher","forced_prefix":bool(PREFIX),
                "forced_prefix_before_rank":RANK if PREFIX else None,"forced_suffix":False}


policy.Policy = ReplanningTeacher
from agent import main

if __name__ == "__main__":
    main()
