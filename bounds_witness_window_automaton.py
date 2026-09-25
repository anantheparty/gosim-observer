#!/usr/bin/env python3
"""Time-varying request-witness automaton for rigorous projected bounds.

This module implements and tests the witness-state transition, not a full
season K-key bound. The latter must take the product of this automaton and the
existing first-success key-mask DP before reporting any improved upper bound.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable


NEG_INF = -(10**15)


@dataclass(frozen=True)
class WitnessLink:
    request_id: str
    tile_id: str
    available_unit: int
    deadline_unit: int

    def __post_init__(self) -> None:
        if not 0 <= self.available_unit < self.deadline_unit:
            raise ValueError("witness window must be nonempty")


@dataclass(frozen=True)
class ToyArc:
    start: int
    end: int
    tile_id: str | None
    weight: int

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("toy arc must advance time")


def active_ids(links: tuple[WitnessLink, ...], unit: int) -> tuple[int, ...]:
    return tuple(i for i, link in enumerate(links)
                 if link.available_unit <= unit < link.deadline_unit)


def mask_to_global(active: tuple[int, ...], local_mask: int) -> int:
    if local_mask < 0 or local_mask >= (1 << len(active)):
        raise ValueError("local mask exceeds active witness set")
    return sum(1 << link_id for bit, link_id in enumerate(active)
               if local_mask & (1 << bit))


def mask_from_global(active: tuple[int, ...], global_mask: int) -> int:
    return sum(1 << bit for bit, link_id in enumerate(active)
               if global_mask & (1 << link_id))


def transition(
    links: tuple[WitnessLink, ...], start: int, end: int,
    local_mask: int, tile_id: str | None,
) -> tuple[int, ...]:
    """Possible successor local masks after one arc, crediting at most one link.

    A real observe action carries a single request label. An ordinary wait or
    weather-interrupted action credits none. A successful untagged action may
    also choose no credit. If the arc crosses a deadline, the link must have
    been credited before leaving its window. Credit is granted at arc start;
    this matches the scorer even if completion crosses the deadline.
    """
    if end <= start:
        raise ValueError("transition must advance")
    before = active_ids(links, start)
    after = active_ids(links, end)
    already = mask_to_global(before, local_mask)
    options = [0]
    if tile_id is not None:
        options.extend(1 << link_id for link_id in before
                       if links[link_id].tile_id == tile_id)
    expiring = sum(1 << link_id for link_id, link in enumerate(links)
                   if start < link.deadline_unit <= end)
    successors = set()
    for credited in options:
        completed = already | credited
        if expiring & ~completed:
            continue
        successors.add(mask_from_global(after, completed))
    return tuple(sorted(successors))


def terminal_allowed(links: tuple[WitnessLink, ...], unit: int,
                     local_mask: int) -> bool:
    """All expired links were validated on earlier edges; check remaining ones."""
    if any(link.available_unit > unit for link in links):
        return False
    active = active_ids(links, unit)
    return local_mask == (1 << len(active)) - 1


def toy_dp(n: int, links: tuple[WitnessLink, ...], arcs: Iterable[ToyArc]) -> int:
    """Exact witness-constrained path value on a small time DAG."""
    outgoing: list[list[ToyArc]] = [[] for _ in range(n + 1)]
    for arc in arcs:
        if arc.start < 0 or arc.end > n:
            raise ValueError("arc outside horizon")
        outgoing[arc.start].append(arc)

    @lru_cache(None)
    def value(unit: int, local_mask: int) -> int:
        best = 0 if terminal_allowed(links, unit, local_mask) else NEG_INF
        for arc in outgoing[unit]:
            for successor in transition(links, unit, arc.end,
                                        local_mask, arc.tile_id):
                future = value(arc.end, successor)
                if future > NEG_INF // 2:
                    best = max(best, arc.weight + future)
        return best

    return value(0, 0)


def toy_bruteforce(n: int, links: tuple[WitnessLink, ...],
                   arcs: Iterable[ToyArc]) -> int:
    """Independent path/label enumeration with a global completion set."""
    outgoing: list[list[ToyArc]] = [[] for _ in range(n + 1)]
    for arc in arcs:
        outgoing[arc.start].append(arc)
    all_links = (1 << len(links)) - 1
    latest_available = max((link.available_unit for link in links), default=0)

    @lru_cache(None)
    def walk(unit: int, global_mask: int) -> int:
        best = 0 if unit >= latest_available and global_mask == all_links else NEG_INF
        for arc in outgoing[unit]:
            label_options = [None]
            if arc.tile_id is not None:
                label_options.extend(i for i, link in enumerate(links)
                                     if link.tile_id == arc.tile_id and
                                     link.available_unit <= unit < link.deadline_unit)
            for label in label_options:
                new_mask = global_mask if label is None else global_mask | (1 << label)
                future = walk(arc.end, new_mask)
                if future > NEG_INF // 2:
                    best = max(best, arc.weight + future)
        return best

    return walk(0, 0)
