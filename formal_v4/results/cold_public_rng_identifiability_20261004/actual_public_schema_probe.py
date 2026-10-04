"""Finite schema check of six authorized public files; no seed search or truth read."""
import csv
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
WORKSPACE=ROOT.parents[2]
FILES=('config/v4_scenario.json','config/v4_fiber_config.json','config/v4_score_config.json',
       'public/targets.csv','public/footprint.csv','public/v4_night_calendar.csv')
PRIVATE_COLUMNS={'factor','quality','prog_mult','valid','is_observable','seeing_arcsec','transparency','sky_quality','instrument_efficiency'}
def seed_paths(value,path=''):
    if isinstance(value,dict):
        for key,child in value.items():
            sub=path+'/'+str(key)
            if 'seed' in str(key).lower():
                yield sub
            else:
                yield from seed_paths(child,sub)
    elif isinstance(value,list):
        for i,child in enumerate(value):
            yield from seed_paths(child,path+'/'+str(i))
result=[]
for card in ('alpha','beta','gamma','delta'):
    root=WORKSPACE/'formal_v4/practice_cards'/card/card
    records=[]
    for rel in FILES:
        path=root/rel
        data=path.read_bytes()
        record={'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
        if path.suffix=='.json':
            cfg=json.loads(data)
            record['seed_key_paths']=list(seed_paths(cfg))
            record['top_level_keys']=sorted(cfg)
        else:
            with path.open(newline='') as h:
                reader=csv.DictReader(h)
                header=reader.fieldnames
                if PRIVATE_COLUMNS & set(header):
                    raise RuntimeError('Nonpublic schema; abort before consuming data rows')
                record.update(columns=header,rows=sum(1 for _ in reader))
        records.append(record)
    result.append({'card':card,'files':records,
        'generator_config_filenames_present_in_public_config_directory':[name for name in ('v4_catalog_config.json','v4_weather_config.json') if (root/'config'/name).exists()]})
(ROOT/'actual_public_schema_probe_result.json').write_text(json.dumps({'records':result,
    'seed_values_emitted':False,'future_publication_files_read':False,'candidate_domain':None,
    'conclusion':'No disclosed seed domain or complete generator configs in these six public inputs; seed recovery experiment not admitted'},indent=2)+'\n')
print(json.dumps({'cards':len(result),'authorized_public_files_read':sum(len(r['files']) for r in result),
    'seed_key_paths_found':[f['seed_key_paths'] for r in result for f in r['files'] if f.get('seed_key_paths')],
    'generator_configs_found':[r['generator_config_filenames_present_in_public_config_directory'] for r in result],
    'actual_seed_search_performed':False}))
