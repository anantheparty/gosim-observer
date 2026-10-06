#!/usr/bin/env python3
"""Offline c32-c35 robustness checks; run ONLY against a copied package.

python work/logtest/fuzz_llm.py --pkg /tmp/c35_review/baseline --json /tmp/c35_review/baseline.json
python work/logtest/fuzz_llm.py --pkg /tmp/c33_fuzz/patched --deadline-policy disable --json /tmp/c33_fuzz/legacy.json
python work/logtest/fuzz_llm.py --pkg /tmp/c37_copy --deadline-policy tolerant --json /tmp/c37_fuzz.json   (c37 thresholds: 6 unfinished, 8 consecutive)

No models, credentials, engine, Policy constructor, or ChatClient constructor
are used. A network/credential audit guard is installed before loading modules.
DutyReader.read uses injected local stubs; policy methods use tiny fake state.
Each case has a wall-time alarm. Exit 1 means failures were found, 0 means pass.
Seeded JSON mutations supplement explicit minimal regression cases. Linux/POSIX.
The default timeout contract is c35: one timeout remains recoverable; three
unfinished workers or four consecutive failures disable the reader. Use
--deadline-policy disable for the original c32/c33/c34 hard-timeout contract.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stderr
import copy
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import random
import re
import signal
import sys
import threading
import time
from types import SimpleNamespace

sys.dont_write_bytecode = True
for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[key] = "1"
os.environ["OBSERVER_MODEL_DISABLED"] = "1"


def guard(event, args):
    if event in ("socket.connect", "socket.getaddrinfo", "socket.bind"):
        raise RuntimeError("Fuzz harness forbids network access")
    if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
        name = os.fsdecode(args[0])
        if any(part in name for part in (".gosim_llm", ".gosim_cred")):
            raise RuntimeError("Fuzz harness forbids credential files")


sys.addaudithook(guard)
HERE = Path(__file__).resolve().parent
ISSUED = datetime(2026, 10, 2, tzinfo=timezone.utc).timestamp()
FAULT = {"date": "10/2", "time": "22:30", "clock": "local", "status": "confirmed", "quote": "signed equipment work"}
WINDOW = {"night": "10/2", "start": "21:00", "end": "21:15", "clock": "local"}
FIELDS = ("fault_starts", "lost_windows", "closures", "active_faults")


class CaseTimeout(Exception):
    pass


def alarm(signum, frame):
    raise CaseTimeout("case exceeded wall timeout")


class Suite:
    def __init__(self, timeout):
        self.timeout, self.results = timeout, []

    def case(self, name, func, payload=None, category="regression"):
        started = time.monotonic()
        signal.setitimer(signal.ITIMER_REAL, self.timeout)
        error = None
        try:
            with redirect_stderr(io.StringIO()):
                func()
        except Exception as exc:
            error = {"type": type(exc).__name__, "message": str(exc)[:220]}
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        row = {"name": name, "category": category, "seconds": round(time.monotonic() - started, 6), "passed": error is None}
        if error:
            row["error"] = error
            if payload is not None:
                # A size-limited diagnostic, never credentials or arbitrary object repr.
                try:
                    row["payload"] = json.dumps(payload, ensure_ascii=False)[:1000]
                except (TypeError, ValueError, RecursionError):
                    row["payload"] = "<non-JSON or oversized numeric payload>"
        self.results.append(row)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pkg", type=Path, default=Path("/tmp/c35_review/baseline"))
    parser.add_argument("--json", type=Path, default=Path("/tmp/c35_review/fuzz_results.json"))
    parser.add_argument("--random", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=32006)
    parser.add_argument("--deadline-policy", choices=("recoverable", "tolerant", "disable"), default="recoverable",
                        help="Expected timeout contract: c35 recovery (default), c37 tolerant thresholds, "
                             "or c32-c34 immediate disable")
    args = parser.parse_args()
    # Unfinished timeouts and consecutive failures that disable the reader (c35: 3 and 4, c37: 6 and 8).
    HUNG_N, RUN_N = (6, 8) if args.deadline_policy == 'tolerant' else (3, 4)
    RECOVER = args.deadline_policy in ('recoverable', 'tolerant')
    pkg = args.pkg.resolve()
    protected = HERE.parent / "pkgs"
    if pkg == protected or protected in pkg.parents:
        parser.error("Use a copy under /tmp, not work/pkgs")
    if not 0 < args.timeout <= 10 or not 0 <= args.random <= 1000:
        parser.error("Use timeout in (0,10] and random count in [0,1000]")
    signal.signal(signal.SIGALRM, alarm)
    sys.path.insert(0, str(pkg))
    import guider_log as gm
    import llm_strategist as lm
    import policy as pm
    import numpy as np
    when = None
    if (pkg / 'when_text.py').exists():
        import when_text as when
    lm._emit = lambda obj: None
    pm._log = lambda obj: None
    suite = Suite(args.timeout)
    gl_cls, duty_cls = gm.GuiderLog, lm.DutyReader

    # Warm a real deterministic reader once, then copy its small state per case.
    source = (HERE / "variants/original/A1.log.txt").read_text(encoding="utf-8")
    chunks = re.split(r"^#### issued ([^\n]+)\n", source, flags=re.M)
    warm = gl_cls(-4, ISSUED, ISSUED + 120 * 86400)
    warm.read(chunks[2], ISSUED)

    def fresh(seed=True, end=None):
        return copy.deepcopy(warm) if seed and end is None else gl_cls(-4, ISSUED, end or ISSUED + 120 * 86400)

    def assert_state(gl, before):
        for key, c in gl.cands.items():
            t = c["t"]
            require(math.isfinite(t), "non-finite candidate")
            if key not in before:
                require(ISSUED - 2 * 86400 <= t <= ISSUED + 12 * 86400, "new candidate outside merge horizon")
                require(t <= gl.t1, "new candidate beyond season end")
        for a, b in gl.flats:
            require(math.isfinite(a) and math.isfinite(b) and 0 < b - a <= 4 * 3600, "invalid flat interval")
        gl.known_summary(ISSUED, lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%m/%d %H:%M"))

    def merge(payload, cleaned=False):
        gl = fresh()
        before = set(gl.cands)
        item = duty_cls._clean(payload) if cleaned else payload
        if item is not None or not cleaned:
            gl.add_llm(item, ISSUED)
        assert_state(gl, before)

    malformed = [None, True, 7, 1.5, "oops", [], [None], {}, {"x": []}]
    payloads = [("root_" + str(i), v) for i, v in enumerate(malformed)]
    for field in FIELDS:
        for i, value in enumerate(malformed + [[None], [7], ["oops"], [{}], [{"date": ["10/2"]}]]):
            payloads.append((field + "_" + str(i), {field: value}))
    variants = {
        "shift_inf": {"shift_minutes": float("inf")},
        "shift_neginf": {"shift_minutes": float("-inf")},
        "shift_nan": {"shift_minutes": float("nan")},
        "shift_exp": {"shift_minutes": "1e309"},
        "shift_large": {"shift_minutes": 10**50},
        "shift_negative": {"shift_minutes": -10**50},
        "shift_nested": {"shift_minutes": [[{"x": 60}]]},
        "shift_badtext": {"shift_minutes": "several minutes"},
        "date_bad": {"date": "2/30"}, "date_type": {"date": ["10/2"]},
        "time_bad": {"time": "25:99"}, "time_negative": {"time": "-1:30"},
        "clock_bad": {"clock": "garbage"}, "clock_large": {"clock": "UTC+99:99"},
        "relative_string": {"relative_to": "window_end"},
        "relative_kind": {"relative_to": {"kind": "gibberish"}},
        "index_inf": {"relative_to": {"kind": "window_end", "date": "10/1", "index": "inf"}},
        "index_zero": {"relative_to": {"kind": "window_end", "date": "10/1", "index": 0}},
        "index_negative": {"relative_to": {"kind": "window_end", "date": "10/1", "index": -1}},
        "index_bad": {"relative_to": {"kind": "window_end", "date": "10/1", "index": "first-ish"}},
    }
    for name, patch in variants.items():
        payloads.append((name, {"fault_starts": [{**FAULT, **patch}]}))
    payloads += [("window_bad_hm", {"lost_windows": [{**WINDOW, "start": "25:90", "end": "26:00"}]}),
                 ("huge_integer", {"fault_starts": [{**FAULT, "shift_minutes": 10**5000}]}),
                 ("many_entries", {"fault_starts": [dict(FAULT) for _ in range(5000)]}),
                 ("many_keys", {"active_faults": [{f"junk_{i}": "x" for i in range(5000)}]})]
    rng = random.Random(args.seed)
    atoms = malformed + ["UTC-13", "10/2", "22:30", "inf", -999999, {"kind": "window_end", "index": []}]
    for i in range(args.random):
        f = dict(FAULT)
        for _ in range(rng.randrange(1, 5)):
            f[rng.choice(["date", "time", "clock", "shift_minutes", "relative_to", "status", "quote"])] = rng.choice(atoms)
        payloads.append((f"random_{i:03d}", {rng.choice(FIELDS): [f, rng.choice(atoms)]}))
    for name, payload in payloads:
        for clean in (False, True):
            suite.case(("clean_merge/" if clean else "raw_merge/") + name,
                       lambda p=payload, c=clean: merge(p, c), payload, "fuzz")

    for name, patch in variants.items():
        if name in ("date_bad", "time_bad", "time_negative", "date_type", "clock_bad", "clock_large", "relative_string", "relative_kind", "index_zero", "index_negative", "index_bad", "shift_inf", "shift_nan", "shift_exp", "shift_large", "shift_negative", "shift_nested", "shift_badtext"):
            item = {**FAULT, **patch}
            suite.case("reject/" + name, lambda f=item: require(fresh().llm_time(f, ISSUED) is None, "invalid item accepted as a timestamp"), item)
    for value in malformed:
        suite.case("helper/time_" + type(value).__name__, lambda v=value: fresh().llm_time(v, ISSUED))
        suite.case("helper/window_" + type(value).__name__, lambda v=value: fresh().llm_window(v, ISSUED))
    suite.case("helper/window_invalid_clock", lambda: require(fresh().llm_window({**WINDOW, "start": "25:90", "end": "26:45"}, ISSUED) is None, "invalid clock normalized into a valid window"))
    suite.case("helper/uninitialized_windows", lambda: require(fresh(False).llm_time({"relative_to": {"kind": "window_end", "date": "10/2", "index": 1}}, ISSUED) is None, "missing windows should give None"))
    for label in ('UTC+bogus', 'UTC+', 'not Tokyo', 'UTC+14:01', 'UTC+5:75', 'UTC+999'):
        suite.case('reject/clock_' + label, lambda label=label: require(fresh()._clock(label) is None, 'invalid clock accepted'), {'clock': label})
    for label, offset in [('local', -4.), ('UTC', 0.), ('UTC+05:30', 5.5), ('UTC-13', -13.), ('Tokyo', 9.), ('JST', 9.)]:
        suite.case('control/clock_' + label, lambda label=label, offset=offset: require(fresh()._clock(label) == offset, 'valid clock changed'))

    def late():
        gl = fresh(False, ISSUED + 86400)
        gl.add_llm({"fault_starts": [{**FAULT, "date": "10/5"}]}, ISSUED)
        assert_state(gl, set())
    suite.case("regression/season_end", late)

    def inactive():
        gl = fresh(False)
        gl.add_llm({"fault_starts": [dict(FAULT)]}, ISSUED)
        require(gl.active and len(gl.probes()) == 1, "LLM-only fault did not activate guider path")
    suite.case("regression/llm_only_activation", inactive)

    def empty_active():
        gl = fresh(False)
        gl.add_llm(duty_cls._clean({"active_faults": [{}]}), ISSUED)
        require(not gl.probes(), "empty active-fault object creates immediate probe")
    suite.case("regression/empty_active", empty_active)

    def windows_union():
        gl = fresh(False)
        gl.read("【值班】10/2 当晚平场灯测试 20:00到20:15，不是故障。", ISSUED)
        gl.add_llm({"lost_windows": [WINDOW]}, ISSUED)
        actual = gl.llm_time({"relative_to": {"kind": "window_end", "date": "10/2", "index": 2}}, ISSUED)
        expected = datetime(2026, 10, 3, 1, 15, tzinfo=timezone.utc).timestamp()
        require(actual == expected, "second model window hidden by existing rule window")
    suite.case("regression/window_union", windows_union)

    def many_bounded():
        gl = fresh(False)
        n = gl.add_llm({"fault_starts": [dict(FAULT) for _ in range(5000)]}, ISSUED)
        require(n['new'] + n['agree'] <= (480 if when else 60), "raw answer exceeded bounded section record count")
    suite.case("regression/input_cap", many_bounded)

    def duty(answer=None, behavior=None):
        d = duty_cls.__new__(duty_cls)
        d.enabled, d.dead = True, False
        d.calls = d.ok = d.failed = 0
        d.wall = 0.0
        d.max_calls, d.wall_cap, d.question_deadline, d.attempt_timeout = 150, 10.0, 0.04, 0.04
        d.rules, d._rule_keys = [], set()
        d.client = SimpleNamespace(ask=behavior or (lambda *a, **kw: (answer, {})))
        return d

    def read_stub(answer):
        d = duty(answer)
        out = d.read(["设备交接"], {}, "2026-10-01 20:00", -4, {})
        require(d.calls == 1 and math.isfinite(d.wall), "invalid read accounting")
        require(out is None or isinstance(out, dict), "invalid cleaned reply")
    for value in payloads[:9] + payloads[-4:]:
        suite.case("duty/read_" + value[0], lambda v=value[1]: read_stub(v), value[1])

    def release_workers(release, workers):
        # Always release fake clients, including when an assertion/alarm fires.
        release.set()
        for worker in workers:
            if worker is not threading.current_thread():
                worker.join(timeout=0.10)

    def blocked_client(release, workers):
        def blocked(*a, **kw):
            workers.append(threading.current_thread())
            release.wait(timeout=0.65)
            return {key: [] for key in FIELDS}, {}
        return blocked

    def timed_read(d):
        start = time.monotonic()
        answer = d.read(["交接"], {}, "2026-10-01", -4, {})
        elapsed = time.monotonic() - start
        require(elapsed < 0.12, f"question_deadline=0.04s but blocked {elapsed:.3f}s")
        return answer

    def successful_read(d):
        d.client = SimpleNamespace(ask=lambda *a, **kw: ({key: [] for key in FIELDS}, {}))
        result = timed_read(d)
        require(isinstance(result, dict) and not d.dead and d.fail_run == 0,
                "successful retry did not clear consecutive failures")

    def deadline():
        release, workers = threading.Event(), []
        d = duty(behavior=blocked_client(release, workers))
        try:
            require(timed_read(d) is None, "timed-out call must not return a late answer")
            require(d.failed == 1 and d.fail_run == 1 and d.ok == 0, "timeout must count as one failure")
            if args.deadline_policy == 'disable':
                require(d.dead, "legacy timeout contract must disable future calls")
            else:
                require(not d.dead, "one timeout must remain recoverable in c35")
                # Recovery must work even while the earlier answer is unfinished.
                successful_read(d)
                require(d.ok == 1 and d.failed == 1, "late worker altered retry accounting")
        finally:
            release_workers(release, workers)
    suite.case("duty/hard_deadline", deadline)

    if RECOVER:
        def three_unfinished():
            release, workers = threading.Event(), []
            d = duty(behavior=blocked_client(release, workers))
            try:
                for i in range(1, HUNG_N + 1):
                    require(timed_read(d) is None, "unfinished call returned a result")
                    require(len(workers) == i and d.failed == i and d.fail_run == i, "timeout accounting mismatch")
                    require(d.dead == (i == HUNG_N), f"disable only at unfinished timeout {HUNG_N}")
                before = d.calls
                require(timed_read(d) is None and d.calls == before and len(workers) == HUNG_N,
                        "disabled reader started another worker")
            finally:
                release_workers(release, workers)
        suite.case("duty/three_unfinished_timeouts", three_unfinished)

        def completed_workers(retry_between):
            d = duty()
            for i in range(1, RUN_N + 1):
                release, workers = threading.Event(), []
                d.client = SimpleNamespace(ask=blocked_client(release, workers))
                try:
                    require(timed_read(d) is None, "timeout returned an answer")
                    require(d.failed == i, "completed timeout disappeared from failure count")
                    expected_dead = not retry_between and i == RUN_N
                    require(d.dead == expected_dead,
                            f"completed workers counted as unfinished, or {RUN_N} consecutive failures did not disable")
                finally:
                    release_workers(release, workers)
                if retry_between:
                    successful_read(d)
            if retry_between:
                require(d.ok == RUN_N and d.fail_run == 0 and not d.dead, "successful retries failed to reset the streak")
            else:
                require(d.fail_run == RUN_N, f"{RUN_N} sequential timeouts must count as {RUN_N} failures")
                before = d.calls
                timed_read(d)
                require(d.calls == before, f"reader retried after {RUN_N} consecutive timeouts")
        suite.case("duty/completed_timeout_workers_pruned", lambda: completed_workers(True))
        suite.case("duty/four_sequential_timeouts", lambda: completed_workers(False))

        def four_failures():
            d = duty(behavior=lambda *a, **kw: (None, {'error': 'local fake failure'}))
            for i in range(1, RUN_N + 1):
                require(timed_read(d) is None, "failed call returned a result")
                require(d.failed == i and d.fail_run == i and d.dead == (i == RUN_N),
                        f"ordinary failures must disable only on consecutive failure {RUN_N}")
            before = d.calls
            timed_read(d)
            require(d.calls == before, f"reader retried after {RUN_N} consecutive failures")
        suite.case("duty/four_consecutive_failures", four_failures)

    def raised():
        def fail(*a, **kw):
            raise ValueError("local fake failure")
        d = duty(behavior=fail)
        require(d.read(["交接"], {}, "2026-10-01", -4, {}) is None, "failed call should fall back")
        require(d.failed == 1 and d.wall >= 0, "failed call not accounted")
    suite.case("duty/client_exception", raised)

    def rules():
        d = duty()
        notices = [f"从今天起规则{i}＝含义{i}" for i in range(20)]
        for text in notices:
            d._remember_rules([text], {})
        require(len(d.rules) <= 12 and len(d._rule_keys) <= 12, "rule-key memory exceeds retained rules")
        d._remember_rules([notices[0]], {})
        require(notices[0] in d.rules, "evicted rule cannot be remembered again")
    suite.case("duty/rule_retention", rules)

    def colliding_rule():
        d = duty()
        prefix = "从今天起" + "交接本长期统一说明" * 6
        old, new = prefix + "＝旧定义", prefix + "＝新定义"
        d._remember_rules([old, new], {})
        require(new in d.rules, "different rules sharing first 40 normalized characters collide")
    suite.case("duty/rule_prefix_collision", colliding_rule)

    # No full policy setup: only tiny arrays for isolated report/ratio logic.
    def policy_stub(gl=None):
        p = pm.Policy.__new__(pm.Policy)
        p.p = dict(pm.DEFAULTS)
        p.glog = gl or fresh(False)
        p.g_probe, p.g_done, p.g_report = {}, set(), None
        p.g_hist = []
        p.g_dead_since, p.g_dead_hold, p.g_dead_false, p.g_dead_n = None, -1e18, 0, 0
        p.g_false = p.g_correct = p.false_since_correct = p.g_skip = 0
        p.correct_reports = 0
        p.reports = p.paid_reports = p.consec_reports = 0
        p.free_reports, p.last_correct_t, p.last_report_t = 2, -1e18, -1e18
        p.night_ends = np.array([ISSUED + 86400])
        p.flux, p.mult, p.q0, p.f0t0 = np.array([1., 2.]), np.array([1., 1., 1.]), 1., 1.
        p.bel = SimpleNamespace(peek=lambda *a: (0., 1.), leta=0., quake_factor=lambda *a: 1.)
        return p

    def dead_overflow():
        p = policy_stub()
        p.g_dead_false = 1024
        p._g_outcome({"why": "dead"}, False, ISSUED)
        require(0 <= p.g_dead_hold - ISSUED <= 28800, "backoff out of bounds")
    suite.case("policy/dead_backoff_overflow", dead_overflow)

    def ratio(mean=0., nan_y=False):
        p = policy_stub()
        p.bel.peek = lambda *a: (mean, 1.)
        y = np.array([float("nan"), float("nan")]) if nan_y else np.array([0.5, 0.5])
        r = p._obs_ratio(ISSUED, 1., 0, np.array([0, 1]), y, np.ones(2), 0, {})
        require(r is None or (math.isfinite(r) and r >= 0), "non-finite or negative observation ratio")
    suite.case("policy/ratio_overflow", lambda: ratio(1000.))
    suite.case("policy/ratio_nan", lambda: ratio(nan_y=True))
    suite.case("policy/ratio_normal", ratio)

    def policy_probe():
        gl = fresh(False)
        gl.add_llm({"fault_starts": [{**FAULT, "date": "10/1", "time": "21:30"}]}, ISSUED)
        p = policy_stub(gl)
        action, cap = p._guider_step(ISSUED + 7200, 0)
        require(action is None and p.g_probe and cap == p.p['g_probe_T'], "LLM-only candidate never armed for a short exposure")
        p._obs_ratio = lambda *a: 0.01
        args = (ISSUED + 7200, 60., ISSUED + 7260, 0, np.array([0, 1]), np.ones(2), np.ones(2), 0, {})
        require(p._guider_obs(*args), "low-throughput probe should stay out of belief")
        action, cap = p._guider_step(ISSUED + 7260, 0)
        require(action == {'action': 'report'} and p.pending['guider']['why'] == 'probe', "probe did not schedule a report")
    suite.case("policy/llm_probe_to_report", policy_probe)

    def flat_wait():
        gl = fresh(False)
        gl.flats[(ISSUED + 10, ISSUED + 50)] = (2026, 10, 1)
        p = policy_stub(gl)
        action, cap = p._guider_step(ISSUED + 11, 0)
        until = datetime.fromisoformat(action['until_utc'].replace('Z', '+00:00')).timestamp()
        require(action['action'] == 'wait' and ISSUED + 11 < until <= p.night_ends[0], "flat wait does not advance within night")
    suite.case("policy/flat_wait_progress", flat_wait)

    def correct_outcome():
        p = policy_stub()
        p.g_dead_since, p.g_dead_n, p.g_dead_false = ISSUED, 4, 3
        p.bel.w, p.bel.x, p.bel.P = np.array([1., 0.]), np.ones((2, 1)), np.ones((2, 1, 1))
        p._g_report(ISSUED, {'why': 'dead'})
        require(p.reports == 1 and p.paid_reports == 0 and p.pending['kind'] == 'report', "report counters invalid")
        p._g_outcome({'why': 'dead'}, True, ISSUED + 1)
        require(p.g_correct == 1 and p.g_dead_since is None and p.g_dead_n == 0 and p.g_dead_false == 0, "correct report did not reset detector")
    suite.case("policy/report_and_correct_outcome", correct_outcome)

    def dead_detection():
        p = policy_stub()
        p.glog.flats[(ISSUED + 3600, ISSUED + 3660)] = (2026, 10, 1)
        p._obs_ratio = lambda *a: 0.01
        if hasattr(p, '_g_precursor'):
            p.g_hist = [(ISSUED - 300, ISSUED - 180, 0.3), (ISSUED - 120, ISSUED - 60, 0.3)]
        for i in range(2):
            start = ISSUED + i * 60
            p._guider_obs(start, 60., start + 60, 0, np.array([0, 1]), np.ones(2), np.ones(2), 0, {})
            if i == 0:
                require(p.g_report is None, "one low exposure should not trip dead detector")
        require(p.g_report and p.g_report['why'] == 'dead', "two low exposures did not trip detector")
        p._obs_ratio = lambda *a: 1.
        p._guider_obs(ISSUED + 120, 60., ISSUED + 180, 0, np.array([0, 1]), np.ones(2), np.ones(2), 0, {})
        require(p.g_dead_since is None and p.g_dead_n == 0, "healthy throughput did not reset detector")
    suite.case("policy/dead_detector_two_exposures", dead_detection)

    def duty_caller_guard():
        p = policy_stub()
        p.log_off_s, p.t_real0, p.g_err = -4 * 3600., time.monotonic(), False
        p.dlm = SimpleNamespace(read=lambda *a, **kw: {'fault_starts': [None]})
        p._duty_read('【值班】10/2 22:30 设备开工。', ISSUED)
        require(not p.g_probe, "malformed callback produced active probe")
    suite.case("policy/duty_call_exception_boundary", duty_caller_guard)

    def no_budget_call():
        def forbidden(*a, **kw):
            raise AssertionError('budget exhausted but client called')
        for field, value in [('dead', True), ('calls', 150), ('wall', 10.)]:
            d = duty(behavior=forbidden)
            setattr(d, field, value)
            require(d.read([], {}, '2026-10-01', -4, {}) is None, 'budget guard did not return None')
    suite.case("duty/exhausted_budget", no_budget_call)

    def valid():
        gl = fresh(False)
        gl.add_llm({"fault_starts": [{**FAULT, "clock": "UTC+9", "shift_minutes": 15}], "lost_windows": [WINDOW]}, ISSUED)
        expected = datetime(2026, 10, 2, 13, 45, tzinfo=timezone.utc).timestamp()
        require([c["t"] for c in gl.probes()] == [expected], "valid fault/shift/zone regression")
        require(len(gl.flats) == 1, "valid window lost")
    suite.case("control/valid_llm", valid)

    def valid_after_bad(cleaned):
        gl = fresh(False)
        payload = {'fault_starts': [{**FAULT, 'shift_minutes': '1e309'}, dict(FAULT)],
                   'lost_windows': [None, dict(WINDOW)], 'active_faults': [{}]}
        gl.add_llm(duty_cls._clean(payload) if cleaned else payload, ISSUED)
        require(len(gl.probes()) == 1 and len(gl.flats) == 1, 'bad item prevented later valid records from merging')
    suite.case('control/valid_after_bad_raw', lambda: valid_after_bad(False))
    suite.case('control/valid_after_bad_cleaned', lambda: valid_after_bad(True))

    if when is not None:
        from datetime import date
        d0 = date(2026, 10, 1)
        weird = [None, False, True, 3, 1e309, [], {}, ['10/2'], {'x': '21:30'},
                 '2/30', '2026-02-29', '-1/2', '25:99', '24:30', '-1:30',
                 'D+' + '9' * 5000, 'x' * 50000, ' ' * 50000]
        def date_probe(value, anchor=d0):
            result = when.date_from_text(value, anchor)
            if result is not None:
                require(isinstance(result, tuple) and len(result) == 2, 'invalid date shape')
                date(2000, *result)  # structural calendar validity, permitting leap day
        def time_probe(value):
            result = when.time_from_text(value)
            if result is not None:
                h, m = result
                require((0 <= h < 24 and 0 <= m < 60) or (h, m) == (24, 0), 'invalid time bounds')
        for i, value in enumerate(weird):
            suite.case(f'c33/date_type_{i}', lambda value=value: date_probe(value), category='c33')
            suite.case(f'c33/time_type_{i}', lambda value=value: time_probe(value), category='c33')
        for anchor in [None, 1, '2026-10-01', [], {}, date.min, date.max]:
            for word in ['明天', '昨天']:
                suite.case(f'c33/date_anchor_{type(anchor).__name__}_{word}_{str(anchor)[:12]}',
                           lambda anchor=anchor, word=word: date_probe(word, anchor), category='c33')
        for text, expected in [('quarter to twelve a.m.', (23, 45)), ('quarter to twelve p.m.', (11, 45)),
                               ('ten minutes to twelve a.m.', (23, 50)), ('24:00', (24, 0)),
                               ('24:30', None), ('-1:30', None), ('sample: 9:30 PM', (21, 30)),
                               ('9:30 AM PM', None), ('午後9時半', (21, 30)), ('2130 hours', (21, 30))]:
            suite.case('c33/time_value/' + text, lambda text=text, expected=expected:
                       require(when.time_from_text(text) == expected, 'incorrect verbatim clock conversion'), category='c33')
        for text, expected in [('2/30', None), ('2026-02-29', None), ('-1/2', None),
                               ('Oct 5', (10, 5)), ('5 October 2026', (10, 5)), ('后天', (10, 3)),
                               ('2024-02-29', (2, 29)), ('2026-10-05', (10, 5))]:
            suite.case('c33/date_value/' + text, lambda text=text, expected=expected:
                       require(when.date_from_text(text, d0) == expected, 'incorrect verbatim date conversion'), category='c33')

        for i, value in enumerate(weird[:10]):
            suite.case(f'c33/helper_date_of_{i}', lambda value=value: fresh()._date_of(value, ISSUED), category='c33')
            suite.case(f'c33/helper_time_of_{i}', lambda value=value: fresh()._time_of(value), category='c33')
            suite.case(f'c33/helper_label_{i}', lambda value=value:
                       require(fresh()._label(value) == '' or isinstance(value, str), 'non-string label accepted'), category='c33')
            suite.case(f'c33/helper_source_{i}', lambda value=value:
                       require(fresh()._src_line(value, [None, 2, {}, 'a clock 21:30']) is None, 'non-string quote accepted'), category='c33')
        suite.case('c33/source_bad_lines', lambda: fresh()._src_line('valid quote', [None, 2, {}]), category='c33')
        suite.case('c33/label_huge_integer', lambda: fresh()._label(10**5000), category='c33')
        def source_unique():
            lines = ['common engineering notice: OLD start', 'common engineering notice: NEW start']
            require(fresh()._src_line(lines[1], lines) == lines[1], 'prefix matched wrong source line')
        suite.case('c33/source_exact_before_prefix', source_unique, category='c33')

        for i, f in enumerate([{**FAULT, 'date_text': '2/30'}, {**FAULT, 'time_text': 'x' * 50000},
                               {**FAULT, 'quote': 10**5000, 'night': '10/2', 'date_text': '那晚', 'time': '01:30'},
                               {'relative_to': {'kind': 'window_end', 'label': 10**5000}}]):
            suite.case(f'c33/merge_new_fields_{i}', lambda f=f: fresh().add_llm({'fault_starts': [f]}, ISSUED, lines=[None, 3, {}, 'text']), category='c33')
        for i, kwargs in enumerate([{'issued': None}, {'issued': 'bad'}, {'issued': float('inf')},
                                    {'utc_offset': []}, {'before': '7'}, {'after': 10**9}, {'before': -9}]):
            params = {'issued': ISSUED, 'utc_offset': -4, **kwargs}
            def calendar(params=params):
                values = lm.duty_calendar(**params)
                require(isinstance(values, list) and len(values) <= 121, 'calendar is unbounded')
            suite.case(f'c33/calendar_{i}', calendar, params, 'c33')

        def captured_read(lines, hints=None, chunk_chars=12000, replies=None):
            calls = []
            d = duty()
            d.max_calls, d.wall_cap, d.question_deadline = 150, 10., 0.05
            def ask(*args, **kwargs):
                payload = json.loads(args[1]); calls.append(payload)
                value = replies[len(calls) - 1] if replies and len(calls) <= len(replies) else {k: [] for k in FIELDS}
                return value, {}
            d.client = SimpleNamespace(ask=ask)
            result = d.read(lines, hints if hints is not None else {}, '2026-10-01', -4, {},
                            real_left=300., issued=ISSUED, chunk_chars=chunk_chars)
            require(len(calls) <= 4, 'more than 4 chunk calls')
            return result, calls
        for i, lines in enumerate([None, 3, {}, 'a line', [], [None], [2, 'valid line'], ['']]):
            suite.case(f'c33/read_lines_{i}', lambda lines=lines: captured_read(lines), category='c33')
        for i, hints in enumerate([None, 3, [], {'9' * 5000: 'hint'}, {'0': {}}, {'0': None}]):
            suite.case(f'c33/read_hints_{i}', lambda hints=hints: captured_read(['a valid line'], hints), category='c33')
        for size in [None, '5', -1, 0, float('inf'), 16]:
            suite.case(f'c33/chunk_budget_{str(size)}', lambda size=size: captured_read(['a line'] * 25, chunk_chars=size), category='c33')
        def long_line():
            result, calls = captured_read(['x' * 50000])
            require(all(sum(len(x) for x in c['log_lines']) <= 12000 for c in calls), 'oversized single line bypassed chunk budget')
        suite.case('c33/chunk_single_long_line', long_line, category='c33')
        def partial_chunks():
            result, calls = captured_read(['x' * 11000 for _ in range(8)])
            require(result is None or result.get('_complete') is False, 'unread tail not marked incomplete')
        suite.case('c33/chunk_partial_coverage', partial_chunks, category='c33')
        def failed_chunk():
            result, calls = captured_read(['x' * 6000 for _ in range(4)], replies=[{k: [] for k in FIELDS}, None])
            require(result is None or result.get('_complete') is False, 'failed chunk not marked incomplete')
        suite.case('c33/chunk_failed_coverage', failed_chunk, category='c33')
        def empty_no_call():
            result, calls = captured_read([])
            require(result is None and not calls, 'empty section makes a request')
        suite.case('c33/control_empty_no_call', empty_no_call, category='c33')
        def hint_reindex():
            result, calls = captured_read(['a' * 6000, 'b' * 6000, 'c' * 6000], {'2': 'hint-c'})
            for c in calls:
                for key, hint in c['decoded_hints'].items():
                    if hint == 'hint-c':
                        require(c['log_lines'][int(key)].startswith('c'), 'hint attached to wrong chunk line')
        suite.case('c33/control_hint_reindex', hint_reindex, category='c33')

        def official():
            gl = fresh(False)
            gl.read('10/2 22:30 动导星相机，到点报修。', ISSUED)
            return gl
        def partial_strict():
            gl = official()
            gl.add_llm({**{k: [] for k in FIELDS}, '_complete': False}, ISSUED)
            require(len(gl.due()) == 1, 'partial reply downgraded unread deterministic job')
        suite.case('c33/strict_partial', partial_strict, category='c33')
        def malformed_strict():
            gl = official()
            gl.add_llm({'unrelated': 'garbage'}, ISSUED)
            require(len(gl.due()) == 1, 'non-schema answer downgraded deterministic job')
        suite.case('c33/strict_invalid_schema', malformed_strict, category='c33')
        def complete_strict():
            gl = official()
            gl.add_llm({k: [] for k in FIELDS}, ISSUED)
            require(not gl.due() and gl.probes()[0].get('dg'), 'complete strict reply must downgrade unconfirmed rule job')
        suite.case('c33/control_strict_complete', complete_strict, category='c33')
        def same_answer_priority():
            gl = official()
            gl.add_llm({'fault_starts': [{**FAULT, 'status': 'wrong'}, dict(FAULT)]}, ISSUED)
            require(len(gl.due()) == 1, 'withdrawal beat confirmation in same reply')
        suite.case('c33/control_confirmation_priority', same_answer_priority, category='c33')
        def later_withdrawal():
            gl = official()
            gl.add_llm({'fault_starts': [dict(FAULT)]}, ISSUED)
            gl.add_llm({'fault_starts': [{**FAULT, 'status': 'cancelled'}]}, ISSUED + 3600)
            require(not gl.due(), 'earlier llm_ok prevents later explicit withdrawal')
        suite.case('c33/withdrawal_after_confirmation', later_withdrawal, category='c33')
        def conditional_not_approved():
            gl = fresh(False)
            gl.add_llm({'fault_starts': [{**FAULT, 'status': 'conditional'}]}, ISSUED)
            require(not gl.probes()[0].get('llm_ok'), 'conditional new job marked confirmed')
        suite.case('c33/conditional_marked_confirmed', conditional_not_approved, category='c33')
        def calendar_windows():
            gl = fresh(False)
            windows = [{'date': '10/2', 'date_text': '2026-10-02', 'start': '23:00', 'end': '23:15', 'quote': 'ticket X on 2026-10-02 at 23:00'},
                       {'date': '10/2', 'date_text': '2026-10-02', 'start': '01:00', 'end': '01:15', 'quote': 'ticket Y on 2026-10-02 at 01:00'}]
            gl.add_llm({'lost_windows': windows}, ISSUED, lines=[w['quote'] for w in windows])
            expected = datetime(2026, 10, 2, 5, tzinfo=timezone.utc).timestamp()
            require(any(a == expected for a, b in gl.flats), 'independent calendar row rolled to tomorrow')
        suite.case('c33/calendar_rollover_scope', calendar_windows, category='c33')
        def valid_window_modes():
            gl = fresh(False)
            a = gl.llm_window({'date': '10/2', 'start': '23:45', 'end_date': '10/3', 'end': '00:15'}, ISSUED)
            b = gl.llm_window({'night': '10/2', 'start': '01:00', 'end': '01:15'}, ISSUED)
            require(a and a[1] - a[0] == 1800 and b and datetime.fromtimestamp(b[0], timezone.utc).day == 3, 'calendar/night/end_date control failed')
        suite.case('c33/control_window_modes', valid_window_modes, category='c33')
        def invalid_end():
            require(fresh(False).llm_window({'date': '10/2', 'start': '23:45', 'end_date': '2/30', 'end': '00:15'}, ISSUED) is None, 'invalid explicit end_date inferred away')
        suite.case('c33/invalid_explicit_end_date', invalid_end, category='c33')
        def known_night_and_label():
            gl = fresh(False)
            gl.read('10/2 当晚平场灯测试 20:00到20:15、21:00到21:15，不是故障。', ISSUED)
            gl.add_llm({'lost_windows': [{**WINDOW, 'label': 'C-1'}, {**WINDOW, 'start': '22:00', 'end': '22:15', 'label': 'extra'}],
                        'closures': [{**WINDOW, 'night': '10/4'}]}, ISSUED)
            require(len(gl.flats) == 2, 'known-night guard or closure exclusion changed')
            result = gl.llm_time({'relative_to': {'kind': 'window_end', 'label': 'C-1'}, 'shift_minutes': 15}, ISSUED)
            require(result == datetime(2026, 10, 3, 1, 30, tzinfo=timezone.utc).timestamp(), 'label mapping to existing window failed')
        suite.case('c33/control_known_night_label_closure', known_night_and_label, category='c33')

        for i, (f, hm, tz) in enumerate([(None, (21, 30), -4), ({}, None, -4),
                                        ({}, ([], 2), -4), ({}, (25, 99), -4),
                                        ({}, (21, 30), 'UTC'), ({}, (21, 30), float('inf'))]):
            suite.case(f'c33/when_direct_{i}', lambda f=f, hm=hm, tz=tz:
                       require(fresh()._when(f, hm, tz, ISSUED) is None, 'invalid _when accepted'), category='c33')
        suite.case('c33/night_windows_nested_key', lambda: require(fresh()._night_windows(([], 1, 2)) == [], 'bad night tuple accepted'), category='c33')
        suite.case('c33/window_huge_date_text', lambda: fresh().llm_window({**WINDOW, 'date': '10/2', 'date_text': 10**5000}, ISSUED), category='c33')

        def shared_source_roll():
            gl = fresh(False)
            line = '10/2 night list: 23:00-23:15; 01:00-01:15'
            gl.add_llm({'lost_windows': [{'date': '10/2', 'start': '23:00', 'end': '23:15', 'quote': line},
                                        {'date': '10/2', 'start': '01:00', 'end': '01:15', 'quote': line}]},
                       ISSUED, lines=[line])
            expected = datetime(2026, 10, 3, 5, tzinfo=timezone.utc).timestamp()
            require(any(a == expected for a, b in gl.flats), 'one nightly list no longer rolls after midnight')
        suite.case('c33/control_shared_source_roll', shared_source_roll, category='c33')
        def label_ambiguity():
            gl = fresh(False)
            gl.add_llm({'lost_windows': [{**WINDOW, 'label': 'C-1'}, {**WINDOW, 'night': '10/3', 'label': 'C-1'}]}, ISSUED)
            require(gl._label_window('C1', ISSUED) is None, 'ambiguous label selected an arbitrary window')
        suite.case('c33/control_ambiguous_label', label_ambiguity, category='c33')
        def source_preserves_calendar():
            gl = fresh(False)
            quote = 'ticket date 10/2 at 01:30'
            f = {**FAULT, 'date': '10/2', 'night': '10/2', 'date_text': '10/2 night', 'time': '01:30', 'quote': quote}
            t = gl.llm_time(f, ISSUED, lines=[quote])
            require(t == datetime(2026, 10, 2, 5, 30, tzinfo=timezone.utc).timestamp(), 'calendar source evidence ignored')
        suite.case('c33/control_source_calendar', source_preserves_calendar, category='c33')
        def remaining_budget():
            d = duty()
            d.question_deadline = 120.
            seen = []
            def stub(lines, hints, local, offset, known, real_left, cal):
                seen.append(real_left)
                time.sleep(0.005)
                return {**{k: [] for k in FIELDS}, '_complete': True}
            d._read1 = stub
            d.read(['x' * 6000 for _ in range(3)], {}, '2026-10-01', -4, {}, real_left=300., issued=ISSUED)
            require(len(seen) >= 2 and all(b < a for a, b in zip(seen, seen[1:])), 'chunk real_left never decreases')
        suite.case('c33/chunk_remaining_budget', remaining_budget, category='c33')
        def policy_truncated():
            p = policy_stub(official())
            p.log_off_s, p.t_real0, p.g_err = -4 * 3600., time.monotonic(), False
            p.dlm = SimpleNamespace(read=lambda *a, **kw: {k: [] for k in FIELDS})
            p._duty_read('\n'.join(['status unchanged'] * 401), ISSUED)
            require(len(p.glog.due()) == 1, 'policy silently truncated input before strict merge')
        suite.case('c33/policy_truncated_strict', policy_truncated, category='c33')
        def sudden_darkness():
            p = policy_stub()
            p.glog.flats[(ISSUED + 3600, ISSUED + 3660)] = (2026, 10, 1)
            p._obs_ratio = lambda *a: 0.01
            for i in range(2):
                start = ISSUED + i * 60
                p._guider_obs(start, 60., start + 60, 0, np.array([0, 1]), np.ones(2), np.ones(2), 0, {})
            require(p.g_report is None, 'sudden dark test window reported before wait')
            require(p._g_sudden_dark(ISSUED + 120), 'sudden-dark veto missing')
            start = ISSUED + p.p['g_dead_wait']
            p._guider_obs(start, 60., start + 60, 0, np.array([0, 1]), np.ones(2), np.ones(2), 0, {})
            require(p.g_report and p.g_report['why'] == 'dead', 'sustained darkness never reports')
        suite.case('c33/control_sudden_darkness_wait', sudden_darkness, category='c33')

        def overlapping_window_index():
            gl = fresh(False)
            gl.read('10/2 当晚平场灯测试 20:00到20:15、21:00到21:15，不是故障。', ISSUED)
            gl.add_llm({'lost_windows': [{**WINDOW, 'start': '20:01', 'end': '20:16', 'label': 'Alias'}]}, ISSUED)
            t = gl.llm_time({'relative_to': {'kind': 'window_end', 'date': '10/2', 'index': 2}}, ISSUED)
            require(t == datetime(2026, 10, 3, 1, 15, tzinfo=timezone.utc).timestamp(), 'overlap alias changed the second window index')
        suite.case('c33/control_overlapping_window_index', overlapping_window_index, category='c33')

    if hasattr(pm.Policy, '_g_many'):
        for count, expected in [(0, False), (6, False), (7, True), (8, True), (50, True)]:
            def many_count(count=count, expected=expected):
                p = policy_stub(); p.correct_reports = count
                require(bool(p._g_many()) == expected, 'incorrect silent-card threshold')
            suite.case(f'c35/many_count_{count}', many_count, category='c35')
        def many_without_reader():
            p = policy_stub(); p.glog = None; p.correct_reports = 99
            require(not p._g_many(), 'missing GuiderLog must keep optional path disabled')
        suite.case('c35/many_no_reader', many_without_reader, category='c35')
        def many_announced():
            p = policy_stub(); p.glog.flats[(ISSUED, ISSUED + 60)] = (2026, 10, 1)
            require(p._g_many(), 'known flat windows no longer enable busy-card protection')
        suite.case('c35/many_announced_windows', many_announced, category='c35')
        for i, value in enumerate([None, [], {}, 'bad', '1e309', float('inf'), float('nan'), 0, -1, True, 7.5]):
            def bad_threshold(value=value):
                p = policy_stub(); p.p['g_many_correct'] = value; p.correct_reports = 6
                require(not p._g_many(), 'invalid threshold enabled busy mode below default threshold')
                p.correct_reports = 7
                require(p._g_many(), 'invalid threshold failed to use default threshold')
            suite.case(f'c35/many_bad_threshold_{i}', bad_threshold, category='defensive_config')
        def missing_threshold():
            p = policy_stub(); p.p.pop('g_many_correct'); p.correct_reports = 7
            require(p._g_many(), 'missing threshold failed to use default')
        suite.case('c35/many_missing_threshold', missing_threshold, category='defensive_config')

        histories = [([], False), ([(-180, -120, .3)], False),
                     ([(-240, -180, .1), (-120, -60, .55)], True),
                     ([(-240, -180, .3), (-120, -60, .8)], False),
                     ([(-300, -240, .3), (-240, -180, .3), (-120, -60, .8)], False),
                     ([(-1500, -1440, .3), (-1400, -1340, .3)], False),
                     ([(-1260, -1200, .3), (-120, -60, .3)], True),
                     ([(-300, -240, .3), (-120, -60, float('nan'))], False),
                     ([(-300, -240, .3), (-120, -60, float('inf'))], False),
                     ([(-300, -240, .099), (-120, -60, .3)], False),
                     ([(-300, -240, .3), (-120, -60, .551)], False)]
        for i, (hist, expected) in enumerate(histories):
            def precursor(hist=hist, expected=expected):
                p = policy_stub(); p.g_hist = [(ISSUED + a, ISSUED + b, r) for a, b, r in hist]
                require(bool(p._g_precursor(ISSUED)) == expected, 'incorrect latest-two/20-minute precursor')
            suite.case(f'c35/precursor_history_{i}', precursor, category='c35')
        def expose(p, start, ratio):
            p._obs_ratio = lambda *a: ratio
            return p._guider_obs(start, 60., start + 60, 0, np.array([0, 1]), np.ones(2), np.ones(2), 0, {})
        def after_repair():
            p = policy_stub(); p.correct_reports = 7
            p.g_hist = [(ISSUED - 240, ISSUED - 180, .3), (ISSUED - 120, ISSUED - 60, .3)]
            p.bel.w, p.bel.x, p.bel.P = np.array([1., 0.]), np.ones((2, 1)), np.ones((2, 1, 1))
            p._g_outcome({'why': 'probe'}, True, ISSUED - 30)
            pre = p._g_precursor(ISSUED)
            expose(p, ISSUED, .01); expose(p, ISSUED + 60, .01)
            require(p.g_report is None, 'test window just after a repair caused a new dead report')
            require(not pre, 'pre-repair dim exposures reused as new fault precursor')
        suite.case('c35/precursor_excludes_pre_repair', after_repair, category='c35_regression')
        def silent_probe():
            p = policy_stub(); p.correct_reports = 7
            p.g_hist = [(ISSUED - 240, ISSUED - 180, .3), (ISSUED - 120, ISSUED - 60, .3)]
            require(not p.glog.active and not p.glog.flats, 'test must use silent logs')
            expose(p, ISSUED, .01)
            action, cap = p._guider_step(ISSUED + 60, 0)
            require(action is None and cap == p.p['g_probe_T'], 'silent-card dead detector did not cap exposure')
            expose(p, ISSUED + 60, .01)
            action, cap = p._guider_step(ISSUED + 120, 0)
            require(action == {'action': 'report'}, 'silent-card low-throughput report was gated out')
        suite.case('c35/silent_data_report_path', silent_probe, category='c35')
        def silent_ingest():
            p = policy_stub(); p.correct_reports = 7; p.p['min_hits'] = 2; p.p['terr_hi'] = 0
            p.index = {'a': 0, 'b': 1}; p.sprobe = None; p.mismatch = 1.; p.w = np.ones(2)
            p.best, p.gl = np.zeros(2), np.zeros(2); p.ledger = []; p.observes = 0; p.slot = 900.
            p.zero_pending = []; p.probe = 0; p.blocked = []
            p._calibrate = lambda *a: None; p._learn_terrain = lambda *a, **kw: None
            p._exact_H = lambda *a: np.ones(2); p._night_index = lambda *a: 0; p._event_activity = lambda *a: {}
            called = []
            p._guider_obs = lambda *a: called.append(a) or True
            p.pending = {'kind': 'observe', 't': ISSUED, 'T': 60., 'idx': np.array([0, 1]), 'P': 0,
                         'alt': np.array([80., 80.]), 'az': np.array([0., 0.])}
            p._ingest({'last_result': {'action': 'observe', 'hits': [{'target_id': 'a', 'score': .01}, {'target_id': 'b', 'score': .01}]}}, ISSUED + 60)
            require(len(called) == 1, 'ingest skipped guider observation on a fault-rich silent card')
        suite.case('c35/silent_ingest_entry', silent_ingest, category='c35')
        for count, cap_limit, expected in [(8, 8, True), (6, 6, False)]:
            def belief_cap(count=count, cap_limit=cap_limit, expected=expected):
                p = policy_stub(); p.correct_reports = count; p.max_consec = 4; p.quake_notice = False; p.upd_at_false = 0
                p.p['max_faults'] = cap_limit; p.p['ev_excuse'] = 0
                p.bel = SimpleNamespace(learning_quake=lambda *a: False, p_fault=lambda: .99, multi=False,
                                        pf_hist=[.99] * 5, n_upd=100, report_result=lambda *a: None)
                require(p._should_report(ISSUED, 0) == expected, 'silent many gate changed belief cap incorrectly')
            suite.case(f'c35/belief_cap_{count}', belief_cap, category='c35')
        def dark_streak_interrupted():
            p = policy_stub(); p.correct_reports = 7
            expose(p, ISSUED, .01)
            expose(p, ISSUED + 60, .1)
            reset = p.g_dead_since is None and p.g_dead_n == 0
            expose(p, ISSUED + p.p['g_dead_wait'], .01)
            require(p.g_report is None, 'two nonconsecutive dark exposures caused a dead report')
            require(reset, 'non-dead exposure failed to break consecutive dead streak')
        suite.case('c35/dead_streak_interrupted', dark_streak_interrupted, category='c35_regression')

        def flat_breaks_streak():
            p = policy_stub(); p.correct_reports = 7
            p.glog.flats[(ISSUED + 60, ISSUED + 120)] = (2026, 10, 1)
            expose(p, ISSUED, .01); expose(p, ISSUED + 60, .005)
            expose(p, ISSUED + p.p['g_dead_wait'], .01)
            require(p.g_report is None, 'known flat joined two unexplained dark dips into one report')
        suite.case('c35/known_flat_breaks_dead_streak', flat_breaks_streak, category='c35_regression')

    if RECOVER:
        def constructor_failure():
            previous = lm.threading
            def fail(*a, **kw):
                raise RuntimeError('local fake thread construction failure')
            lm.threading = SimpleNamespace(Thread=fail)
            d = duty()
            try:
                if args.deadline_policy == 'tolerant':
                    for i in range(1, RUN_N + 1):
                        require(timed_read(d) is None and d.failed == i and d.dead == (i == RUN_N),
                                'thread construction failure escaped reader accounting')
                else:
                    require(timed_read(d) is None and d.failed == 1 and d.dead,
                            'thread construction failure escaped reader accounting')
            finally:
                lm.threading = previous
        suite.case('c35/thread_constructor_failure', constructor_failure, category='c35_regression')
        def completed_at_deadline():
            # Deterministic deadline race: Queue.get sees a timeout, but by the
            # handler the current worker has already completed. Two older ones
            # remain alive; only their liveness matters, not a stale list entry.
            previous = lm.queue
            workers = []
            def ask(*a, **kw):
                workers.append(threading.current_thread())
                return {key: [] for key in FIELDS}, {}
            class DeadlineQueue:
                def __init__(self, maxsize=1):
                    self.ready = threading.Event()
                def put(self, value):
                    self.ready.set()
                def get(self, timeout):
                    require(self.ready.wait(.1), 'local fake worker failed to complete')
                    workers[-1].join(.1)
                    require(not workers[-1].is_alive(), 'race requires a completed current worker')
                    raise previous.Empty
            lm.queue = SimpleNamespace(Queue=DeadlineQueue, Empty=previous.Empty)
            d = duty(behavior=ask)
            d._hung = [SimpleNamespace(is_alive=lambda: True), SimpleNamespace(is_alive=lambda: True)]
            try:
                require(timed_read(d) is None and d.failed == 1, 'deadline race not counted as failure')
                require(not d.dead, 'completed current worker counted as third unfinished timeout')
            finally:
                lm.queue = previous
        suite.case('c35/completed_worker_at_deadline', completed_at_deadline, category='c35_regression')


    if RECOVER:
        def json_mode_inflight(plain=False):
            # Two already-sent JSON-mode requests can overlap after a timeout.
            # Replaying their HTTP 400 handlers in order reproduces the race
            # without sockets, credentials or a ChatClient constructor.
            client = lm.ChatClient.__new__(lm.ChatClient)
            client.key, client.base_url, client.json_mode = '', 'https://offline.invalid', True
            previous = lm.urllib.request.urlopen
            def fake_response(request, timeout):
                raise lm.urllib.error.HTTPError(request.full_url, 400, 'local fake format error', {}, None)
            lm.urllib.request.urlopen = fake_response
            body = {'response_format': {'type': 'json_object'}, 'temperature': 0}
            try:
                try:
                    client._post(body, .01)
                    raise AssertionError('fake 400 did not raise')
                except lm._Retryable:
                    pass
                require(not client.json_mode, 'first format error did not disable JSON mode')
                try:
                    client._post({} if plain else body, .01)
                    raise AssertionError('second fake 400 did not raise')
                except lm._Retryable:
                    require(not plain, 'plain-mode HTTP 400 must remain fatal')
                except lm._Fatal:
                    require(plain, 'late in-flight JSON-mode 400 became fatal after another worker disabled JSON mode')
            finally:
                lm.urllib.request.urlopen = previous
        suite.case('c35/inflight_json_mode_fallback', json_mode_inflight, category='c35_regression')
        suite.case('c35/plain_http_400_still_fatal', lambda: json_mode_inflight(True), category='c35')

    failed = [r for r in suite.results if not r["passed"]]
    report = {"package": str(pkg), "seed": args.seed, "random_cases": args.random,
              "deadline_policy": args.deadline_policy,
              "source_sha256": {name: hashlib.sha256((pkg / name).read_bytes()).hexdigest()
                                for name in ("guider_log.py", "llm_strategist.py", "policy.py") + (("when_text.py",) if when else ())},
              "total": len(suite.results), "passed": len(suite.results) - len(failed), "failed": len(failed),
              "failure_types": dict(Counter(r["error"]["type"] for r in failed)), "cases": suite.results}
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{pkg}: {report['passed']}/{report['total']} passed, {report['failed']} failed; {args.json}")
    for row in failed[:30]:
        print(f"  {row['name']}: {row['error']['type']}: {row['error']['message']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
