"""Figure for FINAL_RESULTS_ZH.md: cumulative science by night on the four hidden cards (our runs), with the
no-report instrument efficiency of the open slots and the first fault / data-loss marks (card_events.py).
Science is approximated: an exposure's score spread evenly over its targets, best so far per target."""
import json, os, collections, statistics
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
for _f in ('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc', '/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc'):
    if os.path.exists(_f):
        font_manager.fontManager.addfont(_f)
plt.rcParams['font.sans-serif'] = ['WenQuanYi Zen Hei', 'Noto Sans CJK SC', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
ROOT = os.environ.get('FINAL_ROOT', '/home/shu/kamico/observer/hackathon-survey26/web/src/content/final')
TEAM = os.environ.get('FINAL_TEAM', 'Pleiades')
OUT = os.environ.get('FINAL_OUT', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out'))
os.makedirs(OUT, exist_ok=True)
d = json.load(open(os.path.join(ROOT, 'results.json')))
mine = {r['run_id']: r['card'] for t in d['teams'] if t['name'] == TEAM for r in t['runs']}
MARKS = {'v4-e': [('2027-01-18T18:00', '第一次故障')], 'v4-f': [('2027-11-04T20:45', '第一次故障')],
         'v4-g': [('2027-07-07T20:45', '第一次故障')],
         'v4-h': [('2027-05-26T19:45', '第一次故障'), ('2027-06-21T13:00', '地震、数据丢失')]}
replays = {}
for f in sorted(os.listdir(os.path.join(ROOT, 'replays'))):
    card = mine.get(f[:-5])
    if card and card not in replays:
        replays[card] = json.load(open(os.path.join(ROOT, 'replays', f)))
fig, axes = plt.subplots(2, 2, figsize=(11, 7.2))
for ax, card in zip(axes.flat, d['cards']):
    x = replays[card]
    nights, eff = [], collections.defaultdict(list)
    for s in x['weather']:
        if s['night'] not in nights:
            nights.append(s['night'])
        if s['open']:
            eff[s['night']].append(s['eff'])
    best, gain = {}, collections.Counter()
    for a in x['actions']:
        if a['a'] != 'observe' or not a.get('targets') or a['score'] <= 0:
            continue
        per = a['score'] / len(a['targets'])
        for tid in a['targets']:
            if per > best.get(tid, 0.0):
                gain[a['slot'].split('-')[0]] += per - best.get(tid, 0.0)
                best[tid] = per
    cum, acc = [], 0.0
    for n in nights:
        acc += gain[n]; cum.append(acc)
    ax.plot(range(1, len(nights) + 1), cum, color='#d62728', lw=1.6)
    ax2 = ax.twinx()
    ax2.fill_between(range(1, len(nights) + 1), [statistics.mean(eff[n]) if eff[n] else 0 for n in nights],
                     color='0.85', alpha=0.5, step='mid')
    ax2.set_ylim(0, 3); ax2.set_yticks([0, 0.5, 1.0]); ax2.set_ylabel('不报修时的仪器效率', fontsize=8)
    for when, label in MARKS[card]:
        night = [s['night'] for s in x['weather'] if s['t'] <= when][-1]
        ax.axvline(nights.index(night) + 1, color='0.4', ls='--', lw=0.8)
        ax.annotate(label, (nights.index(night) + 1, 0.04), xycoords=('data', 'axes fraction'), fontsize=7, color='0.3',
                    xytext=(3, 0), textcoords='offset points')
    ax.set_zorder(ax2.get_zorder() + 1); ax.patch.set_visible(False)
    ax.set_title('卡 %s：累计科学分（按夜，近似）' % card[-1].upper()); ax.set_xlabel('第几晚')
fig.tight_layout(); fig.savefig(os.path.join(OUT, 'final_cumulative_science.png'), dpi=130); plt.close(fig)
print('written', os.path.join(OUT, 'final_cumulative_science.png'))
