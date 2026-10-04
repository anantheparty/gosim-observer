"""Count deployment support on actual strong public L1/L2/L3 action histories.

Only public targets/calendars/scenario site, own committed action/decision times
and public messages are read. Neither observations CSV nor truth is accessed.
"""
import csv,json,sys,bisect
from pathlib import Path
from datetime import datetime,timedelta
ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[2]
sys.path.insert(0,str(ROOT/'official'))
from challenge.v4_fiber_map import min_altitude_during
def dt(x):return datetime.fromisoformat(x.replace('Z','+00:00'))
def main():
    result={}
    for card in ['L1','L2','L3']:
        run=REPO/'formal_v4/results/request_geometry_integration_20261004/seasons/control'/card
        if card=='L3':run=REPO/'formal_v4/results/request_terminal_pair_20261004/seasons/control/L3'
        data=REPO/'formal_v4/upstream/gosim-observer-examples/local-cards'/card
        targets={row['target_id']:row for row in csv.DictReader(open(data/'public/targets.csv'))}
        config=json.loads((data/'config/v4_fiber_config.json').read_text())
        calendar=list(csv.DictReader(open(data/'public/v4_night_calendar.csv')))
        nights={r['night_id']:(dt(r['observing_start_utc']),dt(r['observing_end_utc']),r['night_date']) for r in calendar}
        decisions=list(csv.DictReader(open(run/'decisions.csv')));actions=[json.loads(x) for x in open(run/'actions.jsonl')]
        observe_actions=iter([a for a in actions if a['action']=='observe'])
        assert sum(r['action']=='observe' for r in decisions)==sum(a['action']=='observe' for a in actions)
        messages=[json.loads(x) for x in open(run/'messages.jsonl')]
        bulletins=sorted([x for x in messages if x.get('record_type')=='bulletin'],key=lambda x:x['issued_at_utc'])
        forecasts=sorted([x for x in messages if x.get('record_type')=='forecast'],key=lambda x:x['issued_at_utc'])
        reqs=[x for x in messages if x.get('record_type')=='observation_request']
        stats={'observes':0,'all_targets_min80':0,'all_targets_min55':0,'clean55_history':0,'prediction_80_history8':0,
               'prediction_55_history8':0,'prediction_65_history8':0,'no_future_event_night':0,'active_req_excluded':0}
        history=[];forecast={};bins=[]
        for row in decisions:
            if row['action']=='report':history=[];continue
            if row['action']!='observe':continue
            action=next(observe_actions)
            stats['observes']+=1;start=dt(row['start_utc']);end=dt(row['end_utc'])
            night=next((n for n in nights.values() if n[0]<=start<n[1]),None)
            if not night:history=[];continue
            lower=min(min_altitude_during(float(targets[t]['ra_deg']),float(targets[t]['dec_deg']),start,end,config)
                      for t in action['assignments'].values())
            stats['all_targets_min80']+=lower>=80;stats['all_targets_min55']+=lower>=55
            for f in forecasts:
                if dt(f['issued_at_utc'])<=start:forecast=f
            predict_clean=not any(night[2] in n.get('nights',[]) for n in forecast.get('notices',[]))
            if predict_clean:stats['no_future_event_night']+=1
            active=any(dt(r.get('available_from_utc',r['issued_at_utc']))<=start<dt(r['deadline_utc']) for r in reqs)
            if active:stats['active_req_excluded']+=1
            current=[b for b in bulletins if dt(b['issued_at_utc'])<=start<dt(b['issued_at_utc'])+timedelta(seconds=900)]
            throughout=[b for b in bulletins if start<dt(b['issued_at_utc'])<end]+current
            clean=not any(n.get('event_kind')!='terrain_obstruction' for b in throughout for n in b.get('notices',[]))
            available=len(history)>=8 and predict_clean and not active and (night[1]-start).total_seconds()>=3600
            if available and lower>=80:stats['prediction_80_history8']+=1
            if available and lower>=65:stats['prediction_65_history8']+=1
            if available and lower>=55:stats['prediction_55_history8']+=1
            if clean and lower>=55 and 60<=float(row['duration_seconds'])<=3000:
                history.append((start,end));history=history[-8:];stats['clean55_history']+=1
            # Skipping unsupported sensor history is legitimate; every accepted
            # record carries its actual elapsed observing clock.  A stale
            # history is separately blocked after 8 observing hours.
            if history and (end-history[-1][1]).total_seconds()>8*3600:history=[]
            bins.append(lower)
        stats['minimum_altitude_quantiles']=[float(x) for x in __import__('numpy').quantile(bins,[0,.25,.5,.75,1])]
        result[card]=stats
    (ROOT/'public_support_audit.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main()
