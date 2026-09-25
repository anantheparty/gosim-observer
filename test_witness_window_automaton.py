#!/usr/bin/env python3
"""Independent exhaustive checks for dynamic request-witness masks."""

from __future__ import annotations

import unittest

import numpy as np

from bounds_witness_window_automaton import (
    NEG_INF, ToyArc, WitnessLink, toy_bruteforce, toy_dp,
)


class WitnessAutomatonTest(unittest.TestCase):
    def check(self, n, links, arcs, expected=None):
        got = toy_dp(n, tuple(links), arcs)
        brute = toy_bruteforce(n, tuple(links), arcs)
        self.assertEqual(got, brute)
        if expected is not None:
            self.assertEqual(got, expected)

    def test_tag_start_before_deadline_can_finish_after(self):
        self.check(3, [WitnessLink("r", "a", 1, 2)],
                   [ToyArc(0, 1, None, 0), ToyArc(1, 3, "a", 7)], 7)

    def test_arc_cannot_cross_unobserved_window(self):
        self.check(3, [WitnessLink("r", "a", 1, 2)],
                   [ToyArc(0, 3, None, 100), ToyArc(0, 1, None, 0),
                    ToyArc(1, 2, "a", 3), ToyArc(2, 3, None, 0)], 3)

    def test_one_action_cannot_credit_two_request_links(self):
        self.check(3, [WitnessLink("r1", "a", 0, 3),
                       WitnessLink("r2", "a", 0, 3)],
                   [ToyArc(0, 1, "a", 2), ToyArc(1, 2, "a", 3),
                    ToyArc(2, 3, None, 0)], 5)

    def test_infeasible_single_action_for_two_links(self):
        self.check(1, [WitnessLink("r1", "a", 0, 1),
                       WitnessLink("r2", "a", 0, 1)],
                   [ToyArc(0, 1, "a", 9)], NEG_INF)

    def test_random_dags_against_independent_enumeration(self):
        rng = np.random.default_rng(20260925)
        for case in range(500):
            n = int(rng.integers(3, 9))
            links = []
            for i in range(int(rng.integers(0, 5))):
                a = int(rng.integers(0, n))
                d = int(rng.integers(a + 1, n + 1))
                tile = ("a", "b", "c")[int(rng.integers(0, 3))]
                links.append(WitnessLink(f"r{i}", tile, a, d))
            arcs = [ToyArc(u, u + 1, None, int(rng.integers(-3, 2)))
                    for u in range(n)]
            for _ in range(int(rng.integers(n, 3*n + 1))):
                u = int(rng.integers(0, n))
                v = int(rng.integers(u + 1, min(n, u + 3) + 1))
                tile = ("a", "b", "c")[int(rng.integers(0, 3))]
                arcs.append(ToyArc(u, v, tile, int(rng.integers(-4, 11))))
            with self.subTest(case=case):
                self.check(n, links, arcs)


if __name__ == "__main__":
    unittest.main()
