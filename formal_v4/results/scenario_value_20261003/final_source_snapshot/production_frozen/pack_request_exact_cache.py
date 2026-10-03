"""Build an independent candidate from the exact frozen 75fa request source."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
SOURCE_SHA = 'bfcc8ed738229e961c2135415d44dbef27e78b5386c3bdfdabaee915904e91ec'
SOURCE_FINGERPRINT = '75fa4058539fbe28fafd0e56d4fab0cc8af0108d7cbb6ec87ee1f268a126c0d5'
sha = lambda b: hashlib.sha256(b).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default='/Users/kamico/Downloads/observer_request_phase_gpu.zip')
    parser.add_argument('--out', default='/Users/kamico/Downloads/observer_request_exact_cache.zip')
    args = parser.parse_args()
    source = Path(args.source)
    if sha(source.read_bytes()) != SOURCE_SHA:
        raise ValueError('frozen request source ZIP changed')
    with zipfile.ZipFile(source) as z:
        contents = {n: z.read(n) for n in z.namelist()}
    old_manifest = json.loads(contents['build_manifest.json'])
    assert all(sha(contents[n]) == digest for n, digest in old_manifest.items())
    added = ['research/agent_request_exact_cache.py', 'research/request_exact_cache.py']
    for name in added:
        if name in contents: raise ValueError('new module collides with frozen source')
        contents[name] = (ROOT/name).read_bytes()
    project = json.loads(contents['observer.project.json'])
    project['run'] = ['python3', '-u', '-m', 'research.agent_request_exact_cache']
    contents['observer.project.json'] = (json.dumps(project, indent=2)+'\n').encode()
    contents['remote_runtime.json'] = b'{"enabled": false, "enable_search": false}\n'
    metadata = {'schema': 'frozen-request-exact-cache-candidate-v1',
                'source_zip_sha256': SOURCE_SHA, 'source_fingerprint': SOURCE_FINGERPRINT,
                'policy_config_sha256': sha(contents['policy_config.json']),
                'stable_policy_sha256': sha(contents['policy.py']), 'all_cards_route': 'request',
                'changed_existing_files': ['observer.project.json', 'remote_runtime.json', 'build_manifest.json'],
                'added_algorithm_modules': added, 'algorithm_parameters_changed': False,
                'candidate_score_measured': False, 'transport_enabled': False}
    contents['exact_cache_provenance.json'] = (json.dumps(metadata, sort_keys=True, indent=2)+'\n').encode()
    manifest = {n: sha(raw) for n, raw in contents.items() if n != 'build_manifest.json'}
    contents['build_manifest.json'] = (json.dumps(manifest, sort_keys=True, indent=2)+'\n').encode()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, raw in sorted(contents.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 3, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, raw)
    print(json.dumps({'path': str(out), 'sha256': sha(out.read_bytes()),
                      'bytes': out.stat().st_size, 'files': len(contents),
                      'source_zip_sha256': SOURCE_SHA, 'new_online_score': None}))


if __name__ == '__main__': main()
