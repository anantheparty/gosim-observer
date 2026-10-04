from pathlib import Path
import zipfile,hashlib,json
HERE=Path(__file__).resolve().parent
ZIP=Path('/Users/kamico/Downloads/observer_request_exact_cache.zip')
EXPECTED='e55becb74bbf2a707aeb893fb054a857610312c81d815181a28bfcf5e5ff092a'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def tree(p):return {str(x.relative_to(p)):sha(x) for x in sorted(p.rglob('*')) if x.is_file() and '__pycache__' not in x.parts}
assert sha(ZIP)==EXPECTED
with zipfile.ZipFile(ZIP) as z:
 assert len(z.namelist())==29
 for n in z.namelist():
  for v in ('control_package','candidate_package'):
   out=HERE/v/n; out.parent.mkdir(parents=True,exist_ok=True); out.write_bytes(z.read(n))
for n in ('persistent_fault_guard.py','wrapper.py'):(HERE/'candidate_package'/n).write_bytes((HERE/n).read_bytes())
p=HERE/'candidate_package/observer.project.json'; proj=json.loads(p.read_text()); proj['run']=['python3','-u','wrapper.py']; p.write_text(json.dumps(proj,indent=2)+'\n')
m=tree(HERE/'candidate_package');m.pop('build_manifest.json');(HERE/'candidate_package/build_manifest.json').write_text(json.dumps(m,sort_keys=True,indent=2)+'\n')
receipt={'baseline_zip_sha256':EXPECTED,'baseline_members':tree(HERE/'control_package'),'candidate_members':tree(HERE/'candidate_package'),'parameters':json.loads((HERE/'PREDECLARATION.json').read_text())}
assert all(sha(HERE/'candidate_package'/n)==v for n,v in receipt['baseline_members'].items() if n not in ('build_manifest.json','observer.project.json'))
for v in ('control_package','candidate_package'):
 with zipfile.ZipFile(HERE/(v+'.zip'),'w',zipfile.ZIP_DEFLATED) as z:
  for n in tree(HERE/v):
   info=zipfile.ZipInfo(n,(2026,10,4,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16;z.writestr(info,(HERE/v/n).read_bytes())
 receipt[v+'_zip_sha256']=sha(HERE/(v+'.zip'))
(HERE/'package_receipt.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
print(json.dumps({'passed':True,'zip':str(HERE/'candidate_package.zip'),'sha256':receipt['candidate_package_zip_sha256']}))
