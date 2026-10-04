"""Exact minimum opportunity cost for one request over fixed exposure columns.

Only request completion is modeled here.  In particular, per-column science
gains are never added: the caller supplies each column's nonnegative opportunity
cost and assigns each request target one of at most eight bit positions.
"""

from dataclasses import dataclass
from math import inf, isfinite
from numbers import Integral, Real
from typing import Any, Iterable, Optional, Tuple


MAX_REQUEST_TARGETS = 8


@dataclass(frozen=True)
class RequestColumn:
    """One fixed action, with interval ``[start, end)`` in numeric seconds.

    ``completion_mask`` contains targets that this entire action completes for
    the request.  The geometry/exposure model must supply this certificate.
    ``tag`` is opaque payload for the caller and does not affect optimization.
    """

    start: float
    end: float
    completion_mask: int
    opportunity_cost: float
    tag: Any = None


@dataclass(frozen=True)
class RequestPlan:
    """Minimum-cost complete schedule, or an explicit infeasible result.

    ``chosen_indices`` are original input indices, in chronological order.
    On infeasibility they are empty, ``min_cost`` is infinity, and ``final_mask``
    is the input completed mask.  No partially completed schedule is returned.
    """

    feasible: bool
    min_cost: float
    chosen_indices: Tuple[int, ...]
    final_mask: int


@dataclass(frozen=True)
class RequestRewardDecision:
    """Compare the complete request's reward minus cost with doing nothing.

    Zero-value ties choose doing nothing, represented by empty indices.
    """

    pursue: bool
    net_value: float
    chosen_indices: Tuple[int, ...]


def _integer(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{name} must be an integer")
    return int(value)


def _seconds(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a finite real number")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def solve_request_columns(
    columns: Iterable[RequestColumn],
    *,
    target_count: int,
    quorum: int,
    completed_mask: int = 0,
    now: Optional[float] = None,
    deadline: Optional[float] = None,
) -> RequestPlan:
    """Find a minimum-cost non-overlapping schedule reaching the quorum.

    Target bits are ``0 .. target_count - 1`` and ``0 <= quorum <= target_count
    <= 8``.  Every column must have positive duration and finite, nonnegative
    cost.  Times must already share one numeric clock; normalize datetimes in
    the caller.  The optional bounds retain columns with ``start >= now`` and
    ``end <= deadline``, inclusively.  An expired window is infeasible unless
    the supplied completed mask already reaches quorum.  Equal-cost ties are
    deterministic but have no additional objective.

    The DP uses the event-time DAG crossed with the completion masks.  After
    sorting endpoints, runtime is O((E + C) * 2**target_count), with O(E *
    2**target_count + C) storage.  Endpoint preprocessing is O(C log C).
    """
    target_count = _integer(target_count, "target_count")
    quorum = _integer(quorum, "quorum")
    completed_mask = _integer(completed_mask, "completed_mask")
    if not 0 <= target_count <= MAX_REQUEST_TARGETS:
        raise ValueError("target_count must be between zero and eight")
    if not 0 <= quorum <= target_count:
        raise ValueError("quorum must be between zero and target_count")
    mask_count = 1 << target_count
    if not 0 <= completed_mask < mask_count:
        raise ValueError("completed_mask has a bit outside the request targets")
    now = None if now is None else _seconds(now, "now")
    deadline = None if deadline is None else _seconds(deadline, "deadline")

    eligible = []
    for original_index, column in enumerate(columns):
        if not isinstance(column, RequestColumn):
            raise TypeError("columns must contain RequestColumn instances")
        start = _seconds(column.start, f"columns[{original_index}].start")
        end = _seconds(column.end, f"columns[{original_index}].end")
        cost = _seconds(
            column.opportunity_cost,
            f"columns[{original_index}].opportunity_cost",
        )
        completion_mask = _integer(
            column.completion_mask, f"columns[{original_index}].completion_mask"
        )
        if end <= start:
            raise ValueError("columns must have positive duration")
        if cost < 0:
            raise ValueError("column opportunity costs must be nonnegative")
        if not 0 <= completion_mask < mask_count:
            raise ValueError("column completion_mask has a bit outside the request targets")
        if now is not None and start < now:
            continue
        if deadline is not None and end > deadline:
            continue
        eligible.append((start, end, completion_mask, cost, original_index))

    if completed_mask.bit_count() >= quorum:
        return RequestPlan(True, 0.0, (), completed_mask)
    infeasible = RequestPlan(False, inf, (), completed_mask)
    if not eligible or (now is not None and deadline is not None and now > deadline):
        return infeasible

    event_times = sorted({time for col in eligible for time in col[:2]})
    event_index = {time: i for i, time in enumerate(event_times)}
    outgoing = [[] for _ in event_times]
    for start, end, completion_mask, cost, original_index in eligible:
        outgoing[event_index[start]].append(
            (event_index[end], completion_mask, cost, original_index)
        )

    costs = [[inf] * mask_count for _ in event_times]
    previous = [[None] * mask_count for _ in event_times]
    costs[0][completed_mask] = 0.0

    for event, actions in enumerate(outgoing):
        current = costs[event]
        if event:
            for mask, prior_cost in enumerate(costs[event - 1]):
                if prior_cost < current[mask]:
                    current[mask] = prior_cost
                    previous[event][mask] = (event - 1, mask, -1)
        for end_event, completion_mask, column_cost, original_index in actions:
            destination = costs[end_event]
            for mask, prior_cost in enumerate(current):
                if not isfinite(prior_cost):
                    continue
                new_mask = mask | completion_mask
                # Such an action cannot improve cost or target completion.
                if new_mask == mask:
                    continue
                new_cost = prior_cost + column_cost
                if not isfinite(new_cost):
                    raise OverflowError("accumulated opportunity cost exceeds finite float range")
                if new_cost < destination[new_mask]:
                    destination[new_mask] = new_cost
                    previous[end_event][new_mask] = (event, mask, original_index)

    final_costs = costs[-1]
    complete_masks = (mask for mask in range(mask_count) if mask.bit_count() >= quorum)
    final_mask = min(complete_masks, key=final_costs.__getitem__)
    min_cost = final_costs[final_mask]
    if not isfinite(min_cost):
        return infeasible

    chosen = []
    event, mask = len(event_times) - 1, final_mask
    while event != 0 or mask != completed_mask:
        prior = previous[event][mask]
        if prior is None:
            raise AssertionError("reachable DP state has no predecessor")
        event, mask, original_index = prior
        if original_index >= 0:
            chosen.append(original_index)
    chosen.reverse()
    return RequestPlan(True, min_cost, tuple(chosen), final_mask)


def compare_request_reward(plan: RequestPlan, reward: float) -> RequestRewardDecision:
    """Choose full completion iff its finite reward strictly exceeds cost.

    Reward is credited once for the entire quorum; there is no per-target or
    per-column reward.  The caller must pass an incremental reward if the
    request has already been paid.  An infeasible plan always chooses nothing.
    """
    reward = _seconds(reward, "reward")
    if reward < 0:
        raise ValueError("reward must be nonnegative")
    if not plan.feasible or reward <= plan.min_cost:
        return RequestRewardDecision(False, 0.0, ())
    return RequestRewardDecision(True, reward - plan.min_cost, plan.chosen_indices)
