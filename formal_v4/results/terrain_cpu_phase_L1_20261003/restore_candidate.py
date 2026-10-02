"""Restore this gate's immutable agent from its recorded local Git commit."""
import hashlib,json,subprocess
from pathlib import Path

root=Path(__file__).resolve().parent
manifest=json.loads((root/'source_manifest.json').read_text())
for relative,digest in manifest['files'].items():
    data=subprocess.check_output(['git','show',manifest['source_git_commit']+':'+manifest['snapshot_source_path_map'][relative]])
    if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('archived source hash mismatch: '+relative)
    file=root/'agent'/relative;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(data)
print('Restored '+str(len(manifest['files']))+' verified source files to '+str(root/'agent'))
