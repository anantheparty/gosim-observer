"""Smoke the owned public compatible GPU endpoint using only public card files.

No platform evaluation, browser access, hidden weather or service restart.
Credentials are read separately and never emitted or hashed in results.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

from .model_gpu_transport import ModelGPUTransport, chat_packets, compact
from formal_v4.remote_planner import RemotePlanner


class Values(list):
    def tolist(self):
        return list(self)


def public_initial(card):
    names = ["config/v4_scenario.json", "config/v4_fiber_config.json", "config/v4_score_config.json",
             "public/targets.csv", "public/v4_night_calendar.csv"]
    inputs = {}

    def read(name):
        path = card / name
        if "truth" in path.parts:
            raise ValueError("hidden input forbidden")
        raw = path.read_bytes()
        inputs[name] = hashlib.sha256(raw).hexdigest()
        return raw.decode()

    scenario, fiber, score = [json.loads(read(name)) for name in names[:3]]
    targets = list(csv.DictReader(read(names[3]).splitlines()))
    calendar = list(csv.DictReader(read(names[4]).splitlines()))
    columns = list(targets[0])
    rows = [[row[name] if name in ("target_id", "target_class") else
             row[name].lower() == "true" if name == "required" else float(row[name])
             for name in columns] for row in targets]
    nights = [{"night_id": row["night_id"], "night_date": row["night_date"],
               "observing_start_utc": row["observing_start_utc"],
               "observing_end_utc": row["observing_end_utc"]} for row in calendar]
    field = fiber["field"]
    side = math.isqrt(int(field["n_fibers"]))
    glass = math.sqrt(float(field["fiber_area_deg2"]))
    pitch = glass + float(field["gap_deg"])
    value = {"schema_version": "v4-initialize-v1", "task_card": scenario["task_card"],
             "site": {**scenario["site"], "minimum_altitude_deg": float(scenario["minimum_altitude_deg"])},
             "survey": {"start_utc": nights[0]["observing_start_utc"],
                        "end_utc": nights[-1]["observing_end_utc"], "slot_seconds": 900, "nights": nights},
             "instrument": {**field, "grid_side": side, "glass_side_deg": glass,
                            "pitch_deg": pitch, "fov_side_deg": side * pitch, "exposure": fiber["exposure"]},
             "scoring": score, "targets": {"columns": columns, "rows": rows},
             "limits": scenario.get("limits", {})}
    return value, inputs


def same_action_hash(action):
    return hashlib.sha256(json.dumps(action, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def recorded_environment(env):
    value = dict(env)
    scale = value["target_quality_scale"]
    if scale and all(x == scale[0] for x in scale):
        value["target_quality_scale"] = {"encoding": "constant", "size": len(scale), "value": scale[0],
                                         "sha256_compact_json": hashlib.sha256(compact(scale)).hexdigest()}
    return value


def package_gates(root, initial, snapshot, secret, source_archive=None):
    destination = root / "formal_v4/runs/model_gpu_owned_smoke"
    destination.mkdir(exist_ok=True)
    archive = Path(source_archive) if source_archive else destination / "entry_audit.zip"
    if source_archive is None:
        subprocess.run([sys.executable, str(root / "formal_v4/pack_submission.py"),
                        "--planner", "model-gpu", "--out", str(archive)],
                       cwd=root, capture_output=True, text=True, check=True)
    frozen = destination / ("uploaded_entry" if source_archive else "entry_audit")
    frozen.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        leaked = [name for name in names if secret.encode() in package.read(name)]
        if leaked:
            raise AssertionError("private service credential appeared in audit package")
        runtime = json.loads(package.read("remote_runtime.json"))
        if any(key in runtime for key in ("token", "key", "credential", "url", "base_url")):
            raise AssertionError("model runtime contains private configuration")
        forbidden = [name for name in names if "truth" in name or name.endswith("model_gpu_adapter.py")]
        if forbidden:
            raise AssertionError("server or hidden files appeared in participant package")
        for name in names:
            target = frozen / name
            if not target.resolve().is_relative_to(frozen.resolve()):
                raise AssertionError("invalid archive path")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(package.read(name))
    environment = dict(os.environ)
    environment.pop("OPENAI_BASE_URL", None)
    environment.pop("OPENAI_API_KEY", None)
    messages = [
        {"protocol_version": "participant-agent-protocol-v4", "message_type": "initialize", "payload": initial},
        {"protocol_version": "participant-agent-protocol-v4", "message_type": "decision_request",
         "decision_sequence": 1, "payload": snapshot},
        {"protocol_version": "participant-agent-protocol-v4", "message_type": "finish", "payload": {}}]
    started = time.perf_counter()
    run = subprocess.run([sys.executable, "-u", "-m", "research.agent_model_gpu"],
                         cwd=frozen, env=environment, input=b"\n".join(compact(x) for x in messages) + b"\n",
                         capture_output=True, timeout=30, check=True)
    lines = [json.loads(line) for line in run.stdout.splitlines()]
    assert len(lines) == 1 and lines[0]["decision_sequence"] == 1 and lines[0]["message_type"] == "decision_response"
    assert b"Traceback" not in run.stderr and secret.encode() not in run.stderr + run.stdout
    summaries = [json.loads(line) for line in run.stderr.splitlines() if line.startswith(b"{")]
    assert any(x.get("remote_check") == "unavailable" for x in summaries)
    assert any("cpu_phase" in x for x in summaries)
    return {"zip_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "files": len(names),
            "private_credential_found": False, "remote_runtime": runtime,
            "server_or_hidden_files_found": False, "missing_env_cpu_phase_fallback": True,
            "fallback_seconds": time.perf_counter() - started, "fallback_action": lines[0]["action"],
            "source_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                              for name in ("formal_v4/pack_submission.py", "formal_v4/research/agent_model_gpu.py")}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--card", default="formal_v4/practice_cards/alpha/alpha")
    parser.add_argument("--token-file", default="formal_v4/runs/gpu_service/token")
    parser.add_argument("--out", default="formal_v4/results/model_gpu_owned_smoke_20261003.json")
    parser.add_argument("--package", help="Optional already-built package to audit without rebuilding")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    initial, inputs = public_initial(root / args.card)
    secret = (root / args.token_file).read_text().strip()
    # This is an owned-endpoint smoke, not a platform run. Prevent unrelated
    # inherited model environment from choosing another destination or credential.
    os.environ.pop("OPENAI_BASE_URL", None)
    os.environ.pop("OPENAI_API_KEY", None)
    endpoint = "https://elevatia.cn/gosim-observer-gpu/v1"
    client = ModelGPUTransport(initial, {"base_url": endpoint, "credential": secret,
                                       "initialize_timeout_seconds": 25, "timeout_seconds": 8})
    direct = RemotePlanner(initial, {"url": "https://elevatia.cn/gosim-observer-gpu", "token": secret,
                                     "timeout_seconds": 8})
    count = len(initial["targets"]["rows"])
    scores, factors = Values([0.] * count), Values([0.] * count)
    snapshot = {"schema_version": "v4-decision-snapshot-v1", "now_utc": initial["survey"]["nights"][0]["observing_start_utc"],
                "survey_end_utc": initial["survey"]["end_utc"], "observe_action_index": 0,
                "running_total": 0., "wallclock": {"elapsed_seconds": 0., "remaining_seconds": 900.},
                "new_messages": [], "last_result": None, "active_requests": []}
    env = {"quality_scale": .55, "program_band_quality_scale": .55 / .95,
           "target_quality_scale": [1.] * count,
           "gpu_anchor_count": 1024, "gpu_max_candidates": 32768, "gpu_refine_count": 64,
           "gpu_refine_budget_seconds": .3, "gpu_fixed_workload": True,
           "gpu_exact_candidate_count": 256, "gpu_refinement_steps": 32, "gpu_emergency_seconds": 3.}
    record = {"public_card": "alpha", "sources": inputs, "catalog_targets": count,
              "initialization_sha256": hashlib.sha256(compact(initial)).hexdigest(),
              "initialization_chunks": len(chat_packets("initialize", {"initialize": initial})),
              "initialization_chat_sizes": [len(x) for x in chat_packets("initialize", {"initialize": initial})],
              "endpoint": endpoint, "hidden_inputs_read": False, "credentials_recorded": False,
              "frozen_environment": recorded_environment(env), "runs": []}
    try:
        record["health"] = client.check()
        assert record["health"]["remote_check"] == "ok" and record["health"]["gpu_available"] is True
        started = time.perf_counter()
        client.session = client.request("initialize", {"initialize": initial}, timeout=25)["session"]
        record["initialization_seconds"] = time.perf_counter() - started
        for _ in range(3):
            before = client.rpc_calls
            started = time.perf_counter()
            result = client.choose(snapshot, scores, factors, env, [])
            record["runs"].append({"transport": "compatible", "seconds": time.perf_counter() - started,
                "chat_calls": client.rpc_calls - before, "action": result["action"],
                "action_sha256": same_action_hash(result["action"]), "stats": result.get("stats", {}),
                "backend_seconds": result.get("seconds")})
        started = time.perf_counter()
        reference = direct.choose(snapshot, scores, factors, env, [])
        record["direct_reference"] = {"seconds_including_initialize": time.perf_counter() - started,
                                     "action": reference["action"], "action_sha256": same_action_hash(reference["action"]),
                                     "stats": reference.get("stats", {}), "backend_seconds": reference.get("seconds")}
        record["identical_actions"] = len({x["action_sha256"] for x in record["runs"]} |
                                           {record["direct_reference"]["action_sha256"]}) == 1
        record["all_fixed_workload"] = all(x["stats"].get("fixed_workload") is True and
                                            x["stats"].get("emergency_triggered") is False for x in record["runs"])
        record["entry_package_gates"] = package_gates(root, initial, snapshot, secret,
                                                    root / args.package if args.package else None)
    finally:
        client.close()
        direct.close()
        record["close_invoked"] = True
    record["source_sha256"] = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                               for name in ("model_gpu_transport.py", "model_gpu_adapter.py", "model_gpu_owned_smoke.py")}
    record["verified_at_utc"] = datetime.now(timezone.utc).isoformat()
    out = root / args.out
    out.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"result": str(out), "init_chunks": record["initialization_chunks"],
                      "init_seconds": record["initialization_seconds"],
                      "choose_seconds": [x["seconds"] for x in record["runs"]],
                      "identical_actions": record["identical_actions"], "package_gates": record.get("entry_package_gates")}, indent=2))


if __name__ == "__main__":
    main()
