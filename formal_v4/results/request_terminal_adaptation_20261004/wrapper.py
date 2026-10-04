#!/usr/bin/env python3
"""Explicit RequestCache factory binding, followed by one terminal guard."""
from __future__ import annotations
import os
import sys
import math
import json

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('MKL_NUM_THREADS', '1')
sys.dont_write_bytecode = True

# This original module completes all four factories before any initialize.
from research import agent_request_exact_cache as exact_entry
from terminal_report_agent import make_policy_class, serve
import agent
import policy


def main():
    enabled = os.environ.get('REQUEST_TERMINAL_REPORT_ENABLE', '1') == '1'
    minimum = float(os.environ.get('REQUEST_TERMINAL_REPORT_MIN_WALLCLOCK', '10'))
    if not math.isfinite(minimum) or minimum < 10:
        raise ValueError('Terminal reserve must be at least 10 wallclock seconds')
    def emit(record):
        print(json.dumps(record, separators=(',', ':'), allow_nan=False), file=sys.stderr, flush=True)
    wrapped = make_policy_class(exact_entry.ExactCachedRequestPolicy, enabled, minimum, emit)
    policy.Policy = wrapped
    agent.Policy = wrapped
    serve(sys.stdin, sys.stdout, sys.stderr, wrapped)


if __name__ == '__main__':
    main()
