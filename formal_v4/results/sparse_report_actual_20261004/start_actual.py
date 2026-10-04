"""Launch three frozen normal seasons after checking package and runtime hashes."""
from pathlib import Path
import json,hashlib,subprocess,os
from datetime import datetime,timezone
P=Path(__file__).resolve().parent
KIT=Path('/tmp/geometry_native_20261003/upstream/gosim-observer-examples')
DEPS=Path('/tmp/geometry_native_20261003/.deps')
assert not (P/'job.json').exists()
expected=json.loads((P/'source_lock.json').read_text())['packages']['candidate_package']
actual={str(f.relative_to(P/'candidate_package')):hashlib.sha256(f.read_bytes()).hexdigest() for f in (P/'candidate_package').rglob('*') if f.is_file()}
assert actual==expected
runtime=json.loads((P/'runtime_source_receipt.json').read_text())
assert all(hashlib.sha256((KIT/k).read_bytes()).hexdigest()==v for k,v in runtime.items())
assert hashlib.sha256((P/'run_strong_candidates.py').read_bytes()).hexdigest()=='481612511c05a68d07cf5112bf281944cd0a644f71975605091aec08981d00d3'
contracts=json.loads((P/'COMBINATION_FINAL_RECEIPT.json').read_text())
assert contracts['all_contract_gates_passed']
argv=['/usr/bin/python3','-u',str(P/'run_strong_candidates.py'),'--experiment',str(P),'--kit',str(KIT),'--dependencies',str(DEPS),'--cases',str(P/'cases.json')]
env=os.environ.copy();env['PYTHONPATH']=str(DEPS);env['OPENBLAS_NUM_THREADS']='1';env['OMP_NUM_THREADS']='1';env['MKL_NUM_THREADS']='1'
started=datetime.now(timezone.utc).isoformat()
with (P/'launch.log').open('w') as log:process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
job={'schema':'root-sparse-report-three-normal-full-launch-v1','pid':process.pid,'started_utc':started,'argv':argv,'source_lock_sha256':hashlib.sha256((P/'source_lock.json').read_bytes()).hexdigest(),'cases_sha256':hashlib.sha256((P/'cases.json').read_bytes()).hexdigest(),'harness_sha256':hashlib.sha256((P/'run_strong_candidates.py').read_bytes()).hexdigest(),'runtime_source_receipt_sha256':hashlib.sha256((P/'runtime_source_receipt.json').read_bytes()).hexdigest(),'combination_receipt_sha256':hashlib.sha256((P/'COMBINATION_FINAL_RECEIPT.json').read_bytes()).hexdigest(),'candidate_zip_sha256':'fa7a8e7c8de173331a64e160e4df6f34710c9e59a37b199271c2444e5d46126b','normal_complete_season':True,'forced_prefix':False,'maximum_decisions_stop':None,'actor_truth_mount':False,'limits':{'cpu':2,'memory_gib':2,'wallclock_seconds':900},'no_control_rerun':True,'control':'existing faultv1 complete L1/L2/L3','L4_holdout_not_run':True}
(P/'job.json').write_text(json.dumps(job,indent=2)+'\n');print(json.dumps(job))
