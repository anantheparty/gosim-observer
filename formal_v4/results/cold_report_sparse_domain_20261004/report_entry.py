#!/usr/bin/env python3
import os,sys,json
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
sys.dont_write_bytecode=True
from research import agent_request_exact_cache as exact_entry
from report_policy import make_policy_class
import agent,policy
def emit(record):print(json.dumps(record,separators=(',',':'),allow_nan=False),file=sys.stderr,flush=True)
wrapped=make_policy_class(exact_entry.ExactCachedRequestPolicy,enabled=os.environ.get('REQUEST_REPORT_VALUE_ENABLE','1')=='1',emit=emit,
    mode='posterior_p90_control' if '--posterior-p90-control' in sys.argv else 'dp_free')
policy.Policy=wrapped;agent.Policy=wrapped
if __name__=='__main__':agent.main()
