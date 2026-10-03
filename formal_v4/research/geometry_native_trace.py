#!/usr/bin/env python3
"""Reconstruct public protocol prefixes and inspect the first policy fork."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "results/geometry_native_20261003"


def freeze(args):
    sys.path.insert(0, str(BASE / "upstream/gosim-observer-examples"))
    from runner.challenge.v4_runner import run_scenario
    from runner.challenge.v4_workflow import V4Workflow
    card = BASE / "upstream/gosim-observer-examples/local-cards" / args.card
    actions = [json.loads(line) for line in (args.gate / args.card / "actions.jsonl").read_text().splitlines()]
    initial = V4Workflow(card).initialize_payload(900)
    requests = []
    def factory(_):
        def replay(snapshot):
            index = len(requests)
            if index >= args.cutoff:
                return dict(action="finish")
            requests.append(V4Workflow.request_message(index + 1, snapshot, 0, 900)["payload"])
            return actions[index]
        return replay
    run_scenario(card / "config/v4_scenario.json", factory, OUT / "trace" / args.card / "engine_prefix")
    folder = OUT / "trace" / args.card
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "public_prefix.json").write_text(json.dumps(dict(card=args.card, initial=initial, snapshots=requests,
                                                    actions=actions[:args.cutoff]), separators=(",", ":")) + "\n")
    print(json.dumps(dict(card=args.card, snapshots=len(requests), output=str(folder / "public_prefix.json"))), flush=True)


def compare(args):
    import numpy as np
    release = args.project.resolve()
    sys.path.insert(0, str(release))
    import policy
    if args.backend == "reference":
        name = "research.geometry_native_reference_trace"
        path = BASE / "results/candidate_geometry_20261003/source_snapshot/candidate_geometry_sweep.py"
        spec = importlib.util.spec_from_file_location(name, path)
        cg = importlib.util.module_from_spec(spec); sys.modules[name] = cg; spec.loader.exec_module(cg)
    else:
        from research import candidate_geometry_sweep as cg
    policy.SpatialPlanner = cg.CandidateGeometryPlanner
    prefix = json.loads(args.prefix.read_text())
    prefix["snapshots"] = prefix["snapshots"][:args.cutoff]
    prefix["actions"] = prefix["actions"][:args.cutoff]
    p = policy.Policy(prefix["initial"])
    last_exports = []
    def hook(snapshot, groups, stats, base, best):
        last_exports[:] = groups
    p.planner.export_hook = hook
    records = []
    folder = args.output or OUT / "trace" / prefix["card"] / args.backend
    folder.mkdir(parents=True, exist_ok=True)
    for index, (snapshot, expected) in enumerate(zip(prefix["snapshots"], prefix["actions"])):
        action = p.decide(snapshot)
        if action != expected or index + 1 == len(prefix["snapshots"]):
            diff = {key: [expected.get(key), action.get(key)] for key in set(expected) | set(action) if expected.get(key) != action.get(key)}
            record = dict(sequence=index + 1, observe_index=snapshot["observe_action_index"], now_utc=snapshot["now_utc"],
                          action=action, expected=expected, differences=diff, C=p.C, E=p.E,
                          pointing_estimate=list(p.calibrator.estimate) if p.calibrator else None,
                          stats=dict(p.planner.stats), baseline_candidates=[
                              dict(rate=float(c[0]), center=list(c[1]), duration=int(c[2]), program=int(c[3]),
                                   targets=c[4].tolist(), fibers=c[5].tolist()) for c in p.planner.baseline_candidates])
            arrays = dict(scores=p.scores, factors=p.factors, lower=p.factor_lower)
            for i, frame in enumerate(p.planner.frame or ()):
                if isinstance(frame, np.ndarray): arrays[f"frame_{i}"] = frame
            np.savez_compressed(folder / f"{index + 1:04d}_state.npz", **arrays)
            for j, group in enumerate(last_exports):
                np.savez_compressed(folder / f"{index + 1:04d}_group{j}.npz", **group)
            (folder / f"{index + 1:04d}_record.json").write_text(json.dumps(record, indent=2) + "\n")
            records.append(dict(sequence=index + 1, observe_index=snapshot["observe_action_index"], differences=diff))
            print(json.dumps(dict(card=prefix["card"], backend=args.backend, **records[-1])), flush=True)
            if action != expected:
                break
    (folder / "summary.json").write_text(json.dumps(dict(backend=args.backend, records=records), indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("freeze", "compare"), required=True)
    parser.add_argument("--card", choices=("L1", "L2", "L3", "L4"), default="L4")
    parser.add_argument("--cutoff", type=int, default=110)
    parser.add_argument("--gate", type=Path, default=OUT / "protocol_gate_retry")
    parser.add_argument("--backend", choices=("reference", "native"), default="reference")
    parser.add_argument("--project", type=Path, default=BASE / "runs/geometry_native_20261003/release")
    parser.add_argument("--prefix", type=Path, default=OUT / "trace/L4/public_prefix.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    freeze(args) if args.mode == "freeze" else compare(args)


if __name__ == "__main__":
    main()
