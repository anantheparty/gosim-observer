#!/usr/bin/env python3
"""Explicitly invoked, locked official L3 research replay; no fitting or tapes."""
from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

IMAGE = "python@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016"
ENTRY = "research.student_policy_agent"
OWNER_LABEL = "student_policy_replay.owner"
SELECTORS = ("native_control", "structured", "flat", "flat_pair_ridge", "public_gain_per_second", "public_terminal_components_one_step")
LEARNED = {"structured", "flat", "flat_pair_ridge"}
COMPONENTS = {"sum_best_scores", "required_penalty", "uniformity_penalty", "report_settlement", "observation_request_reward"}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(action):
    return hashlib.sha256(json.dumps(action, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def tree(root):
    root = Path(root)
    if not root.is_dir():
        raise ValueError("Required source/input directory missing: " + str(root))
    files = {}
    for path in sorted(root.rglob("*")):
        if "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            raise ValueError("Locked trees cannot contain symlinks: " + str(path))
        if path.is_file():
            files[str(path.relative_to(root))] = sha(path)
    if not files:
        raise ValueError("Locked tree is empty: " + str(root))
    return files


def checked_hash(path, expected):
    if not re.fullmatch(r"[0-9a-f]{64}", expected or "") or sha(path) != expected:
        raise ValueError("Reviewed SHA256 mismatch: " + str(path))


def validate_options(args):
    match = re.fullmatch(r"([0-9]+),([0-9]+)", args.cpuset)
    if not match or int(match[1]) == int(match[2]):
        raise ValueError("cpuset must contain exactly two distinct CPU IDs, e.g. 16,17")
    if not 0 <= args.diagnostic_limit <= 8192:
        raise ValueError("diagnostic limit must lie in 0..8192")
    if not math.isfinite(args.threshold) or args.threshold != 0:
        raise ValueError("This initial replay contract freezes the threshold at zero")
    if args.mode == "research_l3" and args.selector == "native_control":
        raise ValueError("research_l3 requires an explicit nonnative selector")
    if bool(args.model_sha256) != (args.selector in LEARNED):
        raise ValueError("Learned selectors require --model-sha256; public/native selectors take none")
    if args.container_name and not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,100}", args.container_name):
        raise ValueError("Invalid container name")


def freeze_inputs(args):
    validate_options(args)
    for key in ("project", "dependencies", "kit", "reference", "teacher_source_lock", "out"):
        setattr(args, key, getattr(args, key).resolve())
        if any(char in str(getattr(args, key)) for char in (",", "\n", "\r")):
            raise ValueError("Mount/input paths cannot contain commas or newlines")
    if args.out.exists():
        raise ValueError("Replay output must not already exist")
    for source in (args.project, args.dependencies, args.kit, args.reference):
        if args.out == source or source in args.out.parents or args.out in source.parents:
            raise ValueError("Replay output and locked input trees must not overlap")
    checked_hash(Path(__file__).resolve(), args.harness_sha256)
    checked_hash(args.teacher_source_lock, args.teacher_source_lock_sha256)
    package_lock = args.project / "student_policy_package_lock.json"
    checked_hash(package_lock, args.package_lock_sha256)
    package = read_json(package_lock)
    if package.get("schema") != "student-policy-overlay-source-lock-v1" or package.get("native_release_files") != 20:
        raise ValueError("Unsupported student package lock")
    if package.get("runtime_entry") != ["python3", "-u", "-m", ENTRY] or package.get("deployment_calibrated") is not False or package.get("cloud_deployment_authorized") is not False:
        raise ValueError("Package entry/deployment contract differs")
    package_files = tree(args.project)
    if package_files != {**package["files"], "student_policy_package_lock.json": args.package_lock_sha256}:
        raise ValueError("Package file inventory differs from its reviewed lock")
    teacher = read_json(args.teacher_source_lock)
    if teacher.get("schema") != "policy-iteration-source-lock-v1" or not teacher.get("all_ready_files_byte_identical"):
        raise ValueError("Expected the reviewed native READY teacher source lock")
    if len(teacher["ready_release"]) != 20 or any(package_files.get(name) != expected for name, expected in teacher["ready_release"].items()):
        raise ValueError("Student package changed a native READY file")
    for name, expected in teacher["official"].items():
        checked_hash(args.kit / name, expected)
    if args.selector in LEARNED:
        checked_hash(args.project / "student_model/model.npz", args.model_sha256)
        if package.get("model_sha256") != args.model_sha256:
            raise ValueError("Selected model differs from reviewed package model")
    checked_hash(args.reference / "actions.jsonl", args.reference_actions_sha256)
    checked_hash(args.reference / "score_report.json", args.reference_score_sha256)
    metadata = list(args.dependencies.glob("numpy-2.2.6.dist-info/METADATA"))
    if len(metadata) != 1 or "\nVersion: 2.2.6\n" not in "\n"+metadata[0].read_text():
        raise ValueError("Replay requires existing NumPy 2.2.6 dependency bytes")
    return dict(harness_sha256=args.harness_sha256, teacher_source_lock_sha256=args.teacher_source_lock_sha256,
                package_lock_sha256=args.package_lock_sha256, package=package_files,
                dependencies=tree(args.dependencies), official_runner=tree(args.kit / "runner"),
                official_L3_input_opaque_hashes=tree(args.kit / "local-cards/L3"),
                reference={name: sha(args.reference / name) for name in ("actions.jsonl", "score_report.json")})


def command(args, diagnostics, name, owner):
    env = dict(PYTHONPATH="/deps", PYTHONDONTWRITEBYTECODE="1", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1",
               STUDENT_POLICY_MODE=args.mode, STUDENT_POLICY_SELECTOR=args.selector,
               STUDENT_POLICY_DIAGNOSTIC_DIR="/capture", STUDENT_POLICY_DIAGNOSTIC_LIMIT=str(args.diagnostic_limit))
    if args.selector in LEARNED:
        env.update(STUDENT_POLICY_MODEL="/workspace/student_model/model.npz", STUDENT_POLICY_MODEL_SHA256=args.model_sha256)
    if args.mode == "research_l3":
        env.update(STUDENT_POLICY_RESEARCH_L3_OVERRIDE="L3_FULL_SEASON_RESEARCH_ONLY", STUDENT_POLICY_MINIMUM_ADVANTAGE="0")
        if args.selector == "flat_pair_ridge":
            env["STUDENT_POLICY_RIDGE_SCHEMA"] = "structured-public-action-v1"
    container = ["docker", "run", "--pull=never", "--interactive", "--user", "1000:1000", "--name", name, "--label", OWNER_LABEL+"="+owner,
                 "--cpus", "2", "--cpuset-cpus", args.cpuset, "--memory", "2048m", "--memory-swap", "2048m", "--pids-limit", "128",
                 "--cap-drop=ALL", "--security-opt=no-new-privileges", "--ulimit", "nofile=512:512", "--ulimit", "fsize=268435456:268435456",
                 "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=256m", "--network", "none", "--log-driver", "none",
                 "--mount", f"type=bind,src={args.project},dst=/workspace,readonly",
                 "--mount", f"type=bind,src={args.dependencies},dst=/deps,readonly",
                 "--mount", f"type=bind,src={diagnostics},dst=/capture", "--workdir", "/workspace"]
    for key, value in env.items():
        container += ["--env", key+"="+value]
    container += [IMAGE, "python3", "-u", "-m", ENTRY]
    runner = [sys.executable, str(args.kit / "runner/run_local.py"), "--card", str(args.kit / "local-cards/L3"),
              "--agent", shlex.join(container), "--agent-cwd", str(args.project), "--wallclock", "900", "--out", str(args.out), "--quiet"]
    return runner, container


def inspect(name):
    response = subprocess.run(["docker", "container", "inspect", name], capture_output=True, text=True, timeout=15)
    if response.returncode:
        if "No such" in response.stderr:
            return None
        raise RuntimeError("Container inspection failed: " + response.stderr[:300])
    return json.loads(response.stdout)[0]


def cleanup_owned(name, owner):
    metadata = inspect(name)
    result = dict(name=name, existed=metadata is not None, removed=False, owner_match=False)
    if metadata is None:
        return result, None
    result["owner_match"] = metadata.get("Config", {}).get("Labels", {}).get(OWNER_LABEL) == owner
    result["container_id"] = metadata.get("Id")
    state = metadata.get("State", {})
    if not result["owner_match"]:
        result["error"] = "Owner label differs; container was not removed"
        return result, state
    # Remove by immutable inspected ID, so name reuse cannot remove another run.
    removed = subprocess.run(["docker", "rm", "--force", metadata["Id"]], capture_output=True, text=True, timeout=30)
    result["removed"] = removed.returncode == 0
    result["exists_after_cleanup"] = inspect(name) is not None
    if removed.returncode:
        result["error"] = removed.stderr[:300]
    return result, state


def after_inputs(args):
    return dict(harness_sha256=sha(Path(__file__).resolve()), teacher_source_lock_sha256=sha(args.teacher_source_lock),
                package_lock_sha256=sha(args.project / "student_policy_package_lock.json"), package=tree(args.project),
                dependencies=tree(args.dependencies), official_runner=tree(args.kit / "runner"),
                official_L3_input_opaque_hashes=tree(args.kit / "local-cards/L3"),
                reference={name: sha(args.reference / name) for name in ("actions.jsonl", "score_report.json")})


def verify_outputs(args, code, timed_out, state, cleanup, unchanged):
    workflow = read_json(args.out / "workflow_result.json") if (args.out / "workflow_result.json").exists() else {}
    score = read_json(args.out / "score_report.json") if (args.out / "score_report.json").exists() else {}
    reference_score = read_json(args.reference / "score_report.json")
    log = (args.out / "agent.log").read_text(errors="replace") if (args.out / "agent.log").exists() else ""
    summaries = []
    for line in log.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and isinstance(value.get("student_policy"), dict):
            summaries.append(value)
    summary = summaries[-1] if summaries else {}
    student = summary.get("student_policy", {})
    counts = student.get("counts", {})
    choices = student.get("choices", {})
    actions_path = args.out / "actions.jsonl"
    actions = [json.loads(line) for line in actions_path.read_text().splitlines()] if actions_path.exists() else []
    action_digest = hashlib.sha256()
    for action in actions:
        action_digest.update((json.dumps(action, sort_keys=True, separators=(",", ":"))+"\n").encode())
    diagnostic_dir = args.out / "public_diagnostics"
    diagnostic_path = diagnostic_dir / "student_choices.jsonl"
    diagnostics = [json.loads(line) for line in diagnostic_path.read_text().splitlines()] if diagnostic_path.exists() else []
    diagnostic_ok = True
    for row in diagnostics:
        step = row.get("step", -1)
        diagnostic_ok &= (isinstance(step, int) and 0 <= step < len(actions)
                          and row.get("selected_action_sha256") == canonical(actions[step])
                          and row.get("mode") == args.mode and row.get("selector") == args.selector)
        if args.mode == "control":
            diagnostic_ok &= row.get("selected") == "control" and row.get("native_action_sha256") == row.get("selected_action_sha256")
        deltas = row.get("selection_deltas")
        if deltas is not None:
            diagnostic_ok &= set(deltas) == set(row.get("available", [])) and all(isinstance(value, (float, int)) and math.isfinite(value) for value in deltas.values())
    diagnostic_names = {path.name for path in diagnostic_dir.iterdir()} if diagnostic_dir.exists() else set()
    state = state or {}
    accounted = workflow.get("accounted_wallclock_seconds")
    components = score.get("components", {})
    finite_score = isinstance(score.get("total"), (int, float)) and math.isfinite(score["total"])
    finite_components = set(components) == COMPONENTS and all(isinstance(value, (int, float)) and math.isfinite(value) for value in components.values())
    intervention_count = counts.get("interventions", 0)
    observe_count = counts.get("observe_choices", 0)
    expected_diagnostics = min(observe_count, args.diagnostic_limit)
    gates = dict(runner_exit_zero=code == 0 and not timed_out,
                 container_exit_zero=state.get("Status") == "exited" and state.get("ExitCode") == 0 and not state.get("OOMKilled") and not state.get("Error"),
                 owned_container_cleaned=cleanup.get("owner_match") is True and cleanup.get("removed") is True and cleanup.get("exists_after_cleanup") is False,
                 complete_official_protocol=workflow.get("termination_reason") == "survey_complete" and workflow.get("protocol_version") == "participant-agent-protocol-v4" and workflow.get("ignored_in_flight_response") is False,
                 resource_budget=isinstance(accounted, (int, float)) and 0 <= accounted <= 900 and workflow.get("global_wallclock_seconds") == 900,
                 no_traceback="Traceback" not in log, one_participant_summary=len(summaries) == 1,
                 expected_student_configuration=student.get("mode") == args.mode and student.get("selector") == args.selector and student.get("model_sha256") == args.model_sha256,
                 deployment_remains_false=student.get("deployment_calibrated") is False and student.get("cloud_deployment_authorized") is False,
                 natural_replanning=student.get("forced_prefix") is False and student.get("forced_suffix") is False and student.get("suffix_mode") == "natural_native_replan_after_every_actual_feedback",
                 no_unknown_student_errors=student.get("errors") == {} and counts.get("student_error_native_fallback", 0) == 0,
                 full_decision_bookkeeping=counts.get("decisions") == summary.get("decisions") == workflow.get("decision_requests") == len(actions),
                 full_choice_bookkeeping=sum(choices.values()) == observe_count == score.get("counts", {}).get("observe_actions") and sum(value for key, value in choices.items() if key != "control") == intervention_count,
                 actual_action_digest=student.get("actions_sha256") == action_digest.hexdigest(),
                 bounded_complete_diagnostics=diagnostic_ok and diagnostic_names == {"student_choices.jsonl"} and len(diagnostics) == expected_diagnostics == counts.get("diagnostic_rows", 0),
                 source_and_inputs_unchanged=unchanged, finite_official_score=finite_score and finite_components)
    reference_parity = dict(actions_sha256_match=actions_path.exists() and sha(actions_path) == args.reference_actions_sha256,
                            total_match=finite_score and Decimal(str(score["total"])) == Decimal(str(reference_score["total"])),
                            components_match=components == reference_score.get("components"))
    if args.mode == "control":
        gates.update(native_no_intervention=intervention_count == 0 and student.get("native_actions_on_reached_states_sha256") == student.get("actions_sha256"), **reference_parity)
        if args.selector == "native_control":
            gates["native_no_student_inference"] = counts.get("inferences", 0) == 0
    return dict(schema="student-policy-official-L3-gate-v1", card="L3", mode=args.mode, selector=args.selector,
                passed=all(gates.values()), gates=gates, reference_parity=reference_parity, total=score.get("total"), components=components,
                termination=workflow.get("termination_reason"), termination_detail=workflow.get("termination_detail"), runner_exit_code=code,
                runner_timed_out=timed_out, container_state=state, cleanup=cleanup, accounted_seconds=accounted,
                agent_seconds=workflow.get("agent_wallclock_seconds"), student_policy=student,
                fallback_counts={key: value for key, value in counts.items() if "fallback" in key}, interventions=intervention_count,
                participant_summary_sha256=hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).hexdigest(),
                diagnostics_sha256={path.name: sha(path) for path in diagnostic_dir.iterdir() if path.is_file()},
                output_sha256={name: sha(args.out / name) for name in ("actions.jsonl", "score_report.json", "workflow_result.json", "agent.log") if (args.out / name).exists()},
                participant_truth_mount=False, deployment_calibrated=False, cloud_deployment_authorized=False)


