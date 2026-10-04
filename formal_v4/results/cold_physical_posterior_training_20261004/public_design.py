"""Host cache of real public catalogs/calendars/physical strong action designs.

No original score, factor, validity, quality, program multiplier or fault label.
"""
from __future__ import annotations
import csv,json,sys,time,hashlib,pickle
from pathlib import Path
from datetime import datetime,timedelta,date,timezone
import numpy as np
ROOT=Path(__file__).resolve().parent;WORK=ROOT.parents[2]
OFFICIAL=ROOT/'official';sys.path.insert(0,str(OFFICIAL))
from challenge.observing_calendar import Night,Slot
from challenge.v4_scorer import lunar_quality_factor,_normalized_airmass
from challenge.v4_fiber_map import FiberGrid,radec_to_altaz,min_altitude_during
PROGRAMS=['DARK','BRIGHT','BACKUP']
def utc(s):return datetime.fromisoformat(s.replace('Z','+00:00'))
def design(card):
    initpath=WORK/f'formal_v4/results/policy_iteration_20261004/{card}_initialize_public.json'
    initial=json.loads(initpath.read_text());directory=WORK/'formal_v4/results/request_geometry_integration_20261004/seasons/control'/card
    actpath=directory/'actions.jsonl';decpath=directory/'decisions.csv'
    actions=[json.loads(s) for s in actpath.read_text().splitlines() if s]
    with decpath.open() as f:
        # Whitelist prevents accidentally loading private scorer columns.
        decisions=[{k:r[k] for k in ['action','start_utc','end_utc','duration_seconds']} for r in csv.DictReader(f)]
    nights=[];slots=[]
    for n in initial['survey']['nights']:
        a,b=utc(n['observing_start_utc']),utc(n['observing_end_utc']);night=Night(n['night_id'],date.fromisoformat(n['night_date']),a,b,a,b,int(n['slot_count']));nights.append(night)
        for j in range(night.slot_count):slots.append(Slot(f'{night.night_id}-S{j+1:03d}',night.night_id,a+timedelta(seconds=900*j),900))
    cols={k:j for j,k in enumerate(initial['targets']['columns'])};targets={r[cols['target_id']]:dict(ra_deg=float(r[cols['ra_deg']]),dec_deg=float(r[cols['dec_deg']]),feature_flux=float(r[cols['feature_flux']]),science_weight=float(r[cols['science_weight']])) for r in initial['targets']['rows']}
    ids=list(targets);index={s:j for j,s in enumerate(ids)};flux=np.asarray([targets[s]['feature_flux'] for s in ids]);weight=np.asarray([targets[s]['science_weight'] for s in ids])
    grid=FiberGrid(float(initial['instrument']['fiber_area_deg2']),float(initial['instrument']['gap_deg']),16)
    lat=float(initial['site']['latitude_deg']);lon=float(initial['site']['longitude_deg']);minimum=float(initial['site']['minimum_altitude_deg']);scoring=initial['scoring']
    source=[initpath,actpath,decpath];records=[];dcursor=0;starts=np.asarray([s.timestamp_utc.timestamp() for s in slots])
    for action in actions:
        row=decisions[dcursor];assert row['action']==action['action']
        if action['action']=='wait' and 'until_utc' in action:
            until=min(action['until_utc'],initial['survey']['end_utc'])
            while decisions[dcursor]['end_utc']<until:dcursor+=1
        if action['action']=='observe':
            start,end=utc(row['start_utc']),utc(row['end_utc']);d=int(row['duration_seconds']);pos=action['pointing'];assign={int(k):v for k,v in action['assignments'].items()}
            # Cache every assigned target with public altitude eligibility. New
            # world offsets decide actual fiber hits later, never old feedback.
            hits=grid.assigned_hits(assign,{s:(targets[s]['ra_deg'],targets[s]['dec_deg']) for s in assign.values()},start,float(pos['alt_deg']),float(pos['az_deg']),lat,lon)
            hitids=[s for s in assign.values() if min_altitude_during(targets[s]['ra_deg'],targets[s]['dec_deg'],start,end,initial)>=minimum]
            if hitids:
                targetidx=np.asarray([index[s] for s in hitids]);ras=np.asarray([targets[s]['ra_deg'] for s in hitids]);decs=np.asarray([targets[s]['dec_deg'] for s in hitids])
                ni=next(k for k,n in enumerate(nights) if n.observing_start_utc<=start<n.observing_end_utc)
                times=[];seconds=[];slotids=[];HH=[];AA=[];ZZ=[];cursor=start
                while cursor<end:
                    si=int(np.searchsorted(starts,cursor.timestamp(),side='right')-1);boundary=min(end,slots[si].end_utc)
                    while cursor<boundary:
                        right=min(boundary,cursor+timedelta(seconds=120));mid=cursor+(right-cursor)/2
                        altaz=np.asarray([radec_to_altaz(float(ra),float(dec),mid,lat,lon) for ra,dec in zip(ras,decs)])
                        h=[_normalized_airmass(float(alt))**(-float(scoring['airmass_exponent']))*lunar_quality_factor(float(ra),float(dec),mid,initial['site'],scoring) for ra,dec,alt in zip(ras,decs,altaz[:,0])]
                        HH.append(h);AA.append(altaz[:,0]);ZZ.append(altaz[:,1]);times.append(mid.timestamp());seconds.append((right-cursor).total_seconds());slotids.append(si);cursor=right
                records.append(dict(start=start.timestamp(),end=end.timestamp(),duration=d,night=ni,ids=targetidx,target_ids=hitids,fibers=np.asarray([next(f for f,s in assign.items() if s==tid) for tid in hitids]),ra=ras,dec=decs,program=PROGRAMS.index(action['program']),nominal_hits=np.asarray([hits[s] for s in hitids]),
                    pointing=[float(pos['alt_deg']),float(pos['az_deg'])],H=np.asarray(HH),alt=np.asarray(AA),az=np.asarray(ZZ),seconds=np.asarray(seconds),slots=np.asarray(slotids),times=np.asarray(times),
                    h_public=np.asarray(seconds)@np.asarray(HH)/d))
        dcursor+=1
    assert dcursor==len(decisions)
    summary=dict(card=card,targets=len(ids),actions=len(records),hits_mean=float(np.mean([len(r['ids']) for r in records])),duration_quantiles=np.quantile([r['duration'] for r in records],[0,.1,.5,.9,1]).tolist(),
        altitude_quantiles=np.quantile([r['pointing'][0] for r in records],[0,.1,.5,.9,1]).tolist(),geometry='all public assigned candidates with official public minimum-altitude gate; actual fiber hit recomputed once per new world offset at exposure start; fixed target RA/Dec; per-target <=120s Moon/airmass mesh and public slot boundaries',
        original_feedback_read=False,original_private_columns_read=False,sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source})
    return dict(initial=initial,nights=nights,slots=slots,actions=records,flux=flux,weight=weight,summary=summary)
def main():
    start=time.time();pack={c:design(c) for c in ['L1','L2']}
    with (ROOT/'public_design_cache.pkl').open('wb') as f:pickle.dump(pack,f,protocol=5)
    out={c:p['summary'] for c,p in pack.items()};out['seconds']=time.time()-start
    (ROOT/'public_design_manifest.json').write_text(json.dumps(out,indent=2));print(json.dumps(out))
if __name__=='__main__':main()
