"""Independent exhaustive checks for the fixed-column request mask DP.

Run directly with ``python formal_v4/research/request_mask_dp_checks.py``.
Only the standard library is required.
"""

from itertools import combinations
from math import inf, isinf
import random
import unittest

try:
    from .request_mask_dp import RequestColumn, compare_request_reward, solve_request_columns
except ImportError:
    from request_mask_dp import RequestColumn, compare_request_reward, solve_request_columns


def brute_force(columns, target_count, quorum, completed_mask=0, now=None, deadline=None):
    """Enumerate every input subset, check timing, then count its target union."""
    if completed_mask.bit_count() >= quorum:
        return 0.0
    best = inf
    for size in range(len(columns) + 1):
        for indices in combinations(range(len(columns)), size):
            selected = sorted(indices, key=lambda i: (columns[i].start, columns[i].end, i))
            if any(now is not None and columns[i].start < now for i in selected):
                continue
            if any(deadline is not None and columns[i].end > deadline for i in selected):
                continue
            if any(columns[a].end > columns[b].start for a, b in zip(selected, selected[1:])):
                continue
            union, cost = completed_mask, 0.0
            for i in selected:
                union |= columns[i].completion_mask
                cost += columns[i].opportunity_cost
            if union.bit_count() >= quorum:
                best = min(best, cost)
    return best


