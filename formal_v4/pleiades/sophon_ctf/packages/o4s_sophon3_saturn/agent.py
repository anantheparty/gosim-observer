#!/usr/bin/env python3
"""participant-agent-protocol-v4 entry: one JSON object per line on stdin/stdout, logs on stderr."""
import json
import os
import sys
import traceback

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')
sys.dont_write_bytecode = True
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(1, os.path.join(_HERE, '.deps'))

from sophon_policy import Policy  # noqa: E402
from sophon_probe import log  # noqa: E402

PROTO = 'participant-agent-protocol-v4'
SAFE_PARAMS = {'req_moon': 0, 'req_urg': 0.0, 'opt_value': 0.0, 'season_rho': 0.0, 'fault_counts': [],
               'fault_counts_stress': [], 'pool_max': 5000, 'llm': 0}


def main():
    policy = None
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        kind = msg.get('message_type')
        if kind == 'initialize':
            try:
                policy = Policy(msg['payload'])
            except Exception:
                traceback.print_exc(file=sys.stderr)
                try:  # retry with the optional features off
                    policy = Policy(msg['payload'], params=SAFE_PARAMS)
                except Exception:
                    traceback.print_exc(file=sys.stderr)
                    policy = None
        elif kind == 'decision_request':
            seq = msg.get('decision_sequence')
            action = None
            if policy is not None:
                try:
                    action = policy.decide(msg.get('payload') or {})
                except Exception:
                    traceback.print_exc(file=sys.stderr)
            if not isinstance(action, dict) or 'action' not in action:
                action = {'action': 'wait', 'duration_seconds': 900}
            out = {'protocol_version': PROTO, 'message_type': 'decision_response', 'decision_sequence': seq}
            out.update(action)
            try:
                text = json.dumps(out, separators=(',', ':'), allow_nan=False)
            except Exception:  # e.g. a NaN in the action: never break the protocol
                traceback.print_exc(file=sys.stderr)
                text = json.dumps({'protocol_version': PROTO, 'message_type': 'decision_response',
                                   'decision_sequence': seq, 'action': 'wait', 'duration_seconds': 900},
                                  separators=(',', ':'))
            sys.stdout.write(text + '\n')
            sys.stdout.flush()
        elif kind == 'finish':
            log('sophon_finish_message', payload=msg.get('payload'))
            if policy is not None:
                try:
                    print(json.dumps({'summary': policy.summary()}), file=sys.stderr, flush=True)
                except Exception:
                    pass
            break


if __name__ == '__main__':
    main()
