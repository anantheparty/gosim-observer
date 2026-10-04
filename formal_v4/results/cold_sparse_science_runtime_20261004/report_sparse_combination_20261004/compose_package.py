"""Byte-preserving report NN/DP plus frozen exact arithmetic composition."""
from pathlib import Path
import hashlib,json,zipfile,shutil
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[3]
report=ROOT/'formal_v4/results/cold_report_sparse_domain_20261004/candidate_package.zip'
sparse=OUT.parent/'fault_package'
assert hashlib.sha256(report.read_bytes()).hexdigest()=='069c346450412437a96b02d48abe886d4201b7a87dc583c87715b995c42a9823'
folder=OUT/'candidate_package';folder.mkdir(exist_ok=False)
z=zipfile.ZipFile(report);z.extractall(folder)
extras=['sparse_exact.py','sparse_native.py','sparse_evaluator.py','sparse_kernel.cpp','sparse_kernel_darwin_arm64.dylib','sparse_kernel_linux_x86_64.so']
for n in extras:shutil.copyfile(sparse/n,folder/n)
(folder/'report_sparse_entry.py').write_text('''"""Normal frozen report policy with exact arithmetic installed first."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
from sparse_exact import install
install()
import report_entry
if __name__ == '__main__': report_entry.agent.main()
''')
project=json.loads((folder/'observer.project.json').read_text());project['run']=['python3','-u','report_sparse_entry.py'];(folder/'observer.project.json').write_text(json.dumps(project,indent=2)+'\n')
hashes={str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob('*')) if p.is_file() and p.name!='build_manifest.json'}
(folder/'build_manifest.json').write_text(json.dumps(hashes,indent=2)+'\n')
full={**hashes,'build_manifest.json':hashlib.sha256((folder/'build_manifest.json').read_bytes()).hexdigest()}
changed=[n for n in z.namelist() if (folder/n).read_bytes()!=z.read(n)]
assert set(changed)=={'build_manifest.json','observer.project.json'}
assert (folder/'report_support.py').read_bytes()==(sparse/'persistent_fault_guard.py').read_bytes()
assert all((folder/n).read_bytes()==(sparse/n).read_bytes() for n in extras)
lock={'packages':{'candidate_package':full}}
(OUT/'source_lock.json').write_text(json.dumps(lock,indent=2)+'\n')
zipout=OUT/'observer_report_sparse_exact_20261004.zip'
with zipfile.ZipFile(zipout,'w',zipfile.ZIP_DEFLATED) as target:
 for p in sorted(folder.rglob('*')):
  if p.is_file():target.write(p,p.relative_to(folder))
receipt={'status':'source_frozen_pending_contract_checks','report_source_zip_sha256':hashlib.sha256(report.read_bytes()).hexdigest(),'sparse_source_fault_zip_sha256':'5b00e6a33cbacc167cdf9255531c5209b0ab36cab7c52ce13d395942e672cf29','candidate_zip_sha256':hashlib.sha256(zipout.read_bytes()).hexdigest(),'candidate_members':len(full),'original_report_members':len(z.namelist()),'report_members_byte_identical':len(z.namelist())-len(changed),'only_original_members_changed':changed,'report_support_equals_original_faultv1':True,'report_model_sha256':full['report_model.npz'],'report_dp_sha256':full['report_dp.npz'],'native_extras_byte_identical':True,'call_order':['report_sparse_entry imports sparse_exact','sparse_exact.install replaces SpatialPlanner._evaluate and CPUPhase coarse_numpy_local','import original report_entry','original ExactCache factories are installed','original report_policy wraps ExactCachedRequestPolicy','agent.main receives initialize and decision messages'],'no_fault_wrapper_imported':True,'source_lock_sha256':hashlib.sha256((OUT/'source_lock.json').read_bytes()).hexdigest(),'frozen_package_never_modified_after_creation':True}
(OUT/'SOURCE_FROZEN_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))
