"""Independent packer using exact previously uploaded algorithms and configs."""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
from datetime import datetime
import sys
import zipfile

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from research.agent_verified_portfolio import public_digest

PHASE_SHA='a6fca473886bc1ea5d763f6a358eb5006163b072b807abc8946d141ccfcfee42'
REQUEST_SHA='bfcc8ed738229e961c2135415d44dbef27e78b5386c3bdfdabaee915904e91ec'
sha=lambda b:hashlib.sha256(b).hexdigest()


def public_card(card_id):
    """Reconstruct official initialize from six public files, without an engine."""
    card=ROOT/f'practice_cards/{card_id}/{card_id}'
    names=['config/v4_scenario.json','config/v4_fiber_config.json','config/v4_score_config.json','public/targets.csv','public/v4_night_calendar.csv','public/footprint.csv']
    data={name:(card/name).read_bytes() for name in names}
    scenario=json.loads(data[names[0]]);fiber=json.loads(data[names[1]]);score=json.loads(data[names[2]])
    targets=list(csv.DictReader(data[names[3]].decode().splitlines()))
    nights=list(csv.DictReader(data[names[4]].decode().splitlines()))
    footprint={}
    for row in sorted(csv.DictReader(data[names[5]].decode().splitlines()),key=lambda x:(x['component_id'],int(x['vertex_index']))):
        footprint.setdefault(row['component_id'],[]).append([float(row['ra_deg']),float(row['dec_deg'])])
    night_fields=('night_id','night_date','observing_start_utc','observing_end_utc')
    nights=[{**{k:row[k] for k in night_fields},'slot_count':int(row['slot_count'])} for row in nights]
    field=fiber['field'];side=math.isqrt(int(field['n_fibers']));glass=math.sqrt(float(field['fiber_area_deg2']));pitch=glass+float(field['gap_deg'])
    parse=lambda value:datetime.fromisoformat(value.replace('Z','+00:00'))
    seconds=(parse(nights[0]['observing_end_utc'])-parse(nights[0]['observing_start_utc'])).total_seconds()
    initial={'schema_version':'v4-initialize-v1','task_card':scenario['task_card'],'site':{**scenario['site'],'minimum_altitude_deg':scenario['minimum_altitude_deg']},
             'survey':{'start_utc':nights[0]['observing_start_utc'],'end_utc':nights[-1]['observing_end_utc'],'slot_seconds':int(round(seconds/nights[0]['slot_count'])),'nights':nights},
             'instrument':{**field,'grid_side':side,'glass_side_deg':round(glass,6),'pitch_deg':round(pitch,6),'fov_side_deg':round(side*pitch,6),
                           'layout':'row-major, fiber 0 bottom-left; rows along +alt, columns along +az at exposure start; gnomonic plane centred on the actual pointing',
                           'exposure':fiber['exposure']},'scoring':score,
             'footprint':[{'component_id':k,'vertices':v} for k,v in sorted(footprint.items())],
             'limits':{'global_wallclock_seconds':900,'max_consecutive_reports':score['reporting'].get('max_consecutive_reports',32),
                       'response_max_bytes':512*1024,'decision_timeout':'global only (no per-decision timeout)'},
             'targets':{'columns':list(targets[0]),'rows':[[row[k] if k in ('target_id','target_class') else
                       row[k].lower()=='true' if k=='required' else float(row[k]) for k in targets[0]] for row in targets]}}
    return initial,{name:sha(raw) for name,raw in data.items()}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--phase-zip',default='/Users/kamico/Downloads/observer_phase_gpu.zip')
    parser.add_argument('--request-zip',default='/Users/kamico/Downloads/observer_request_phase_gpu.zip')
    parser.add_argument('--out',required=True)
    args=parser.parse_args()
    packages={}
    for branch,path,expected in [('phase',args.phase_zip,PHASE_SHA),('request',args.request_zip,REQUEST_SHA)]:
        raw=Path(path).read_bytes()
        if sha(raw)!=expected:raise ValueError('frozen source ZIP changed')
        with zipfile.ZipFile(path) as z:packages[branch]={n:z.read(n) for n in z.namelist()}
    excluded={'observer.project.json','policy_config.json','remote_runtime.json','build_manifest.json'}
    shared=(set(packages['phase'])&set(packages['request']))-excluded
    assert all(packages['phase'][n]==packages['request'][n] for n in shared)
    initial,public_hashes=public_card('delta')
    public_manifest={'schema_version':'verified-offline-policy-portfolio-v1',
                     'delta':{'card_id':'delta','scenario_slug':'v4-practice-delta','public_semantic_sha256':public_digest(initial),
                              'public_file_sha256':public_hashes},
                     'identity_scope':'schema, site, public calendar with slot_count, rounded6 instrument geometry, footprint, scoring and complete public target catalog; no hidden products or prior-output forecast',
                     'default_branch':'phase','runtime':{'enabled':False,'enable_search':False},
                     'source_packages':{'phase':PHASE_SHA,'request':REQUEST_SHA},
                     'policy_config_sha256':{b:sha(p['policy_config.json']) for b,p in packages.items()}}
    contents={'research/agent_verified_portfolio.py':(ROOT/'research/agent_verified_portfolio.py').read_bytes(),
              'portfolio_public_manifest.json':(json.dumps(public_manifest,sort_keys=True,indent=2)+'\n').encode(),
              'requirements.txt':packages['phase']['requirements.txt']}
    project=json.loads(packages['phase']['observer.project.json'])
    project['run']=['python3','-u','-m','research.agent_verified_portfolio']
    contents['observer.project.json']=(json.dumps(project,indent=2)+'\n').encode()
    disabled=(json.dumps(public_manifest['runtime'],sort_keys=True)+'\n').encode()
    for branch,package in packages.items():
        for name,data in package.items():
            if name not in ('observer.project.json','build_manifest.json','remote_runtime.json'):
                contents[f'branches/{branch}/{name}']=data
        contents[f'branches/{branch}/remote_runtime.json']=disabled
        contents[f'branches/{branch}/research/agent_verified_offline.py']=(ROOT/'research/agent_verified_offline.py').read_bytes()
    manifest={name:sha(raw) for name,raw in contents.items()}
    contents['build_manifest.json']=(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode()
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for name,raw in sorted(contents.items()):
            info=zipfile.ZipInfo(name,date_time=(2026,10,3,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644<<16
            z.writestr(info,raw)
    historical=(Decimal('7289.494481')+Decimal('6602.149692')+Decimal('7033.080199')+Decimal('6423.086757'))/4
    print(json.dumps({'path':str(out),'sha256':sha(out.read_bytes()),'bytes':out.stat().st_size,'files':len(contents),
                      'historical_selected_mean_exact':str(historical),'new_package_score_measured':False,
                      'frozen_shared_source_files_equal':sorted(shared),'delta_public_digest':public_manifest['delta']['public_semantic_sha256']}))


if __name__=='__main__':main()
