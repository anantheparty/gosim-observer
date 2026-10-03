"""Locked native participant with optional public same-slot planning constraint."""
import copy
import json
import os
import sys

os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
import numpy as np
import policy
from research.geometry_native import load_library
from research.candidate_geometry_sweep import CandidateGeometryPlanner
from research.geometry import parse_utc
from research.band_identification_runtime import PublicSlotConstraint

load_library()
policy.SpatialPlanner=CandidateGeometryPlanner
BasePolicy=policy.Policy
MODE=os.environ.get('BAND_IDENTIFICATION_MODE','control')
if MODE not in ('control','constraint'):raise ValueError(MODE)


class SameSlotPolicy(BasePolicy):
    def __init__(self,initial):
        super().__init__(initial)
        self.band_constraint=PublicSlotConstraint(initial)
        self.band_seen=set();self.band_begin_bulletin=None;self.band_snapshot=None
        choose=self.planner.choose

        def constrained_choose(snapshot,scores,factors,env_estimate=None,active_requests=None):
            env=dict(env_estimate or {});q0=float(self.initial['scoring']['q0'])
            c=float(env['program_band_quality_scale'])/q0
            e=float(env['quality_scale'])/(q0*c)
            correction=self.band_constraint.constrain(parse_utc(snapshot['now_utc']),c,e)
            if correction is not None and MODE=='constraint':
                env.update(program_band_quality_scale=correction[0]*q0,
                           quality_scale=correction[0]*correction[1]*q0)
            action=choose(snapshot,scores,factors,env,active_requests)
            if correction is not None:
                print(json.dumps(dict(event='band_constraint_projection',mode=MODE,
                    observe_action_index=snapshot.get('observe_action_index'),now_utc=snapshot['now_utc'],
                    C=c,E=e,projected_C=correction[0],projected_E=correction[1],
                    source_indices=self.band_constraint.indices[:],programs=sorted(self.band_constraint.programs),
                    action=action),separators=(',',':')),file=sys.stderr,flush=True)
            return action

        self.planner.choose=constrained_choose

    def _ingest_result(self,snapshot):
        pending=self.pending;result=snapshot.get('last_result') or {}
        super()._ingest_result(snapshot)
        if result.get('action')=='report':
            self.band_constraint.clear();return
        if result.get('action')!='observe' or not pending:return
        index=result.get('observe_index')
        if index is None or int(index) in self.band_seen:return
        self.band_seen.add(int(index))
        action=pending['action'];start=pending['start'];end=parse_utc(snapshot['now_utc'])
        duration=min(float(action['duration_seconds']),(end-start).total_seconds())
        hits=[h for h in result.get('hits',[]) if str(h.get('target_id')) in self.planner.index]
        records=[]
        if 0<duration<=120 and hits:
            idx=np.asarray([self.planner.index[str(h['target_id'])] for h in hits],int)
            H=self._geometric_H(start,duration,idx)
            records=[dict(score=float(h['score']),weight=float(self.planner.weight[i]),
                          flux=float(self.planner.flux[i]),H=float(hh)) for h,i,hh in zip(hits,idx,H)]
        self.band_constraint.ingest(start,end,action['program'],int(index),records,self.band_begin_bulletin)

    def decide(self,snapshot):
        self.band_snapshot=snapshot
        action=super().decide(snapshot)
        if action.get('action')=='observe':
            self.band_begin_bulletin=copy.deepcopy(snapshot.get('latest_bulletin'))
        return action

    def summary(self):
        return {**super().summary(),'band_identification_mode':MODE,
                'band_identification_stats':self.band_constraint.stats,
                'geometry':self.planner.geometry_summary}


policy.Policy=SameSlotPolicy
from agent import main
if __name__=='__main__':main()
