"""Our 12 hidden-final runs (E-H, three each) and the replays of our runs, from the official snapshot
(hackathon-survey26 web/src/content/final: results.json + replays/<run_id>.json)."""
import json, os, csv, statistics
from datetime import datetime
ROOT = os.environ.get('FINAL_ROOT', '/home/shu/kamico/observer/hackathon-survey26/web/src/content/final')
TEAM = os.environ.get('FINAL_TEAM', 'Pleiades')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'pleiades_runs.csv')
d = json.load(open(os.path.join(ROOT, 'results.json')))
team = next(t for t in d['teams'] if t['name'] == TEAM)
P = lambda s: datetime.fromisoformat(s)
print('snapshot', d['generated_at'], '| team', TEAM, '| total', round(team['total'], 1))
rows = []
for card in d['cards']:
    runs = sorted((r for r in team['runs'] if r['card'] == card), key=lambda r: r['started_at'])
    scores = [r['score'] for r in runs]
    print('%s  mean %.1f  runs %s  spread %.0f' % (card, team['cards'][card], ' / '.join('%.1f' % s for s in scores),
                                                   max(scores) - min(scores)))
    for r in runs:
        row = dict(card=card, run=r['run_id'][:8], score=round(r['score'], 1), status=r['status'], termination=r['termination'],
                   clean=r['clean'], reruns=r['reruns'], wall_min=round((P(r['finished_at']) - P(r['started_at'])).total_seconds() / 60, 1))
        f = os.path.join(ROOT, 'replays', r['run_id'] + '.json')
        if os.path.exists(f):
            x = json.load(open(f))
            obs = [a for a in x['actions'] if a['a'] == 'observe']
            hours = sum(a['dt'] for a in obs) / 3600
            row.update(science=round(x['score']['base_science'], 1), non_science=round(x['score']['total'] - x['score']['base_science'], 1),
                       required_missing=len(x['required_missing']), targets_observed=x['completed'], exposures=len(obs),
                       observe_hours=round(hours, 1), interrupted=sum(1 for a in obs if a['cls'] == 'interrupted'))
        rows.append(row)
keys = list(dict.fromkeys(k for r in rows for k in r))
with open(OUT, 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=keys); w.writeheader(); w.writerows(rows)
for r in rows:
    print('  ', {k: v for k, v in r.items() if k not in ('status',)})
print('written', OUT)
