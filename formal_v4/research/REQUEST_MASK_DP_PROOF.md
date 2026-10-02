# Finite-column request completion

`request_mask_dp.py` solves one request with at most eight target bits, quorum
`k`, and an initial completed mask `M0`. Each supplied `RequestColumn` certifies
the targets completed by a fixed positive-duration action and gives its finite,
nonnegative opportunity cost. The caller supplies geometry, exposure
certificates, and any science opportunity cost. The optimizer adds no science
gain and gives no partial request reward.

## API

```python
columns = [RequestColumn(start, end, completion_mask, opportunity_cost, tag)]
plan = solve_request_columns(
    columns,
    target_count=m,
    quorum=k,
    completed_mask=M0,
    now=now_seconds,           # optional
    deadline=deadline_seconds, # optional; completion at the boundary is valid
)
decision = compare_request_reward(plan, reward=R)
```

Times use one finite numeric clock; normalize datetimes before calling. Only
columns starting at or after `now` and ending at or before `deadline` are
eligible. Intervals are `[start, end)`, so adjacent actions are compatible.
`tag` is an arbitrary unchanged payload. `plan.chosen_indices` are original
input indices in chronological order. Feasible output has minimum total cost
and a final mask with at least `k` bits. Infeasible output has cost infinity,
empty indices, and final mask `M0`. Already completed requests return cost zero
and no actions.

## Exactness

Sort every eligible start and end time into events `t0 < ... < t(E-1)`. Create
a vertex `(event, mask)` for every event and every request mask. Add zero-cost
waiting edges `(i, M) -> (i+1, M)`. For every column from event `i` to event `j`,
add an edge `(i, M) -> (j, M | column_mask)` with its opportunity cost. Positive
duration makes every edge advance in event time, so this graph is a DAG.

Every non-overlapping schedule corresponds to a path from `(0, M0)`: wait to
the first start, take its column edge, and continue. Conversely, column edges
along a path form a non-overlapping schedule because their starts cannot
precede the previous edge's end. Inductively, the path's mask is exactly the
union of `M0` and its selected column masks; repeating a target adds no bit.
The path cost is exactly the sum of selected opportunity costs. A column that
adds no new bit can be replaced by waiting, with cost no greater, so dropping
those transitions preserves an optimum.

The DP processes vertices in event order, relaxing waiting and column edges.
The usual DAG shortest-path induction therefore gives the minimum path cost
to every `(event, mask)`. Minimize at the last event over masks with at least
`k` bits. Waiting carries earlier completed paths to that event, so this
returns exactly the minimum feasible completion cost. If no such state is
reachable, the request is infeasible; a partial mask cannot pass this test.

The single request contributes `R` exactly once on full completion. Thus the
best incremental utility is `max(0, R - min_cost)` when completion is feasible,
and zero otherwise. `compare_request_reward` selects doing nothing on zero
ties. If the reward was already paid, pass only its remaining incremental
value.

## Cost and checks

Endpoint sorting takes `O(C log C)`. The event/mask DP takes
`O((E + C) * 2^m)` time and `O(E * 2^m + C)` storage, including reconstruction.
Costs use ordinary floating-point arithmetic; accumulated overflow raises an
explicit error. Exactness is for the supplied finite column model, not for
unmodeled pointing choices or changing completion certificates.

Run `python formal_v4/research/request_mask_dp_checks.py`. It checks adjacent
and overlapping exposures, original indices after filtering, inclusive
deadline boundaries, repeated masks, existing completion, infeasibility,
reward comparison, input validation, and 700 seeded random instances with at
most ten columns against independent enumeration of every subset.
