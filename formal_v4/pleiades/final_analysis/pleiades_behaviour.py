"""What our final agent did on the hidden cards, from the replays of our runs (one replay per card):
science before the first instrument fault, recovery after fault changes, pointing, Moon, exposure lengths and
exposures started while the dome was closed."""
import json, os, sys, math, bisect, statistics, collections
from datetime import datetime, timedelta
sys.path.insert(0, os.environ.get('AGENT_DIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'agent')))
from astro import alt_scalar, moon_state  # noqa: E402
ROOT = os.environ.get('FINAL_ROOT', '/home/shu/kamico/observer/hackathon-survey26/web/src/content/final')
TEAM = os.environ.get('FINAL_TEAM', 'Pleiades')
d = json.load(open(os.path.join(ROOT, 'results.json')))
mine = {r['run_id']: r['card'] for t in d['teams'] if t['name'] == TEAM for r in t['runs']}
P = lambda s: datetime.fromisoformat(s.replace('Z', ''))
TS = lambda s: datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
# first instrument fault per card (card_events.py); H is cut before the first data-loss window starts
CUT = {'v4-e': '2027-01-18T18:00', 'v4-f': '2027-11-04T20:45', 'v4-g': '2027-07-07T20:45', 'v4-h': '2027-05-18T18:00'}
ONSETS = {'v4-e': ['2027-01-18T18:00', '2027-02-11T18:15', '2027-03-02T20:30', '2027-03-25T15:00', '2027-05-24T20:00'],
          'v4-f': ['2027-11-04T20:45'],
          'v4-g': ['2027-07-07T20:45', '2027-08-12T19:45', '2027-09-14T01:00', '2027-10-12T03:30', '2027-11-12T02:45',
                   '2027-12-06T22:15'],
          'v4-h': ['2027-05-26T19:45', '2027-07-14T23:00']}
BINS = [(0, 0.5), (0.5, 1), (1, 2), (2, 4), (4, 8)]
replays = {}
for f in sorted(os.listdir(os.path.join(ROOT, 'replays'))):
    card = mine.get(f[:-5])
    if card and card not in replays:
        replays[card] = json.load(open(os.path.join(ROOT, 'replays', f)))
recovery = collections.defaultdict(list)
print('%-5s %10s %7s %6s %7s | %8s %8s %8s %8s %8s %8s' % ('card', 'opening', 'obs_h', 'n_exp', 'min/exp', 'sci/h', 'meanAlt',
                                                            'moonSep', 'meanMin', 'obsCls_h', 'waitCls_h'))
for card, x in sorted(replays.items()):
    obs = [a for a in x['actions'] if a['a'] == 'observe']
    # 1. science before the first fault (exposure score spread evenly over its targets, best so far per target)
    cut = datetime.fromisoformat(CUT[card]); best, early, hours, n = {}, 0.0, 0.0, 0
    for a in obs:
        before = P(a['t']) + timedelta(seconds=a['dt']) <= cut
        if before:
            hours += a['dt'] / 3600; n += 1
        if not a.get('targets') or a['score'] <= 0:
            continue
        per = a['score'] / len(a['targets'])
        for tid in a['targets']:
            if per > best.get(tid, 0.0):
                if before:
                    early += per - best.get(tid, 0.0)
                best[tid] = per
    # 2. recovery after fault changes: score per target per 15 min / median over the 48 h before the onset
    scored = [(P(a['t']), a) for a in obs if a.get('targets') and a['score'] > 0]
    rate = lambda a: a['score'] / len(a['targets']) / min(1.0, a['dt'] / 900)
    for on in ONSETS[card]:
        t0 = datetime.fromisoformat(on)
        ref = [rate(a) for t, a in scored if t >= t0 - timedelta(hours=48) and t + timedelta(seconds=a['dt']) <= t0]
        if len(ref) >= 10:
            m = statistics.median(ref)
            for lo, hi in BINS:
                recovery[(lo, hi)] += [rate(a) / m for t, a in scored if lo <= (t - t0).total_seconds() / 3600 < hi]
    # 3. pointing, Moon, exposure length, dome state
    lat, lon = x['site']['lat'], x['site']['lon']
    alts, msep = [], []
    for a in [a for a in obs if a.get('center')][::3]:
        t = TS(a['t']) + 0.5 * a['dt']
        ra, dec = a['center']['ra'], a['center']['dec']
        alts.append(alt_scalar(ra, dec, t, lat, lon))
        mv, illum, malt = moon_state(t, lat, lon)
        if malt > 0:
            r, dd = math.radians(ra), math.radians(dec)
            v = (math.cos(dd) * math.cos(r), math.cos(dd) * math.sin(r), math.sin(dd))
            msep.append(math.degrees(math.acos(max(-1, min(1, sum(p * q for p, q in zip(v, mv)))))))
    wopen = {TS(s['t']): s['open'] for s in x['weather']}
    slots = sorted(wopen)

    def closed(t):
        k = bisect.bisect_right(slots, t) - 1
        return k >= 0 and t < slots[k] + 900 and not wopen[slots[k]]
    obs_cls = sum(a['dt'] for a in obs if closed(TS(a['t']))) / 3600
    wait_cls = sum(300 for a in x['actions'] if a['a'] == 'wait' for k in range(int(a['dt'] // 300)) if closed(TS(a['t']) + 300 * k)) / 3600
    obs_h = sum(a['dt'] for a in obs) / 3600
    print('%-5s %10.0f %7.0f %6d %7.1f | %8.2f %8.1f %8.1f %8.1f %8.1f %8.1f' % (
        card, early, hours, n, 60 * hours / max(1, n), x['score']['base_science'] / obs_h, statistics.mean(alts),
        statistics.mean(msep), statistics.mean(a['dt'] for a in obs) / 60, obs_cls, wait_cls))
print('\nscore ratio after a fault change, pooled over %d onsets (exposures starting in the bin):' % sum(len(v) for v in ONSETS.values()))
print('  ' + '  '.join('%g-%gh %.2f (n=%d)' % (lo, hi, statistics.median(recovery[(lo, hi)]), len(recovery[(lo, hi)]))
                       for lo, hi in BINS if recovery[(lo, hi)]))
print('\nopening = science before the first fault (H: before 05-18 18:00 UTC), approximate; sci/h = official science per observing hour'
      ' (H includes the voided exposures); obsCls_h / waitCls_h = hours of exposures started / waited while the dome was closed')
