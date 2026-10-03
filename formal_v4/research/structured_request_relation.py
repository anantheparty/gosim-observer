"""Public-only request nodes and target membership; no model, files or labels.

This is an optional, versioned representation supplement. It does not change
the existing student, candidate inventory, teacher, or runner. IDs are used
only to join public records to target/request rows, never as numeric features.
Ledger arrays are deliberately unnecessary: public completed_target_ids are
the authoritative request-window progress available in a decision snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Mapping

import numpy as np

from research.structured_student_features import SchemaError, utc


SCHEMA = "public-request-member-relations-v1"
REQUEST_NAMES = ("minimum_completed", "public_completed_count", "remaining_deficit", "member_count",
                 "completion_factor_threshold", "completion_reward", "seconds_since_issued", "seconds_to_deadline")
MEMBER_NAMES = ("public_completed",)
ACTION_MEMBER_NAMES = ("assigned", "window_eligible", "prediction_present", "predicted_factor", "predicted_new_crossing")
ACTION_REQUEST_NAMES = ("window_eligible", "actual_duration_seconds", "predicted_new_completions", "predicted_complete_now")
COUNT_NAMES = ("public_completed", "predicted_current_new", "conditional_future_support", "remaining_after_current")


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not np.isfinite(value):
        raise SchemaError("Non-finite/non-numeric request relation field: " + name)
    return float(value)


def _integer(value, name):
    number = _number(value,name)
    if number != int(number):
        raise SchemaError("Non-integer request relation field: " + name)
    return int(number)


@dataclass
class RequestActionRelations:
    member_features: np.ndarray  # one row for each request-target edge
    request_features: np.ndarray


@dataclass
class RequestRelations:
    target_ids: tuple[str,...]  # joins/metadata only
    request_ids: tuple[str,...]  # joins/metadata only
    request_nodes: np.ndarray
    member_index: np.ndarray  # columns request row, target row
    member_features: np.ndarray
    actions: dict[str,RequestActionRelations]

    def pool_members(self, target_values, *, action_name=None, extra_member_values=None):
        """Sum inside each request, preserving the request axis for nonlinear heads.

        target_values must follow target_ids. Optional edge-local interactions
        can be appended before pooling. Never pool different requests before
        applying their individual quota/deadline/reward semantics.
        """
        target_values=np.asarray(target_values,float)
        if target_values.ndim!=2 or len(target_values)!=len(self.target_ids) or not np.isfinite(target_values).all():
            raise SchemaError("Target value rows must align to public target joins")
        blocks=[target_values[self.member_index[:,1]],self.member_features]
        if action_name is not None:
            blocks.append(self.actions[action_name].member_features)
        if extra_member_values is not None:
            extra=np.asarray(extra_member_values,float)
            if extra.ndim!=2 or len(extra)!=len(self.member_index) or not np.isfinite(extra).all():
                raise SchemaError("Extra member rows must align to request-target edges")
            blocks.append(extra)
        values=np.column_stack(blocks)
        pooled=np.zeros((len(self.request_ids),values.shape[1]),float)
        np.add.at(pooled,self.member_index[:,0],values)
        return pooled

    def conditional_completion_counts(self, action_name, future_support):
        """Keep public/current/future support counts separate for each request.

        future_support is supplied by a PUBLIC history/action-conditioned
        predictor, not by this adapter or teacher truth. Accept a target
        vector for identical request thresholds/windows, or an (R,N) matrix
        with request-specific threshold/deadline semantics for general cases.
        A sum of marginal completion probabilities is an expected count; its
        threshold is NOT generally a request-completion probability. The tiny
        collision probe uses deterministic 0/1 support from a fixed public pi.
        """
        support=np.asarray(future_support,float)
        n,r=len(self.target_ids),len(self.request_ids)
        if not np.isfinite(support).all() or np.any((support<0)|(support>1)):
            raise SchemaError("Conditional future support must be finite and in [0,1]")
        if support.shape==(n,):
            if r>1 and len(np.unique(self.request_nodes[:,[4,6,7]],axis=0))>1:
                raise SchemaError("Different request thresholds/windows require request-specific future support")
            future_support_at_edge=support[self.member_index[:,1]]
        elif support.shape==(r,n):
            future_support_at_edge=support[self.member_index[:,0],self.member_index[:,1]]
        else:
            raise SchemaError("Future support must align to target vector or request-target matrix")
        completed=self.member_features[:,0]
        current=self.actions[action_name].member_features[:,-1]
        future=future_support_at_edge*(1-completed)*(1-current)
        values=np.column_stack((completed,current,future))
        sums=np.zeros((len(self.request_ids),3),float)
        np.add.at(sums,self.member_index[:,0],values)
        remaining=np.maximum(0,self.request_nodes[:,0]-sums[:,0]-sums[:,1])
        return np.column_stack((sums,remaining))


def build_request_relations(initial: Mapping, capture: Mapping) -> RequestRelations:
    """Use only initialize and delivered capture public fields; no file I/O.

    Empty requests and empty/missing raw ledger arrays are both supported.
    Array row order follows the caller's declared target/request order, so a
    request/target permutation is equivariant, while per-request pooling is
    invariant after aligning the joins. IDs have no learned numeric value.
    """
    initial=initial.get("payload",initial)
    table=initial["targets"]
    id_column=table["columns"].index("target_id")
    catalog_ids=tuple(str(r[id_column]) for r in table["rows"])
    ids=tuple(map(str,capture.get("target_ids",catalog_ids)))
    if len(set(catalog_ids))!=len(catalog_ids) or len(set(ids))!=len(ids) or set(ids)!=set(catalog_ids):
        raise SchemaError("Request relation target joins differ from the public catalog")
    index={tid:i for i,tid in enumerate(ids)}
    snapshot=capture["snapshot"]
    now=utc(snapshot["now_utc"])
    survey_end=utc(initial["survey"]["end_utc"])
    requests=snapshot.get("active_requests",[])
    request_ids=[]
    nodes=[]
    members=[]
    flags=[]
    windows=[]
    for j,r in enumerate(requests):
        rid=str(r["request_id"])
        if rid in request_ids:
            raise SchemaError("Duplicate public request_id")
        request_ids.append(rid)
        tids=tuple(map(str,r["target_ids"]))
        completed=set(map(str,r.get("completed_target_ids",[])))
        if not tids or len(set(tids))!=len(tids) or set(tids)-set(ids) or not completed<=set(tids):
            raise SchemaError("Invalid public request member joins")
        minimum=_integer(r["minimum_completed"],"minimum_completed")
        if not 1<=minimum<=len(tids):
            raise SchemaError("Request quota outside its public member count")
        count=len(completed)
        deficit=max(0,minimum-count)
        if "completed_count" in r and _integer(r["completed_count"],"completed_count")!=count:
            raise SchemaError("Public request completed count disagrees with member list")
        if "remaining_count" in r and _integer(r["remaining_count"],"remaining_count")!=deficit:
            raise SchemaError("Public request remaining count disagrees with quota")
        threshold=_number(r["completion_factor_threshold"],"completion_factor_threshold")
        reward=_number(r["completion_reward"],"completion_reward")
        issued,deadline=utc(r["issued_at_utc"]),utc(r["deadline_utc"])
        if not 0<=threshold<=1 or reward<0 or not issued<deadline or issued>now:
            raise SchemaError("Invalid/undelivered public request window or scoring fields")
        nodes.append([minimum,count,deficit,len(tids),threshold,reward,(now-issued).total_seconds(),(deadline-now).total_seconds()])
        windows.append((issued,deadline))
        for tid in tids:
            members.append((j,index[tid]))
            flags.append([float(tid in completed)])
    request_nodes=np.asarray(nodes,float).reshape((-1,len(REQUEST_NAMES)))
    member_index=np.asarray(members,np.int64).reshape((-1,2))
    member_features=np.asarray(flags,float).reshape((-1,len(MEMBER_NAMES)))
    action_relations={}
    for name,action in capture.get("actions",{}).items():
        if action.get("action")!="observe":
            raise SchemaError("Request relation pilot ranks observe candidates only")
        duration=_integer(action["duration_seconds"],"duration_seconds")
        if duration<=0:
            raise SchemaError("Nonpositive candidate exposure duration")
        actual_end=min(now+timedelta(seconds=duration),survey_end)
        for night in initial["survey"].get("nights",[]):
            night_start,night_end=utc(night["observing_start_utc"]),utc(night["observing_end_utc"])
            if night_start<=now<night_end:
                actual_end=min(actual_end,night_end)
                break
        if actual_end<=now:
            raise SchemaError("Candidate is after the public survey end")
        assigned=set(map(str,action["assignments"].values()))
        if assigned-set(ids) or len(assigned)!=len(action["assignments"]):
            raise SchemaError("Unknown/duplicate candidate target joins")
        predictions=capture.get("candidate_predictions",{}).get(name,{})
        edges=[]
        for (r,i),(completed,) in zip(member_index,member_features):
            tid=ids[i]
            chosen=tid in assigned
            eligible=windows[r][0]<=now and actual_end<=windows[r][1]
            prediction=predictions.get(tid,{}) if chosen else {}
            present="factor" in prediction
            factor=_number(prediction["factor"],"candidate factor") if present else 0.
            if not 0<=factor<=1:
                raise SchemaError("Candidate factor outside [0,1]")
            crossing=chosen and eligible and present and not completed and factor>=request_nodes[r,4]
            edges.append([float(chosen),float(eligible),float(present),factor,float(crossing)])
        edge_features=np.asarray(edges,float).reshape((-1,len(ACTION_MEMBER_NAMES)))
        counts=np.zeros(len(request_ids))
        np.add.at(counts,member_index[:,0],edge_features[:,-1])
        request_features=np.asarray([[float(issued<=now and actual_end<=deadline),(actual_end-now).total_seconds(),
                                     counts[r],float(0<request_nodes[r,2]<=counts[r])]
                                    for r,(issued,deadline) in enumerate(windows)],float).reshape((-1,len(ACTION_REQUEST_NAMES)))
        action_relations[name]=RequestActionRelations(edge_features,request_features)
    return RequestRelations(ids,tuple(request_ids),request_nodes,member_index,member_features,action_relations)
