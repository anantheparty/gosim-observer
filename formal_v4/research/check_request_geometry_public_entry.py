"""Initialize and one real JSONL decision using only public L1 material."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "results/request_geometry_integration_20261004"


def main():
    sys.path.insert(0, str(BASE / "upstream/gosim-observer-examples/runner"))
    from challenge.v4_workflow import V4Workflow
    initial = json.loads((BASE / "results/policy_iteration_20261004/L1_initialize_public.json").read_text())
    snapshot = {
        "now_utc": initial["survey"]["nights"][0]["observing_start_utc"],
        "survey_end_utc": initial["survey"]["end_utc"], "observe_action_index": 0,
        "running_total": 0, "latest_bulletin": None, "latest_forecast": None,
        "active_requests": [], "new_messages": [], "last_result": None,
    }
    protocol = "".join(json.dumps(m) + "\n" for m in [
        V4Workflow.initialize_message(initial), V4Workflow.request_message(1, snapshot, 0., 900.),
    ])
    (OUT / "smoke_public_input.jsonl").write_text(protocol)
    results = []
    for variant, entry in [("control", "research.agent_request_exact_cache"),
                           ("geometry", "research.agent_request_geometry")]:
        env = {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
               "MKL_NUM_THREADS": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        env.pop("PYTHONPATH", None)
        started = time.monotonic()
        run = subprocess.run([sys.executable, "-u", "-m", entry], cwd=OUT / (variant + "_package"),
                             input=protocol, text=True, capture_output=True, env=env, timeout=40)
        (OUT / (variant + "_smoke.stdout.jsonl")).write_text(run.stdout)
        (OUT / (variant + "_smoke.stderr.jsonl")).write_text(run.stderr)
        assert run.returncode == 0, (variant, run.stderr)
        responses = [json.loads(line) for line in run.stdout.splitlines()]
        assert len(responses) == 1
        action = V4Workflow.action_from_response(responses[0], 1)
        assert action["action"] == "observe" and "Traceback" not in run.stderr
        results.append({"variant": variant, "exit_code": run.returncode, "responses": responses,
                        "seconds": time.monotonic() - started, "input_only_public": True})
    (OUT / "first_decision_smoke.json").write_text(json.dumps({"passed": True, "results": results}, indent=2) + "\n")
    print(json.dumps({"passed": True, "variants": 2, "uses_static_official_protocol_constructors": True}))


if __name__ == "__main__":
    main()
