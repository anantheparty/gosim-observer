from pathlib import Path
import json,zipfile,hashlib,shutil
HERE=Path(__file__).resolve().parent
original=HERE/'candidate_package.zip';expected='bd461164340f4adf490ace91003d49f7205a6ea631f712e9767f3527ec9549ba'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def tree(p):return {str(x.relative_to(p)):sha(x) for x in sorted(p.rglob('*')) if x.is_file() and '__pycache__' not in x.parts}
assert sha(original)==expected
out=HERE/'candidate_v2_package';out.mkdir(exist_ok=True)
with zipfile.ZipFile(original) as z:
 for name in z.namelist():
  p=out/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(name))
(out/'adaptive_fault_guard.py').write_bytes((HERE/'adaptive_fault_guard.py').read_bytes())
(out/'wrapper.py').write_bytes((HERE/'wrapper_v2.py').read_bytes())
manifest=tree(out);manifest.pop('build_manifest.json');(out/'build_manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
with zipfile.ZipFile(HERE/'candidate_v2_package.zip','w',zipfile.ZIP_DEFLATED) as z:
 for name in tree(out):
  i=zipfile.ZipInfo(name,(2026,10,4,0,0,0));i.compress_type=zipfile.ZIP_DEFLATED;i.external_attr=0o100644<<16;z.writestr(i,(out/name).read_bytes())
receipt={'v1_immutable_zip_sha256':sha(original),'v2_zip_sha256':sha(HERE/'candidate_v2_package.zip'),'members':tree(out),'v2_parameters':json.loads((HERE/'V2_PREDECLARATION.json').read_text())}
(HERE/'v2_package_receipt.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n');print(json.dumps({'passed':True,'sha256':receipt['v2_zip_sha256']}))
