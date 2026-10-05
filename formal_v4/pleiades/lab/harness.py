#!/usr/bin/env python3
"""In-process runner: official V4Workflow engine + a policy object, no subprocess/JSON pipe.

usage: harness.py --card L1|path --agent-dir DIR --factory module:callable [--wallclock S] --out DIR
The factory is called with the initialize payload and must return an object with .decide(payload)->action dict.
"""
import argparse, importlib, json, os, sys, time
from pathlib import Path

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')

EX = Path(os.environ.get('OBS_EX', '/home/shu/kamico/observer/gosim-observer/formal_v4/upstream/gosim-observer-examples'))
sys.path.insert(0, str(EX / 'runner'))
from challenge.v4_workflow import V4Workflow  # noqa: E402

PROTO = 'participant-agent-protocol-v4'


def card_dir(card):
    p = Path(card)
    if p.is_dir():
        return p
    for base in (EX / 'local-cards', Path(os.environ.get('OBS_WORLDS', '/home/shu/kamico/observer/work/worlds'))):
        if (base / card).is_dir():
            return base / card
    raise SystemExit(f'card not found {card}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--card', required=True)
    ap.add_argument('--agent-dir', required=True)
    ap.add_argument('--factory', required=True, help='module:callable')
    ap.add_argument('--wallclock', type=float, default=900)
    ap.add_argument('--out', required=True)
    ap.add_argument('--env', action='append', default=[], help='KEY=VALUE env for the policy')
    ap.add_argument('--clock-factor', type=float, default=1.3,
                    help='budget clock = policy CPU seconds x factor (platform charges agent CPU only); 0 = wall clock')
    a = ap.parse_args()
    for kv in a.env:
        k, v = kv.split('=', 1)
        os.environ[k] = v
    a.out = str(Path(a.out).resolve())
    sys.path.insert(0, a.agent_dir)
    os.chdir(a.agent_dir)
    mod_name, fn_name = a.factory.split(':')
    mod = importlib.import_module(mod_name)
    factory = getattr(mod, fn_name)
    cpu = {'t': 0.0, 'n': 0}
    if a.clock_factor > 0:
        wf = V4Workflow(card_dir(a.card), clock=lambda: cpu['t'] * a.clock_factor)
    else:
        wf = V4Workflow(card_dir(a.card))
    holder = {}

    def initialize(payload):
        t = time.process_time()
        try:
            holder['p'] = factory(payload)
        except BaseException:
            import traceback
            traceback.print_exc()
            sys.stderr.flush()
            raise
        cpu['init'] = time.process_time() - t

    wall_cap = float(os.environ.get('HARNESS_WALL_CAP', '0') or 0)

    def decide(message, limit):
        if wall_cap > 0:
            # emulate the platform's hard real-time cap from the first request (and what the agent sees of it)
            now_w = time.perf_counter()
            cpu.setdefault('w0', now_w)
            left = wall_cap - (now_w - cpu['w0'])
            if left <= 0:
                cpu['wall_expired'] = True
                raise TimeoutError()
            wc = message['payload'].setdefault('wallclock', {})
            wc['wall_remaining_seconds'] = round(left, 3)
            wc['speed_factor'] = round(1.0 / a.clock_factor, 4) if a.clock_factor > 0 else 1.0
        if a.clock_factor > 0:
            # the platform's speed factor: charged = this machine's CPU seconds / factor (here x clock factor)
            message['payload'].setdefault('wallclock', {})['speed_factor'] = round(1.0 / a.clock_factor, 4)
        t = time.process_time()
        w = time.perf_counter()
        try:
            action = holder['p'].decide(message['payload'])
        finally:
            # like the platform's fair clock: CPU of all threads in the turn, at most the turn's real time
            cpu['t'] += min(time.process_time() - t, time.perf_counter() - w)
            cpu['n'] += 1
        return {'protocol_version': PROTO, 'message_type': 'decision_response',
                'decision_sequence': message['decision_sequence'], **action}

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    result = wf.run(decide, out, wallclock_seconds=a.wallclock, initialize=initialize)
    rep = result['score_report']
    summary = {'card': a.card, 'total': rep['total'], **rep['components'],
               'required_missing': rep['counts']['required_missing'],
               'observe_actions': rep['counts']['observe_actions'],
               'targets_observed': rep['counts']['targets_observed'],
               'termination': result['termination_reason'],
               'wall': round(time.time() - t0, 1), 'policy_cpu': round(cpu['t'], 1),
               'init_cpu': round(cpu.get('init', 0), 2), 'decisions': cpu['n'],
               'accounted': result['accounted_wallclock_seconds'], 'wall_expired': cpu.get('wall_expired', False)}
    p = holder.get('p')
    if p is not None and hasattr(p, 'summary'):
        try:
            summary['policy'] = p.summary()
        except Exception:
            pass
    (out / 'summary.json').write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
