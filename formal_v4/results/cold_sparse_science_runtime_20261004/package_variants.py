from pathlib import Path
import hashlib,json,zipfile,shutil,difflib
OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]
variants={'strong':(Path('/Users/kamico/Downloads/observer_request_exact_cache.zip'),'from research import agent_request_exact_cache as entry\nif __name__ == \'__main__\': entry.agent.main()\n'),
 'fault':(ROOT/'formal_v4/results/cold_persistent_fault_control_20261004/candidate_package.zip','import wrapper\nif __name__ == \'__main__\': wrapper.agent.main()\n'),
 'debias':(ROOT/'formal_v4/results/cold_strategy_rebuild_20261004/observer_science_seed_debias_20261004.zip','import debias_entry\nif __name__ == \'__main__\': debias_entry.agent.main()\n')}
extras=['sparse_kernel.cpp','sparse_kernel_darwin_arm64.dylib','sparse_kernel_linux_x86_64.so','sparse_native.py','sparse_exact.py','sparse_evaluator.py']
receipt={'variants':{}}
for name,(archive,tail) in variants.items():
 folder=OUT/(name+'_package');folder.mkdir(exist_ok=True)
 z=zipfile.ZipFile(archive);z.extractall(folder)
 for file in extras:shutil.copyfile(OUT/'package'/file,folder/file)
 entry='''"""Normal original policy entry with exact compiled arithmetic installed first."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
from sparse_exact import install
install()
'''+tail
 (folder/'sparse_entry.py').write_text(entry)
 project=json.loads((folder/'observer.project.json').read_text());project['run']=['python3','-u','sparse_entry.py'];(folder/'observer.project.json').write_text(json.dumps(project,indent=2)+'\n')
 for p in folder.rglob('__pycache__'):shutil.rmtree(p)
 hashes={str(p.relative_to(folder)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob('*')) if p.is_file() and p.name!='build_manifest.json'}
 (folder/'build_manifest.json').write_text(json.dumps(hashes,indent=2)+'\n')
 preserved=[n for n in z.namelist() if n not in ['observer.project.json','build_manifest.json'] and (folder/n).read_bytes()==z.read(n)]
 changed=[n for n in z.namelist() if n not in preserved]
 assert changed==['build_manifest.json','observer.project.json'] or set(changed)=={'build_manifest.json','observer.project.json'}
 outzip=OUT/('observer_sparse_exact_'+name+'_20261004.zip')
 with zipfile.ZipFile(outzip,'w',zipfile.ZIP_DEFLATED) as za:
  for p in sorted(folder.rglob('*')):
   if p.is_file():za.write(p,p.relative_to(folder))
 receipt['variants'][name]={'zip':str(outzip),'sha256':hashlib.sha256(outzip.read_bytes()).hexdigest(),'members':len(hashes)+1,'original_members_preserved':len(preserved),'original_members_changed':changed,'extras':extras+['sparse_entry.py'],'file_sha256':{**hashes,'build_manifest.json':hashlib.sha256((folder/'build_manifest.json').read_bytes()).hexdigest()}}
(OUT/'package_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
lock={'packages':{name+'_package':r['file_sha256'] for name,r in receipt['variants'].items()}}
(OUT/'source_lock.json').write_text(json.dumps(lock,indent=2)+'\n')
print(json.dumps({k:{x:y for x,y in v.items() if x!='file_sha256'} for k,v in receipt['variants'].items()},indent=2))
