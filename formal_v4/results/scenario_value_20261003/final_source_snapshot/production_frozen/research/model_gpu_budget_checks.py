"""Targeted timing gates: one-time setup, failed setup and late-call reserve."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

# The participant entry uses the same import layout as its packaged workspace.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.agent_model_gpu import ModelRemoteBudget
from .model_gpu_transport import ModelGPUTransport


class ModelBudgetChecks(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict("os.environ", {"OPENAI_BASE_URL": "", "OPENAI_API_KEY": ""})
        self.environment.start()
        self.clock = [0.]
        self.transport = ModelGPUTransport({"targets": {"rows": [[1], [2], [3]]}}, {
            "base_url": "http://127.0.0.1:1/v1", "credential": "local-test-credential",
            "initialize_timeout_seconds": 75, "timeout_seconds": 10})
        self.budget = ModelRemoteBudget(self.transport, cpu_default=.26)

    def tearDown(self):
        self.transport.session = None
        self.transport.close()
        self.environment.stop()

    def choose_with(self, setup, decision, failure=None):
        def request(operation, payload=None, timeout=4):
            if operation == "initialize":
                self.clock[0] += setup
                if failure == "initialize":
                    raise TimeoutError("synthetic initialization failure")
                return {"session": "stub-session"}
            self.clock[0] += decision
            if failure == "decision":
                raise TimeoutError("synthetic decision failure")
            return {"action": {"action": "wait", "duration_seconds": 60}}

        start = self.clock[0]
        with patch.object(self.transport, "request", request), patch(
                "formal_v4.research.model_gpu_transport.time.perf_counter", lambda: self.clock[0]):
            if failure:
                with self.assertRaises(TimeoutError):
                    self.transport.choose({}, [0.] * 3, [0.] * 3, {}, [])
            else:
                self.transport.choose({}, [0.] * 3, [0.] * 3, {}, [])
        elapsed = self.clock[0] - start
        self.budget.record_remote(elapsed)
        return elapsed

    def test_successful_setup_not_forecast_as_every_decision(self):
        self.assertEqual(self.choose_with(15., 3.), 18.)
        self.assertEqual(list(self.budget.remote_samples), [3.])
        self.assertEqual(self.choose_with(15., 4.), 4.)
        self.assertEqual(list(self.budget.remote_samples), [3., 4.])
        self.assertEqual(self.budget.initialization_seconds, 15.)
        self.assertEqual(self.budget.observed_remote_seconds, 22.)

    def test_failed_setup_classified_and_full_failure_cost_kept(self):
        self.assertEqual(self.choose_with(75., 3., "initialize"), 75.)
        self.assertEqual(self.transport.last_initialization_seconds, 75.)
        self.assertEqual(self.transport.last_decision_seconds, 0.)
        self.assertEqual(self.transport.last_failure_kind, "initialize")
        self.assertEqual(list(self.budget.remote_samples), [75.])
        self.assertEqual(self.budget.initialization_seconds, 75.)
        self.assertEqual(self.budget.observed_remote_seconds, 75.)
        self.assertEqual(self.budget.failed_initializations, 1)

    def test_failed_decision_keeps_real_recurring_cost(self):
        self.assertEqual(self.choose_with(15., 10., "decision"), 25.)
        self.assertEqual(self.transport.last_initialization_seconds, 15.)
        self.assertEqual(self.transport.last_decision_seconds, 10.)
        self.assertEqual(list(self.budget.remote_samples), [10.])
        self.assertEqual(self.budget.observed_remote_seconds, 25.)
        self.assertEqual(self.budget.failed_initializations, 0)

    def test_setup_guard_and_warm_session_guard_differ(self):
        # 30 reserve + 75 initialization + 10 decision must all fit initially.
        self.assertFalse(self.budget.allow(115., 1))
        self.assertEqual(self.budget.last["reason"], "initialization_budget")
        self.assertTrue(self.budget.allow(116., 1))
        self.transport.session = "stub-session"
        self.assertTrue(self.budget.allow(41., 1))
        self.assertFalse(self.budget.allow(40., 1))

    def test_actual_wall_already_lost_setup_budget_not_subtracted_twice(self):
        self.choose_with(15., 3.)
        self.budget.allow(282., 100)
        # Successful setup is absent from recurring p90; remaining wall still
        # determines the optional quota, so the consumed setup is never free.
        self.assertEqual(self.budget.last["remote_p90"], 3.)
        smaller_wall_fraction = self.budget.last["fraction"]
        self.budget.allow(300., 100)
        self.assertLess(smaller_wall_fraction, self.budget.last["fraction"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
