"""Organizer role: produce only new synthetic worlds after protocol freeze."""
import random
import shutil
from fixture import ROOT, build, digest, dump
import json

cfg = json.loads((ROOT / 'synthetic_nonseed_configs_frozen.json').read_text())
rng = random.SystemRandom()
seeds = [(s, True) for s in rng.sample(range(1024), 12)]
seeds += [(s, False) for s in rng.sample(range(1024, 2048), 4)]
rng.shuffle(seeds)
records = []
for i, (seed, in_domain) in enumerate(seeds):
    world_id = f'W{i:02d}'
    path = ROOT / 'worlds_SYNTHETIC' / world_id
    record = dict(world_id=world_id, SYNTHETIC_master=seed, in_domain=in_domain)
    try:
        build(path, cfg, seed, seed)
        public = ROOT / 'blind_public' / world_id
        public.mkdir(parents=True)
        for name in ('targets.csv', 'footprint.csv', 'v4_night_calendar.csv'):
            shutil.copyfile(path / 'public' / name, public / name)
        record.update(status='generated', footprint_sha256=digest((public / 'footprint.csv').read_bytes()))
    except Exception as exc:
        record.update(status='failed', error=f'{type(exc).__name__}: {exc}')
    records.append(record)
dump(ROOT / 'SYNTHETIC_SEALED_LABELS.json', records)
dump(ROOT / 'blind_public' / 'inventory.json', [dict(world_id=r['world_id'], status=r['status']) for r in records])
print(json.dumps(dict(generated=sum(r['status']=='generated' for r in records), failed=[r for r in records if r['status']=='failed'])))
