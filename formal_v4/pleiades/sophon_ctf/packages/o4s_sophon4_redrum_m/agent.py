#!/usr/bin/env python3
"""Standard-library JSONL participant; all diagnostics go to stderr."""
import json
import sys
import traceback
from skywrite import Policy, log


def main():
    policy = None
    for line in sys.stdin:
        try:
            msg = json.loads(line)
            kind = msg.get('message_type')
            if kind == 'initialize':
                policy = Policy(msg['payload'])
            elif kind == 'decision_request':
                try:
                    action = policy.decide(msg['payload'])
                except Exception:
                    traceback.print_exc(file=sys.stderr)
                    action = {'action': 'wait', 'duration_seconds': 900}
                out = {'protocol_version': 'participant-agent-protocol-v4',
                       'message_type': 'decision_response',
                       'decision_sequence': msg['decision_sequence'], **action}
                print(json.dumps(out, separators=(',', ':'), allow_nan=False), flush=True)
            elif kind == 'finish':
                log('skywrite_finish', complete=bool(policy and policy.completed),
                    completed_points=policy.index if policy else 0)
                break
        except Exception:
            traceback.print_exc(file=sys.stderr)


if __name__ == '__main__':
    main()
