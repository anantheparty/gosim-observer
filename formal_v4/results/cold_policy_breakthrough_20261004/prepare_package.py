#!/usr/bin/env python3
"""Copy unchanged native READY plus the locked terminal wrapper; never execute."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil

NATIVE_MANIFEST_SHA256='88a307956ab7e6bcccab4fa59bad30c98f6d475855686ff40a3b0bc1cbaca5a2'
WRAPPER_SHA256='59b60a48ba3dfb7fd0cefe0e15734e20d151c0779112449ea35d2cec10f753f3'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(native_root,destination,wrapper):
    native_root,destination,wrapper=map(lambda p:Path(p).resolve(),(native_root,destination,wrapper))
    if destination.exists():raise ValueError('Package destination must not already exist')
    if destination==native_root or native_root in destination.parents or destination in native_root.parents:
        raise ValueError('Destination must be isolated from the READY source tree')
    manifest=native_root/'build_manifest.json'
    if sha(manifest)!=NATIVE_MANIFEST_SHA256:raise ValueError('Native READY manifest differs')
    native=json.loads(manifest.read_text())
    inventory={str(p.relative_to(native_root)):sha(p) for p in sorted(native_root.rglob('*'))
               if p.is_file() and '__pycache__' not in p.parts}
    if any(p.is_symlink() for p in native_root.rglob('*')):raise ValueError('READY symlink refused')
    expected={**native,'build_manifest.json':NATIVE_MANIFEST_SHA256}
    if len(expected)!=20 or inventory!=expected:raise ValueError('Exactly 20 unchanged READY files required')
    if sha(wrapper)!=WRAPPER_SHA256:raise ValueError('Terminal wrapper differs from the reviewed candidate')
    destination.mkdir(parents=True)
    for name in sorted(inventory):
        target=destination/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(native_root/name,target)
    shutil.copyfile(wrapper,destination/'wrapper.py')
    files={str(p.relative_to(destination)):sha(p) for p in sorted(destination.rglob('*')) if p.is_file()}
    if files!={**inventory,'wrapper.py':WRAPPER_SHA256}:raise ValueError('Package byte-copy mismatch')
    lock={'schema':'terminal-report-overlay-package-lock-v1','native_release_files':20,
          'native_manifest_sha256':NATIVE_MANIFEST_SHA256,'wrapper_sha256':WRAPPER_SHA256,
          'files':files,'runtime_entry':['python3','-u','/workspace/wrapper.py'],
          'runtime_base_root':'/workspace','default_enabled':False,'minimum_wallclock_seconds':10,
          'observer_project_bytes_preserved':True,'seasons_launched':0,'teacher_labels_read':0,
          'deployment_calibrated':False,'cloud_deployment_authorized':False}
    (destination/'terminal_report_package_lock.json').write_text(json.dumps(lock,indent=2)+'\n')
    return lock


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--native-root',type=Path,required=True)
    ap.add_argument('--destination',type=Path,required=True)
    ap.add_argument('--wrapper',type=Path,default=Path(__file__).resolve().parent/'terminal_report_agent.py')
    args=ap.parse_args()
    result=prepare(args.native_root,args.destination,args.wrapper)
    print(json.dumps({'destination':str(args.destination.resolve()),'package_lock_sha256':sha(args.destination/'terminal_report_package_lock.json'),
                      **{k:result[k] for k in ['schema','native_release_files','wrapper_sha256','runtime_entry','default_enabled','seasons_launched']}}))


if __name__=='__main__':main()
