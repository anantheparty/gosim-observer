"""Freeze an isolated two-mode CPU terrain/request comparison."""
import hashlib
import json
import shutil
import sys
from pathlib import Path

project=Path(__file__).resolve().parents[1]
runtime=Path('/tmp/gosim-v4-request-future-pair-20261003')
if runtime.exists():raise SystemExit('runtime already exists; preserve frozen evidence')
runtime.mkdir()
example=project/'upstream/gosim-observer-examples'
shutil.copytree(example/'runner',runtime/'runner')
shutil.copytree(example/'local-cards',runtime/'local-cards')
source=project/'results/terrain_cpu_phase_L1_20261003/agent'
overlay=['request_deadline_common.py','request_future_field.py','agent_request_future_cpu_direct.py']
base=json.loads((source/'policy_config.json').read_text())
base.update(request_dp_future_field_mode='published',request_dp_step_seconds=900,
            request_dp_price_anchors=2,request_dp_quality_tolerance=.15)
for mode in ('bypass','deadline'):
    destination=runtime/'agents'/mode
    shutil.copytree(source,destination,ignore=shutil.ignore_patterns('__pycache__','*.pyc','remote_runtime.json'))
    for name in overlay:shutil.copy2(project/'research'/name,destination/'research'/name)
    shutil.copy2(project/'research/agent_request_future_cpu_direct.py',destination/'agent_request_future_cpu.py')
    config={**base,'request_dp_mode':mode}
    (destination/'policy_config.json').write_text(json.dumps(config,indent=2)+'\n')
    if (destination/'remote_runtime.json').exists():raise ValueError('credential/runtime configuration in freeze')
shutil.copy2(project/'research/run_cpu_phase_pair.py',runtime/'run_pair.py')
manifest={str(p.relative_to(runtime)):hashlib.sha256(p.read_bytes()).hexdigest()
          for p in runtime.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
(runtime/'source_manifest.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps({'runtime':str(runtime),'files':len(manifest),'overlay':overlay}))
