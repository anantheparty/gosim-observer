"""Exact joint request gates on fixed columns, with a completion-signature quotient.

This optimizes request reward minus supplied additive costs, not full survey score.
All requests must already be published. Future loss, feedback and column generation
are external; rebuilding the graph is required when those inputs change.
"""
from dataclasses import dataclass
from math import inf


@dataclass(frozen=True)
class Column:
    start: float
    end: float
    cost: float
    # Each bit is an occurrence (request_id, target_id), never a target globally.
    occurrences: int
    tag: object = None


def solve(columns, request_occurrences, quorums, rewards, initial=0, quotient=True):
    """Sparse event-time DAG. Costs are nonnegative and fixed before solving.

    request_occurrences[q] is the mask of distinct targets belonging to q.
    A witness inside several request windows sets several occurrence bits.
    Identical future column incidence permits exact OR-state merging, after
    removing already-complete occurrences and unreachable occurrences.
    """
    columns = tuple(columns)
    if len(request_occurrences) != len(quorums) or len(quorums) != len(rewards):
        raise ValueError("inconsistent request vectors")
    union = 0
    for occurrence_mask in request_occurrences:
        if occurrence_mask < 0:
            raise ValueError("negative mask")
        union |= occurrence_mask
    if initial & ~union:
        raise ValueError("initial occurrence outside request universe")
    for col in columns:
        if col.end <= col.start or col.cost < 0 or col.occurrences & ~union:
            raise ValueError("invalid column")
    bases = [(mask & initial).bit_count() for mask in request_occurrences]
    remaining = union & ~initial
    groups = {}
    dead = 0
    for bit in range(union.bit_length()):
        if not remaining & (1 << bit):
            continue
        signature = tuple(i for i, col in enumerate(columns) if col.occurrences & (1 << bit))
        if not signature:
            dead += 1
            continue
        key = signature if quotient else (bit,)
        groups.setdefault(key, []).append(bit)
    atom_members = tuple(groups.values())
    weights = tuple(tuple(sum(bool(mask & (1 << bit)) for bit in bits)
                          for mask in request_occurrences)
                    for bits in atom_members)
    completion = []
    for col in columns:
        atom_mask = 0
        for atom, bits in enumerate(atom_members):
            values = [bool(col.occurrences & (1 << bit)) for bit in bits]
            if any(values) != all(values):
                raise AssertionError("invalid incidence quotient")
            if values[0]:
                atom_mask |= 1 << atom
        completion.append(atom_mask)

    def reward(mask):
        counts = list(bases)
        for atom, multiplicities in enumerate(weights):
            if mask & (1 << atom):
                for q, count in enumerate(multiplicities):
                    counts[q] += count
        return sum(value for count, needed, value in zip(counts, quorums, rewards)
                   if count >= needed)

    if not columns:
        return {"value": reward(0), "cost": 0., "chosen": (), "atom_count": 0,
                "occurrence_count": union.bit_count(), "reachable_states": 1,
                "dead_occurrences": dead, "atom_members": atom_members}
    times = sorted({t for col in columns for t in (col.start, col.end)})
    ti = {t: i for i, t in enumerate(times)}
    outgoing = [[] for _ in times]
    for index, col in enumerate(columns):
        outgoing[ti[col.start]].append(index)
    dp = [{} for _ in times]
    dp[0][0] = (0., ())
    for event, row in enumerate(dp):
        if event:
            for mask, path in dp[event-1].items():
                if path[0] < row.get(mask, (inf, ()))[0]:
                    row[mask] = path
        for index in outgoing[event]:
            col = columns[index]
            dest = dp[ti[col.end]]
            for mask, (cost, chosen) in tuple(row.items()):
                new_mask = mask | completion[index]
                if new_mask == mask:
                    continue  # Nonnegative cost; no new request certificate.
                new_cost = cost + col.cost
                if new_cost < dest.get(new_mask, (inf, ()))[0]:
                    dest[new_mask] = (new_cost, chosen + (index,))
    candidates = [(reward(mask)-cost, -cost, chosen)
                  for mask, (cost, chosen) in dp[-1].items()]
    value, negative_cost, chosen = max(candidates, key=lambda item: (item[0], item[1],
                                                                  tuple(-i for i in item[2])))
    return {"value": value, "cost": -negative_cost, "chosen": chosen,
            "atom_count": len(atom_members), "occurrence_count": union.bit_count(),
            "reachable_states": sum(map(len, dp)), "dead_occurrences": dead,
            "atom_members": atom_members}
