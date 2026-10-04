"""Only public action, time, hit ID, and six-decimal score columns are consumed.

No future truth, host factor/quality/program-band columns, or teacher files are read.
The certificate deliberately requires an entire positive exposure inside one
public calendar slot; a cross-slot positive is not a certificate for either slot.
"""
import csv, json, hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent

def utc(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def analyze(name, source, calendar, seconds=900):
    manifest = []
    for n in ['actions.jsonl','decisions.csv','observations.csv','messages.jsonl']:
        p=source/n; manifest.append(dict(path=str(p.relative_to(ROOT)),sha256=sha(p)))
    rows=list(csv.DictReader((source/'decisions.csv').open()))
    # Whitelist discards the host-only factor/quality/prog_mult/valid fields.
    hits=defaultdict(list)
    for r in csv.DictReader((source/'observations.csv').open()):
        hits[int(r['observe_index'])].append(dict(target_id=r['target_id'],score=float(r['score'])))
    messages=[json.loads(s) for s in (source/'messages.jsonl').read_text().splitlines()]
    bulletins=sorted([m for m in messages if m.get('record_type')=='bulletin'],key=lambda x:x['issued_at_utc'])
    actions=[json.loads(s) for s in (source/'actions.jsonl').read_text().splitlines()]
    observes=[a for a in actions if a['action']=='observe']
    by_index={int(r['observe_index']):r for r in rows if r['action']=='observe'}
    assert len(observes)==len(by_index)
    submitted={i:a for i,a in zip(by_index,observes)}
    nights=[(utc(n['observing_start_utc']),utc(n['observing_end_utc'])) for n in calendar]
    def slot(t):
        for ni,(a,b) in enumerate(nights):
            if a<=t<b:
                si=int((t-a).total_seconds()//seconds)
                left=a+timedelta(seconds=si*seconds)
                return (ni,si,left,min(b,left+timedelta(seconds=seconds)))
        return None
    certificates=defaultdict(list); all_zero_waits=[]; certified=[]; total_zero=0
    for pos,r in enumerate(rows):
        if r['action']!='observe': continue
        rank=int(r['observe_index']); start=utc(r['start_utc']); end=utc(r['end_utc'])
        s=slot(start); hh=hits[rank]
        whole=s is not None and end<=s[3]
        positives=[h for h in hh if h['score']>0]
        if positives and whole:
            certificates[(s[0],s[1])].append(dict(observe_index=rank,start_utc=r['start_utc'],end_utc=r['end_utc'],positive_hits=len(positives),anchor=positives[0]))
        if not hh or positives:continue
        total_zero+=1
        if pos+1>=len(rows):continue
        following=rows[pos+1]
        if following['action']!='wait' or following['start_utc']!=r['end_utc']:continue
        at=slot(end)
        if at is None:continue
        B=at[3]
        if utc(following['end_utc'])!=B:continue
        last=next((m for m in reversed(bulletins) if utc(m['issued_at_utc'])<=end),{})
        closed_notice=any(n.get('direction')=='ALL' and n.get('event_kind') in ('rain','storm') for n in last.get('notices',[]))
        record=dict(observe_index=rank,zero_start=r['start_utc'],zero_end=r['end_utc'],zero_hits=len(hh),zero_wholly_same_slot=whole and at[:2]==s[:2],
                    wait_decision_id=following['decision_id'],wait_seconds=int(following['duration_seconds']),slot_start=at[2].isoformat(),slot_end=B.isoformat(),
                    closed_public_notice=closed_notice,notices=last.get('notices',[]),zero_action=submitted[rank])
        prior=certificates.get(at[:2],[])
        record['public_whole_slot_positive_certificates']=prior
        record['strict_trigger']=bool(prior) and record['zero_wholly_same_slot'] and not closed_notice and record['wait_seconds']>=60
        all_zero_waits.append(record)
        if record['strict_trigger']:certified.append(record)
    result=dict(name=name,all_zero_exposures=total_zero,all_zero_followed_slot_wait=len(all_zero_waits),all_zero_wait_seconds=sum(r['wait_seconds'] for r in all_zero_waits),
                strict_public_open_trigger_count=len(certified),strict_public_open_trigger_seconds=sum(r['wait_seconds'] for r in certified),
                strict_triggers=certified,all_zero_waits=all_zero_waits,source_manifest=manifest)
    return result

def main():
    results={}
    for c in ['alpha','beta','gamma','delta']:
        source=ROOT/f'formal_v4/results/cloud_request_cache_{c}_20261003'
        calendar_path=ROOT/f'formal_v4/practice_cards/{c}/{c}/public/v4_night_calendar.csv'
        calendar=list(csv.DictReader(calendar_path.open()))
        results[c]=analyze(c,source,calendar)
        results[c]['source_manifest'].append(dict(path=str(calendar_path.relative_to(ROOT)),sha256=sha(calendar_path)))
    for c in ['L1','L2','L3']:
        source=ROOT/(f'formal_v4/results/sparse_fault_actual_20261004/seasons/fault_fast/{c}' if c in ['L1','L2'] else 'formal_v4/results/strategy_reassessment_actual_20261004/seasons/fault/L3')
        initial_path=ROOT/f'formal_v4/results/policy_iteration_20261004/{c}_initialize_public.json'
        initial=json.loads(initial_path.read_text())
        results[c]=analyze(c,source,initial['survey']['nights'],initial['survey']['slot_seconds'])
        results[c]['source_manifest'].append(dict(path=str(initial_path.relative_to(ROOT)),sha256=sha(initial_path)))
    (OUT/'PUBLIC_CLOSURE_TRIGGER_ANALYSIS.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps({c:{k:v for k,v in r.items() if k not in ['strict_triggers','all_zero_waits','source_manifest']} for c,r in results.items()},indent=2))

if __name__=='__main__':main()
