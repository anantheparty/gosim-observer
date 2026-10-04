"""Freeze the reviewed ZIP and a separate RequestCache terminal wrapper."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ZIP = Path('/Users/kamico/Downloads/observer_request_exact_cache.zip')
ZIP_SHA = 'e55becb74bbf2a707aeb893fb054a857610312c81d815181a28bfcf5e5ff092a'
CONTROL = ROOT/'formal_v4/results/request_geometry_integration_20261004/control_package'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree(path):
    return {str(p.relative_to(path)): sha(p) for p in sorted(path.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts}


def main():
    assert sha(ZIP) == ZIP_SHA
    with zipfile.ZipFile(ZIP) as archive:
        names = archive.namelist()
        assert len(names) == 29 and len(set(names)) == 29
        expected = {n: hashlib.sha256(archive.read(n)).hexdigest() for n in names}
        assert tree(CONTROL) == expected
        for name in names:
            assert not Path(name).is_absolute() and '..' not in Path(name).parts
            for variant in ('control_package', 'full_wrapper_package'):
                destination = HERE/variant/name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(name))
    full = HERE/'full_wrapper_package'
    for name in ('terminal_report_agent.py', 'wrapper.py'):
        (full/name).write_bytes((HERE/name).read_bytes())
    project = json.loads((full/'observer.project.json').read_text())
    original_run = project['run']
    project['run'] = ['python3', '-u', 'wrapper.py']
    (full/'observer.project.json').write_text(json.dumps(project, indent=2)+'\n')
    manifest = tree(full)
    manifest.pop('build_manifest.json')
    (full/'build_manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True)+'\n')
    assert tree(HERE/'control_package') == expected
    actual = tree(full)
    changed = [name for name in names if actual[name] != expected[name]]
    assert changed == ['build_manifest.json', 'observer.project.json']
    before = json.loads((CONTROL/'observer.project.json').read_text())
    assert {k: v for k, v in project.items() if k != 'run'} == {k: v for k, v in before.items() if k != 'run'}
    assert json.loads((full/'build_manifest.json').read_text()) == {k: v for k, v in actual.items() if k != 'build_manifest.json'}
    receipt = {'schema': 'request-terminal-package-preservation-v1', 'baseline_zip': str(ZIP),
               'baseline_zip_sha256': ZIP_SHA, 'baseline_members': expected,
               'baseline_member_count': 29, 'all_29_control_members_byte_identical': True,
               'full_original_members_byte_identical': 27, 'permitted_changed_members': changed,
               'original_run': original_run, 'full_run': project['run'],
               'all_policy_parameters_byte_identical': True, 'transport_remains_disabled': True,
               'control': tree(HERE/'control_package'), 'full_wrapper': actual}
    (HERE/'package_preservation.json').write_text(json.dumps(receipt, indent=2, sort_keys=True)+'\n')
    for variant in ('control_package', 'full_wrapper_package'):
        with zipfile.ZipFile(HERE/(variant+'.zip'), 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in tree(HERE/variant):
                info = zipfile.ZipInfo(name, date_time=(2026, 10, 4, 0, 0, 0))
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, (HERE/variant/name).read_bytes())
    print(json.dumps({'passed': True, 'original_members': 29, 'full_unchanged': 27,
                      'changed_manifests': changed}))


if __name__ == '__main__':
    main()
