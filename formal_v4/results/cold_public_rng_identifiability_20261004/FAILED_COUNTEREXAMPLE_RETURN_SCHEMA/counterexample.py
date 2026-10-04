"""Generator-native two-world example. Entire data scope is SYNTHETIC_ONLY."""
import copy
import itertools
import json
from fixture import ROOT, build, digest, dump, read_rows, weather
from challenge.v4_workflow import V4Workflow
from challenge.v4_runner import run_scenario
from challenge.v4_fiber_map import radec_to_altaz, min_altitude_during
from challenge.contracts import parse_utc, format_utc
from datetime import timedelta

configs = json.loads((ROOT / 'synthetic_nonseed_configs_frozen.json').read_text())
cfg = copy.deepcopy(configs)
w = cfg['weather']
w['stress_tests']['enabled'] = False
cfg['card']['stress'] = False
cfg['card']['observation_requests']['count'] = 0
for value in w['weather_events']['conditions'].values():
    value['count'] = 0
for key in ('rocket_launch','earthquake','instrument_fault'):
    w[key]['count'] = 0
w['terrain_obstruction']['sector_count'] = [0,0]
for name, nominal in [('seeing_arcsec',1.), ('transparency',.9), ('sky_quality',.9)]:
    w['quality'][name].update(nominal=nominal, seasonal_amplitude=0., night_sigma=0., slot_sigma=0.)
w['quality']['instrument_efficiency'].update(jitter_minimum=.95,jitter_maximum=.95)
w['background_closure'].update(start_probability_per_open_slot=.2,
    seasonal_probability_amplitude=0.,reopen_probability_per_closed_slot=.5)
cfg['fiber']['field']['n_fibers'] = 1
cfg['fiber']['exposure'].update(min_duration_seconds=60,max_duration_seconds=60)
dump(ROOT / 'counterexample_nonseed_config.json', cfg)
statuses = []
prefixes = {}
for seed in range(100,132):
    test = copy.deepcopy(w)
    test['seed'] = seed
    nights, slots = weather.build_nights(test)
    rows = weather.generate_weather(test,nights,slots,[],[])
    prefixes[seed] = rows[:12]
    statuses.append(dict(SYNTHETIC_weather_seed=seed,
        first_12_open=[r['is_observable']=='true' for r in rows[:12]],
        prefix_sha256=digest(rows[:12])))
dump(ROOT / 'counterexample_candidate_prefix_status.json', statuses)
selected = None
pair_status = []
for a,b in itertools.combinations(range(100,132),2):
    first_difference = next((j for j in range(12) if prefixes[a][j]!=prefixes[b][j]), None)
    eligible = all(prefixes[s][j]['is_observable']=='true' for s in (a,b) for j in range(4)) and first_difference is not None and 4<=first_difference<=11
    pair_status.append(dict(seeds=[a,b],first_difference=first_difference,eligible=eligible))
    if selected is None and eligible:
        selected = (a,b,first_difference)
dump(ROOT / 'counterexample_all_pair_status.json', pair_status)
if selected is None:
    dump(ROOT / 'counterexample_result.json', dict(pass_gate=False,reason='No pair meets frozen gate; no rescue tuning'))
    raise SystemExit('Frozen pair gate failed')
a,b,j = selected
roots=[]
for label, seed in [('A',a),('B',b)]:
    path=ROOT/'counterexample_SYNTHETIC'/label
    build(path,cfg,7,seed)
    roots.append(path)
public_hashes=[]
for path in roots:
    public_hashes.append({str(f.relative_to(path)):digest(f.read_bytes())
        for dirname in ('config','public') for f in sorted((path/dirname).rglob('*')) if f.is_file()})
initials=[V4Workflow(path).initialize_payload(900) for path in roots]
targets=read_rows(roots[0]/'public/targets.csv')
wc=copy.deepcopy(w);wc['seed']=a
nights,slots=weather.build_nights(wc)
site=cfg['catalog']['site']
lat,lon=float(site['latitude_deg']),float(site['longitude_deg'])
tape={}
actions=[]
for i,slot in enumerate(slots[:j+1]):
    start=slot.timestamp_utc
    end=start+timedelta(seconds=60)
    scored=[]
    for target in targets:
        ra,dec=float(target['ra_deg']),float(target['dec_deg'])
        alt,az=radec_to_altaz(ra,dec,start,lat,lon)
        if min_altitude_during(ra,dec,start,end,cfg['fiber'])>=float(cfg['catalog']['observability']['minimum_altitude_deg']):
            scored.append((alt,target['target_id'],az))
    if not scored:
        raise RuntimeError('Public geometry gate: no visible target; no fixture tuning')
    alt,target_id,az=max(scored)
    action=dict(action='observe',duration_seconds=60,program='BACKUP',
        pointing=dict(alt_deg=alt,az_deg=az),assignments={'0':target_id})
    tape[format_utc(start)]=action
    actions.append(dict(now_utc=format_utc(start),action=action))
    tape[format_utc(end)]=None if i==j else dict(action='wait',until_utc=format_utc(slots[i+1].timestamp_utc))
dump(ROOT/'counterexample_public_action_tape.json',actions)
captures=[]
returns=[]
for label,path in zip(('A','B'),roots):
    capture=[]
    def factory(_context):
        def agent(snapshot):
            capture.append(copy.deepcopy(snapshot))
            return copy.deepcopy(tape[snapshot['now_utc']])
        return agent
    returns.append(run_scenario(path/'config/v4_scenario.json',factory,
        ROOT/'counterexample_SYNTHETIC'/f'runner_{label}'))
    captures.append(capture)
    dump(ROOT/f'counterexample_public_snapshots_{label}.json',capture)
past=[snap['last_result'] for snap in captures[0][:-1]
    if (snap.get('last_result') or {}).get('action')=='observe']
future_feedback=[c[-1]['last_result'] for c in captures]
gate=dict(public_config_bytes_identical=public_hashes[0]==public_hashes[1],
    initialize_identical=initials[0]==initials[1],
    public_past_snapshots_identical=captures[0][:-1]==captures[1][:-1],
    positive_past_feedback_count=sum(any(h['score']>0 for h in r['hits']) for r in past),
    past_observe_feedback_count=len(past),
    next_action_identical=True,
    next_score_feedback_differs=future_feedback[0]!=future_feedback[1],
    next_hits_one_each=all(r['hit_count']==1 for r in future_feedback),
    no_agent_errors=all(r['termination_reason']=='agent_finished' for r in returns))
pass_gate=all(value for key,value in gate.items() if key not in ('positive_past_feedback_count','past_observe_feedback_count')) and gate['positive_past_feedback_count']>=4
result=dict(pass_gate=pass_gate,gate=gate,SYNTHETIC_catalog_seed=7,
    SYNTHETIC_weather_seeds=[a,b],divergent_slot_index=j,
    divergent_slot_id=slots[j].slot_id,divergent_time=format_utc(slots[j].timestamp_utc),
    public_input_hashes=public_hashes,initialize_sha256=digest(initials[0]),
    identical_history_sha256=digest(captures[0][:-1]),future_score_only_feedback=future_feedback,
    generator_native=True,shared_master_required=False,
    limitation='Independent-weather-seed build_spec path with synthetic nonreference quality; existence proof only, not an actual-card seed recovery or common-master collision')
dump(ROOT/'counterexample_result.json',result)
print(json.dumps(result,indent=2))
if not pass_gate:
    raise SystemExit('Counterexample gate failed; all artifacts retained')
