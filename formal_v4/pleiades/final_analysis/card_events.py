"""Instrument faults, earthquakes and the H-card data loss, read off the official replays.

The replay's per-slot `eff` is the truth `instrument_efficiency` of the card (challenge/v4_weather_simulator.py:
base jitter x every active event's multiplier), i.e. the efficiency of a team that never reports: unrepaired
faults stay in it. A correct report restores eff / multiplier from the report until that fault ends
(challenge/v4_scorer.py, WeatherTruth._apply_fault). So a persistent step in `eff` is a fault change that every
team had to detect and report, and a sharp drop that recovers over the next nights is an earthquake.

The data loss (challenge/v4_runner.py, STATE_RESYNC_SCHEMA) invalidates the observe actions with 0-based index in
[floor(i*N), floor(j*N)), N = observe actions executed before the trigger. The replays mark them 'interrupted';
fitting one trigger time and one (i, j) to all public replays recovers the event."""
import json, os, math, statistics, collections
from datetime import datetime, timedelta
ROOT = os.environ.get('FINAL_ROOT', '/home/shu/kamico/observer/hackathon-survey26/web/src/content/final')
TEAM = os.environ.get('FINAL_TEAM', 'Pleiades')
d = json.load(open(os.path.join(ROOT, 'results.json')))
owner = {r['run_id']: (t['name'], r['card']) for t in d['teams'] for r in t.get('runs') or []}
P = lambda s: datetime.fromisoformat(s.replace('Z', ''))
weather, runs = {}, collections.defaultdict(dict)
for f in sorted(os.listdir(os.path.join(ROOT, 'replays'))):
    team, card = owner[f[:-5]]
    x = json.load(open(os.path.join(ROOT, 'replays', f)))
    weather.setdefault(card, x['weather'])
    runs[card].setdefault(team, x)

for card in sorted(weather):
    w = [s for s in weather[card] if s['open'] and s['eff']]
    e = [s['eff'] for s in w]
    night_no = {n: i + 1 for i, n in enumerate(dict.fromkeys(s['night'] for s in weather[card]))}
    print('== %s  (open slots %d)' % (card, len(e)))
    k, quake_until = 8, None
    while k < len(e) - 8:
        pre, post = statistics.median(e[k - 8:k]), statistics.median(e[k:k + 8])
        if abs(math.log(e[k] / e[k - 1])) < 0.12 or abs(math.log(post / pre)) < 0.1:
            k += 1
            continue
        t = P(w[k]['t'])
        later = statistics.median(e[k + 60:k + 120]) if k + 120 < len(e) else post
        if quake_until and t < quake_until:
            k += 1          # the nightly recovery steps of an earthquake
            continue
        kind = 'earthquake' if later / post >= 1.2 else 'fault change'
        if kind == 'earthquake':
            quake_until = t + timedelta(days=4)
        print('   %s UTC  night %3d  %s  eff %.3f -> %.3f (x%.2f)%s' % (
            w[k]['t'][:16], night_no[w[k]['night']], kind.ljust(12), pre, post, post / pre,
            '  -> %.3f two to four days later' % later if kind == 'earthquake' else ''))
        k += 8

# data loss: one trigger and one window (i, j) for all teams
for card, teams in sorted(runs.items()):
    obs = {}
    for team, x in teams.items():
        o = [a for a in x['actions'] if a['a'] == 'observe']
        bad = [i for i, a in enumerate(o) if a['cls'] == 'interrupted']
        if bad:
            obs[team] = (o, bad[0], bad[-1] + 1)
    if not obs:
        continue
    fits = []
    first = max(P(o[e_ - 1]['t']) for o, s, e_ in obs.values())     # the trigger comes after every window
    T = first
    while T < first + timedelta(days=10):
        fr = {tm: (s / sum(1 for a in o if P(a['t']) < T), e_ / sum(1 for a in o if P(a['t']) < T)) for tm, (o, s, e_) in obs.items()}
        spread = statistics.pstdev(v[0] for v in fr.values()) + statistics.pstdev(v[1] for v in fr.values())
        fits.append((spread, T, fr))
        T += timedelta(minutes=15)
    spread, T, fr = min(fits, key=lambda z: z[0])
    print('== %s data loss: trigger ~%s UTC, window [%.4f, %.4f) of the observe actions so far (spread %.5f)' % (
        card, T.strftime('%Y-%m-%d %H:%M'), statistics.mean(v[0] for v in fr.values()), statistics.mean(v[1] for v in fr.values()), spread))
    starts = sorted(o[s]['t'][:10] for o, s, e_ in obs.values())
    print('   void windows in the %d public replays start between %s and %s' % (len(starts), starts[0], starts[-1]))
    if TEAM in obs:
        o, s, e_ = obs[TEAM]
        hours = sum(a['dt'] for a in o[s:e_]) / 3600
        print('   %s: void %s -> %s  (%.1f days)  %d exposures  %.1f exposure hours' % (
            TEAM, o[s]['t'][:16], o[e_ - 1]['t'][:16], (P(o[e_ - 1]['t']) - P(o[s]['t'])).total_seconds() / 86400, e_ - s, hours))