class RequestMaskDPChecks(unittest.TestCase):
    def assert_schedule(self, columns, plan, quorum, completed_mask=0, now=None, deadline=None):
        if not plan.feasible:
            self.assertTrue(isinf(plan.min_cost))
            self.assertEqual(plan.chosen_indices, ())
            self.assertEqual(plan.final_mask, completed_mask)
            return
        indices = plan.chosen_indices
        self.assertEqual(len(indices), len(set(indices)))
        union, cost, previous_end = completed_mask, 0.0, -inf
        for i in indices:
            self.assertTrue(0 <= i < len(columns))
            column = columns[i]
            self.assertGreaterEqual(column.start, previous_end)
            if now is not None:
                self.assertGreaterEqual(column.start, now)
            if deadline is not None:
                self.assertLessEqual(column.end, deadline)
            union |= column.completion_mask
            cost += column.opportunity_cost
            previous_end = column.end
        self.assertEqual(plan.final_mask, union)
        self.assertGreaterEqual(union.bit_count(), quorum)
        self.assertAlmostEqual(plan.min_cost, cost)

    def test_adjacent_exposures_and_original_indices(self):
        tag = {"action": "opaque payload"}
        columns = [
            RequestColumn(2, 3, 0b10, 3, tag),
            RequestColumn(0, 2, 0b01, 2),
            RequestColumn(0, 3, 0b11, 8),
        ]
        plan = solve_request_columns(columns, target_count=2, quorum=2, deadline=3)
        self.assertEqual(plan.min_cost, 5)
        self.assertEqual(plan.chosen_indices, (1, 0))
        self.assertEqual(plan.final_mask, 0b11)
        self.assertIs(columns[0].tag, tag)

    def test_overlap_requires_one_telescope(self):
        columns = [RequestColumn(0, 2, 1, 1), RequestColumn(1, 3, 2, 1)]
        plan = solve_request_columns(columns, target_count=2, quorum=2)
        self.assertFalse(plan.feasible)
        self.assert_schedule(columns, plan, 2)

    def test_repeated_targets_and_existing_completion_never_double_count(self):
        columns = [RequestColumn(0, 1, 1, 0), RequestColumn(1, 2, 1, 0)]
        for completed in (0, 1):
            plan = solve_request_columns(columns, target_count=2, quorum=2, completed_mask=completed)
            self.assertFalse(plan.feasible)
            self.assert_schedule(columns, plan, 2, completed)

    def test_zero_cost_redundant_columns_are_replaced_by_waiting(self):
        columns = [
            RequestColumn(0, 1, 0b001, 0),
            RequestColumn(1, 2, 0b001, 0),
            RequestColumn(2, 3, 0b000, 0),
            RequestColumn(3, 4, 0b010, 2),
            RequestColumn(4, 5, 0b011, 0),
        ]
        plan = solve_request_columns(columns, target_count=3, quorum=2, completed_mask=0b001)
        self.assertEqual(plan.min_cost, 0)
        self.assertEqual(plan.chosen_indices, (4,))
        self.assertEqual(plan.final_mask, 0b011)
        self.assert_schedule(columns, plan, 2, completed_mask=0b001)

    def test_quorum_credits_the_entire_union(self):
        columns = [RequestColumn(0, 1, 0b110, 2)]
        plan = solve_request_columns(columns, target_count=3, quorum=2, completed_mask=0b001)
        self.assertTrue(plan.feasible)
        self.assertEqual(plan.chosen_indices, (0,))
        self.assertEqual(plan.final_mask, 0b111)

    def test_minimum_cost_can_omit_extra_completed_targets(self):
        columns = [RequestColumn(0, 1, 0b011, 2), RequestColumn(1, 2, 0b100, 1)]
        plan = solve_request_columns(columns, target_count=3, quorum=2)
        self.assertEqual(plan.min_cost, 2)
        self.assertEqual(plan.chosen_indices, (0,))
        self.assertEqual(plan.final_mask, 0b011)

    def test_filtering_is_inclusive_and_preserves_input_indices(self):
        columns = [
            RequestColumn(-1, 1, 0b11, 0),
            RequestColumn(0, 1, 0b01, 1),
            RequestColumn(1, 2, 0b10, 1),
            RequestColumn(2, 3, 0b11, 0),
        ]
        plan = solve_request_columns(columns, target_count=2, quorum=2, now=0, deadline=2)
        self.assertEqual(plan.chosen_indices, (1, 2))
        self.assert_schedule(columns, plan, 2, now=0, deadline=2)

    def test_already_complete_empty_and_expired_cases(self):
        self.assertFalse(solve_request_columns([], target_count=2, quorum=1).feasible)
        plan = solve_request_columns([], target_count=2, quorum=1, completed_mask=2, now=3, deadline=2)
        self.assertEqual((plan.feasible, plan.min_cost, plan.chosen_indices, plan.final_mask), (True, 0, (), 2))
        self.assertTrue(solve_request_columns([], target_count=0, quorum=0).feasible)
        columns = [RequestColumn(0, 1, 1, 0)]
        self.assertFalse(solve_request_columns(columns, target_count=1, quorum=1, now=3, deadline=2).feasible)

    def test_reward_is_once_per_completed_request_and_ties_wait(self):
        columns = [RequestColumn(0, 1, 1, 2), RequestColumn(1, 2, 2, 3)]
        plan = solve_request_columns(columns, target_count=2, quorum=2)
        for reward in (0, 4, 5):
            decision = compare_request_reward(plan, reward)
            self.assertEqual((decision.pursue, decision.net_value, decision.chosen_indices), (False, 0, ()))
        decision = compare_request_reward(plan, 7)
        self.assertEqual((decision.pursue, decision.net_value, decision.chosen_indices), (True, 2, (0, 1)))
        incomplete = solve_request_columns(columns[:1], target_count=2, quorum=2)
        self.assertFalse(compare_request_reward(incomplete, 1000).pursue)

    def test_invalid_inputs_fail_clearly(self):
        for kwargs in ({"target_count": 9, "quorum": 1}, {"target_count": 2, "quorum": 3},
                       {"target_count": 2, "quorum": 1, "completed_mask": 4}):
            with self.assertRaises(ValueError):
                solve_request_columns([], **kwargs)
        for column in (RequestColumn(0, 0, 1, 0), RequestColumn(1, 0, 1, 0),
                       RequestColumn(0, 1, 1, -1), RequestColumn(0, 1, 4, 0),
                       RequestColumn(0, inf, 1, 0), RequestColumn(0, 1, 1, float("nan"))):
            with self.assertRaises(ValueError):
                solve_request_columns([column], target_count=2, quorum=1)
        with self.assertRaises(TypeError):
            solve_request_columns([], target_count=2, quorum=1, now="2026-01-01")

    def test_random_small_instances_against_all_subsets(self):
        rng = random.Random(491731)
        incomplete_cases = 0
        for case in range(700):
            target_count = rng.randint(1, 8)
            if case % 7 == 0:
                quorum = rng.randint(0, target_count)
                completed_mask = rng.randrange(1 << target_count)
            else:
                quorum = rng.randint(1, target_count)
                completed_mask = sum(1 << bit for bit in rng.sample(
                    range(target_count), rng.randrange(quorum)))
            incomplete_cases += completed_mask.bit_count() < quorum
            columns = []
            for _ in range(rng.randint(0, 10)):
                start = rng.randint(0, 40) / 4
                completion_mask = (1 << rng.randrange(target_count) if case % 3 == 0
                                   else rng.randrange(1 << target_count))
                columns.append(RequestColumn(start, start + rng.randint(1, 16) / 4,
                                             completion_mask, rng.randint(0, 32) / 4))
            now = None if rng.randrange(3) == 0 else rng.randint(0, 5)
            deadline = None if rng.randrange(3) == 0 else rng.randint(3, 14)
            with self.subTest(case=case):
                best = brute_force(columns, target_count, quorum, completed_mask, now, deadline)
                plan = solve_request_columns(columns, target_count=target_count, quorum=quorum,
                                             completed_mask=completed_mask, now=now, deadline=deadline)
                self.assertEqual(plan.feasible, not isinf(best))
                self.assertEqual(plan.min_cost, best)
                self.assert_schedule(columns, plan, quorum, completed_mask, now, deadline)
        self.assertGreaterEqual(incomplete_cases, 600)


if __name__ == "__main__":
    unittest.main()
