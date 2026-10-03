"""Select a previously validated policy using initialize-visible public identity."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def public_projection(initial):
    columns={name:i for i,name in enumerate(initial['targets']['columns'])}
    ordered=('target_id','ra_deg','dec_deg','target_class','feature_flux','science_weight','required')
    numeric={'ra_deg','dec_deg','feature_flux','science_weight'}
    rows=[]
    for row in initial['targets']['rows']:
        values=[]
        for name in ordered:
            value=row[columns[name]]
            if name in numeric:value=float(value)
            elif name=='required':
                text=str(value).strip().lower()
                if text not in ('true','false','1','0'):raise ValueError('invalid public required flag')
                value=text in ('true','1')
            else:value=str(value)
            values.append(value)
        rows.append(values)
    site=initial['site'];survey=initial['survey'];instrument=initial['instrument']
    return {'schema_version':initial['schema_version'],
            'site':{k:float(site[k]) for k in ('latitude_deg','longitude_deg','utc_offset_hours','minimum_altitude_deg','sun_altitude_limit_deg')},
            'survey':{'start_utc':survey['start_utc'],'end_utc':survey['end_utc'],'slot_seconds':int(survey['slot_seconds']),
                      'nights':[{**{k:n[k] for k in ('night_id','night_date','observing_start_utc','observing_end_utc')},
                                 'slot_count':int(n['slot_count'])} for n in survey['nights']]},
            'instrument':{'n_fibers':int(instrument['n_fibers']),'fiber_area_deg2':float(instrument['fiber_area_deg2']),
                          'gap_deg':float(instrument['gap_deg']),'grid_side':int(instrument['grid_side']),
                          'layout':str(instrument['layout']),
                          **{k:float(instrument[k]) for k in ('glass_side_deg','pitch_deg','fov_side_deg')},
                          'exposure':{k:int(instrument['exposure'][k]) for k in ('min_duration_seconds','max_duration_seconds')}},
            'footprint':[{'component_id':str(item['component_id']),
                          'vertices':[[float(x),float(y)] for x,y in item['vertices']]}
                         for item in sorted(initial['footprint'],key=lambda x:x['component_id'])],
            'scoring':initial['scoring'],'targets':{'columns':list(ordered),'rows':rows}}


def public_digest(initial):
    encoded=json.dumps(public_projection(initial),sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def select_branch(initial,manifest):
    card=initial.get('task_card') or {}
    if card.get('card_id')!='delta' or card.get('scenario_slug')!='v4-practice-delta':return 'phase'
    try:matches=public_digest(initial)==manifest['delta']['public_semantic_sha256']
    except (KeyError,TypeError,ValueError,OverflowError):matches=False
    return 'request' if matches else 'phase'


def main():
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'portfolio_public_manifest.json').read_text())
    first=b''
    while not first.strip():
        first=sys.stdin.buffer.readline()
        if not first:return
    message=json.loads(first)
    if message.get('message_type')!='initialize':raise ValueError('initialize must be first')
    branch=select_branch(message['payload'],manifest)
    print(json.dumps({'portfolio_selection':branch,'identity_scope':'initialize public semantic identity',
                      'remote_enabled':False},separators=(',',':')),file=sys.stderr,flush=True)
    environment=dict(os.environ)
    environment['PYTHONPATH']=os.pathsep.join([str(root/'.deps'),str(root/'branches'/branch)])
    child=subprocess.Popen([sys.executable,'-u','-m','research.agent_verified_offline',branch],
                           cwd=root/'branches'/branch,env=environment,stdin=subprocess.PIPE)
    try:
        child.stdin.write(first);child.stdin.flush()
        for line in sys.stdin.buffer:
            child.stdin.write(line);child.stdin.flush()
            if line.strip() and json.loads(line).get('message_type')=='finish':break
        child.stdin.close()
        status=child.wait()
    finally:
        if child.poll() is None:child.terminate();child.wait()
    if status:raise SystemExit(status)


if __name__=='__main__':main()
