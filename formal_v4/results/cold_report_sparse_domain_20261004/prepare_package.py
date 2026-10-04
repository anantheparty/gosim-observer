from pathlib import Path
import zipfile,json,hashlib,shutil
ROOT=Path(__file__).resolve().parent;ZIP=Path('/Users/kamico/Downloads/observer_request_exact_cache.zip')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def tree(p):return {str(f.relative_to(p)):sha(f) for f in sorted(p.rglob('*')) if f.is_file() and '__pycache__' not in f.parts}
assert sha(ZIP)=='e55becb74bbf2a707aeb893fb054a857610312c81d815181a28bfcf5e5ff092a'
out=ROOT/'candidate_package';out.mkdir(exist_ok=True)
with zipfile.ZipFile(ZIP) as z:
    originals={n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist()}
    for n in z.namelist():
        p=out/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(n))
for n in ['report_core.py','report_policy.py','report_support.py','sensor_core.py','report_entry.py','report_model.npz','report_dp.npz']:
    shutil.copyfile(ROOT/n,out/n)
p=out/'observer.project.json';project=json.loads(p.read_text());project['run']=['python3','-u','report_entry.py'];p.write_text(json.dumps(project,indent=2)+'\n')
members=tree(out);members.pop('build_manifest.json');(out/'build_manifest.json').write_text(json.dumps(members,sort_keys=True,indent=2)+'\n')
assert all(sha(out/n)==v for n,v in originals.items() if n not in ['observer.project.json','build_manifest.json'])
with zipfile.ZipFile(ROOT/'candidate_package.zip','w',zipfile.ZIP_DEFLATED) as z:
    for n in tree(out):
        info=zipfile.ZipInfo(n,(2026,10,4,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16;z.writestr(info,(out/n).read_bytes())
receipt=dict(baseline_zip_sha256=sha(ZIP),original_members=29,original_byte_identical=27,candidate_members=len(tree(out)),
    candidate_zip_sha256=sha(ROOT/'candidate_package.zip'),members=tree(out),actor_has_generator=False,
    selection=json.loads((ROOT/'selection_lock.json').read_text()))
(ROOT/'package_receipt.json').write_text(json.dumps(receipt,indent=2));print(json.dumps({k:v for k,v in receipt.items() if k!='members'}))
control=ROOT/'posterior_p90_control_package';shutil.copytree(out,control,dirs_exist_ok=True)
p=control/'observer.project.json';project=json.loads(p.read_text());project['run'].append('--posterior-p90-control');p.write_text(json.dumps(project,indent=2)+'\n')
members=tree(control);members.pop('build_manifest.json');(control/'build_manifest.json').write_text(json.dumps(members,sort_keys=True,indent=2)+'\n')
with zipfile.ZipFile(ROOT/'posterior_p90_control_package.zip','w',zipfile.ZIP_DEFLATED) as z:
    for n in tree(control):
        info=zipfile.ZipInfo(n,(2026,10,4,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16;z.writestr(info,(control/n).read_bytes())
receipt['posterior_p90_control_zip_sha256']=sha(ROOT/'posterior_p90_control_package.zip')
(ROOT/'package_receipt.json').write_text(json.dumps(receipt,indent=2))
