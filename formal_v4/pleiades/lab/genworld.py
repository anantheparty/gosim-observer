#!/usr/bin/env python3
"""Generate synthetic v4 cards with the official generator. usage: genworld.py name seed start_date nights targets area stress(0/1)"""
import sys, json, datetime
from pathlib import Path
sys.path.insert(0, '/home/shu/kamico/observer/hackathon-survey26')
from challenge.v4_bundle import build_card_bundle
name, seed, start, nights, targets, area, stress = sys.argv[1:8]
d0 = datetime.date.fromisoformat(start)
end = d0 + datetime.timedelta(days=int(nights) - 1)
spec = dict(name=name, card_id=name, scenario_slug=name, phase='local', seed=int(seed), start_date=start,
            end_date=end.isoformat(), targets=int(targets), area_deg2=float(area), stress=stress == '1', wallclock_seconds=900)
root = Path('/home/shu/kamico/observer/work/worlds') / name
build_card_bundle(root, spec)
print('built', root)
