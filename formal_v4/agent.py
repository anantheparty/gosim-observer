#!/usr/bin/env python3
"""Streaming v4 participant, using only the supplied protocol information."""
from __future__ import annotations

import json
import os
import sys
import traceback

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

from policy import Policy


def main():
    policy = None
    for line in sys.stdin:
        if not line.strip():
            continue
        message = json.loads(line)
        kind = message.get("message_type")
        if kind == "initialize":
            policy = Policy(message["payload"])
        elif kind == "decision_request":
            try:
                action = policy.decide(message["payload"]) if policy else {"action": "wait", "duration_seconds": 900}
            except Exception:
                traceback.print_exc(file=sys.stderr)
                action = {"action": "wait", "duration_seconds": 900}
            response = {"protocol_version": "participant-agent-protocol-v4",
                        "message_type": "decision_response",
                        "decision_sequence": message["decision_sequence"], **action}
            print(json.dumps(response, separators=(",", ":"), allow_nan=False), flush=True)
        elif kind == "finish":
            if policy:
                print(json.dumps(policy.summary(), separators=(",", ":")), file=sys.stderr, flush=True)
            break
    if policy and policy.remote:
        policy.remote.close()


if __name__ == "__main__":
    main()