def execute(args, before, runner, name, owner):
    if inspect(name) is not None:
        raise ValueError("A container with this name already exists; refusing restart")
    args.out.mkdir(parents=True)
    diagnostics = args.out / "public_diagnostics"
    diagnostics.mkdir(); diagnostics.chmod(0o777)
    if any(diagnostics.iterdir()):
        raise ValueError("Participant diagnostics mount must begin empty")
    lock = dict(schema="student-policy-official-L3-run-lock-v1", inputs=before, command=runner, image=IMAGE,
                cpuset=args.cpuset, cpus=2, memory_mib=2048, wallclock_seconds=900, mode=args.mode, selector=args.selector,
                threshold=0, model_sha256=args.model_sha256, container_name=name, owner_label=owner)
    (args.out / "run_source_lock.json").write_text(json.dumps(lock, indent=2)+"\n")
    started = time.monotonic()
    code, timed_out, cleanup, state, cleanup_error = -1, False, {}, None, None
    try:
        with (args.out / "driver.log").open("w") as log:
            try:
                completed = subprocess.run(runner, stdout=log, stderr=subprocess.STDOUT, timeout=990)
                code = completed.returncode
            except subprocess.TimeoutExpired:
                code, timed_out = -9, True
    finally:
        try:
            cleanup, state = cleanup_owned(name, owner)
        except Exception as exc:
            cleanup_error = type(exc).__name__+":"+str(exc)[:300]
            cleanup = dict(name=name, error=cleanup_error, removed=False)
    try:
        after = after_inputs(args)
        unchanged = after == before
        (args.out / "after_source_lock.json").write_text(json.dumps(after, indent=2)+"\n")
        result = verify_outputs(args, code, timed_out, state, cleanup, unchanged)
    except Exception as exc:
        result = dict(schema="student-policy-official-L3-gate-v1", card="L3", mode=args.mode, selector=args.selector, passed=False,
                      audit_error=type(exc).__name__+":"+str(exc)[:500], runner_exit_code=code, runner_timed_out=timed_out,
                      container_state=state, cleanup=cleanup, deployment_calibrated=False, cloud_deployment_authorized=False)
    result.update(host_seconds=time.monotonic()-started, run_source_lock_sha256=sha(args.out / "run_source_lock.json"),
                  harness_sha256=args.harness_sha256, package_lock_sha256=args.package_lock_sha256,
                  teacher_source_lock_sha256=args.teacher_source_lock_sha256, model_sha256=args.model_sha256)
    (args.out / "gate_result.json").write_text(json.dumps(result, indent=2)+"\n")
    compact = {key: result.get(key) for key in ("schema", "card", "mode", "selector", "passed", "total", "termination", "runner_exit_code", "runner_timed_out", "accounted_seconds", "host_seconds", "interventions", "fallback_counts", "audit_error", "harness_sha256", "package_lock_sha256", "model_sha256")}
    (args.out / "summary.json").write_text(json.dumps(compact, indent=2)+"\n")
    print(json.dumps(compact))
    return 0 if result["passed"] else 2


