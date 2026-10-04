"""Offline finite-season candidate entry. Normal original guard owns decide()."""
import os,sys,json
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1');sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent/'baseline_package'))
from sparse_exact import install
install()
import wrapper,agent,policy
def emit(record):print(json.dumps(record,separators=(',',':'),allow_nan=False),file=sys.stderr,flush=True)
try:
 from continuation_controller import make_policy
 candidate=make_policy(wrapper.wrapped,emit)
except (ImportError,OSError) as exc:
 emit({'season_pattern_disabled':type(exc).__name__,'reason':str(exc),'fallback':'original_exact_fault_actor'})
 candidate=wrapper.wrapped
policy.Policy=candidate;agent.Policy=candidate
if __name__=='__main__':agent.main()