def self_check():
    args = argparse.Namespace(cpuset="16,17", diagnostic_limit=2048, threshold=0., mode="control", selector="native_control", model_sha256=None,
                              container_name=None, project=Path("/synthetic/package"), dependencies=Path("/synthetic/deps"), kit=Path("/synthetic/kit"), out=Path("/synthetic/out"))
    validate_options(args)
    runner, container = command(args, args.out / "public_diagnostics", "synthetic-student-l3", "fabricated-owner")
    checks = dict(explicit_research_entry=container[-4:] == ["python3", "-u", "-m", ENTRY], native_control_no_model_env=not any(value.startswith("STUDENT_POLICY_MODEL=") for value in container),
                  exact_image=IMAGE in container, cpuset_two_cores=container[container.index("--cpuset-cpus")+1] == "16,17",
                  memory_2gib=container[container.index("--memory")+1] == "2048m", wallclock_900=runner[runner.index("--wallclock")+1] == "900",
                  no_network=container[container.index("--network")+1] == "none", retain_exit_evidence="--rm" not in container,
                  only_three_input_output_mounts=container.count("--mount") == 3 and sum("readonly" in item for item in container) == 2)
    for selector in SELECTORS:
        args.selector = selector; args.model_sha256 = "a"*64 if selector in LEARNED else None
        args.mode = "control" if selector == "native_control" else "research_l3"
        validate_options(args)
        _, argv = command(args, args.out / "public_diagnostics", "synthetic-student-l3", "fabricated-owner")
        checks[selector+"_argv_valid"] = ("STUDENT_POLICY_SELECTOR="+selector) in argv
        if args.mode == "research_l3":
            checks[selector+"_research_override_threshold"] = "STUDENT_POLICY_RESEARCH_L3_OVERRIDE=L3_FULL_SEASON_RESEARCH_ONLY" in argv and "STUDENT_POLICY_MINIMUM_ADVANTAGE=0" in argv
    args.cpuset = "16,16"
    try:
        validate_options(args)
    except ValueError:
        checks["duplicate_cpu_refused"] = True
    args.cpuset = "16,17"; args.threshold = 1.
    try:
        validate_options(args)
    except ValueError:
        checks["nonzero_threshold_refused"] = True
    assert all(checks.values()), checks
    print(json.dumps(dict(schema="student-replay-harness-synthetic-argv-check-v1", passed=True, checks=checks, seasons_launched=0, labels_read=0, docker_calls=0)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("project", "dependencies", "kit", "reference", "teacher-source-lock", "out"):
        parser.add_argument("--"+name, type=Path)
    for name in ("package-lock-sha256", "harness-sha256", "teacher-source-lock-sha256", "reference-actions-sha256", "reference-score-sha256"):
        parser.add_argument("--"+name)
    parser.add_argument("--cpuset", default="16,17")
    parser.add_argument("--container-name")
    parser.add_argument("--mode", choices=("control", "research_l3"), default="control")
    parser.add_argument("--selector", choices=SELECTORS, default="native_control")
    parser.add_argument("--model-sha256")
    parser.add_argument("--threshold", type=float, default=0.)
    parser.add_argument("--diagnostic-limit", type=int, default=2048)
    parser.add_argument("--execute", action="store_true", help="Launch exactly one official L3 episode; omission prints a command plan only")
    parser.add_argument("--self-check", action="store_true", help="Synthetic argv guards only: zero Docker/season/label calls")
    args = parser.parse_args()
    if args.self_check:
        self_check(); return 0
    required = ("project", "dependencies", "kit", "reference", "teacher_source_lock", "out", "package_lock_sha256", "harness_sha256", "teacher_source_lock_sha256", "reference_actions_sha256", "reference_score_sha256")
    missing = [name for name in required if getattr(args, name) is None]
    if missing:
        parser.error("Required arguments: " + ", ".join("--"+name.replace("_", "-") for name in missing))
    before = freeze_inputs(args)
    owner = hashlib.sha256(json.dumps(dict(out=str(args.out), inputs=before, mode=args.mode, selector=args.selector), sort_keys=True).encode()).hexdigest()
    name = args.container_name or "student-l3-"+args.mode.replace("_", "-")+"-"+owner[:12]
    runner, container = command(args, args.out / "public_diagnostics", name, owner)
    if not args.execute:
        print(json.dumps(dict(schema="student-policy-replay-command-plan-v1", execute=False, command=runner, container=container,
                              harness_sha256=args.harness_sha256, package_lock_sha256=args.package_lock_sha256,
                              native_control_additional_inference=args.selector != "native_control", deployment_calibrated=False)))
        return 0
    return execute(args, before, runner, name, owner)


if __name__ == "__main__":
    raise SystemExit(main())
