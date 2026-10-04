"""Demonstrate direct-history/query inputs using only the public initializer."""
from __future__ import annotations
from datetime import datetime,timedelta
import math
import numpy as np
from challenge.v4_fiber_map import FiberGrid, radec_to_altaz, min_altitude_during
from challenge.v4_scorer import lunar_quality_factor, _normalized_airmass
from target_core import PROGRAMS

KINDS=('rain','overcast','haze','cold_snap','storm','rocket_launch','earthquake')
DIRECTIONS=('N','NE','E','SE','S','SW','W','NW','ALL')

def utc(s):return datetime.fromisoformat(s.replace('Z','+00:00'))

def clip_duration(initial,start,requested_duration):
    """Match official night/survey clipping, using only the public calendar."""
    end=min(start+timedelta(seconds=int(requested_duration)),utc(initial['survey']['end_utc']))
    night=next((n for n in initial['survey']['nights'] if utc(n['observing_start_utc'])<=start<utc(n['observing_end_utc'])),None)
    if night:end=min(end,utc(night['observing_end_utc']))
    return max(0,int((end-start).total_seconds()))

def publication_state(initial, seen_messages, available_until, query_night):
    """Explicit issue-time censoring, forecast coverage and observed quake anchors."""
    allowed=[m for m in seen_messages if 'issued_at_utc' not in m or utc(m['issued_at_utc'])<=available_until]
    bulletins=[m for m in allowed if m.get('record_type')=='bulletin']
    forecasts=[m for m in allowed if m.get('record_type')=='forecast']
    reports=[m for m in allowed if m.get('record_type')=='report_result']
    latest_bulletin=bulletins[-1] if bulletins else None
    latest_forecast=forecasts[-1] if forecasts else None
    last_report=reports[-1] if reports else None
    quake_first=None;active=False
    for msg in bulletins:
        quake=any(n['event_kind']=='earthquake' for n in msg.get('notices',[]))
        if quake and not active and 'issued_at_utc' in msg:quake_first=utc(msg['issued_at_utc'])
        active=quake
    night=next((n for n in initial['survey']['nights'] if n['night_date']==query_night),None)
    covered=False
    if latest_forecast and night:
        at=utc(night['observing_start_utc'])
        covered=utc(latest_forecast['coverage_start_utc'])<=at<utc(latest_forecast['coverage_end_utc'])
    return dict(allowed=allowed,bulletin=latest_bulletin,forecast=latest_forecast,
        report=last_report,quake_first_public_utc=quake_first,forecast_covers_query_night=covered,
        available_until_utc=available_until.isoformat())

def notice_features(initial, seen_messages, now, query_night):
    """Factorized sets accept every possible announced terrain direction set."""
    terrain=np.zeros(9);current=np.zeros((7,9));forecast=np.zeros((6,9))
    state=publication_state(initial,seen_messages,now,query_night)
    bulletin=None;latest_forecast=None;reports=[]
    for msg in state['allowed']:
        if msg.get('record_type')=='bulletin':
            bulletin=msg
            if msg.get('initial'):
                for n in msg.get('notices',[]):
                    if n['event_kind']=='terrain_obstruction':terrain[DIRECTIONS.index(n['direction'])]=1
        elif msg.get('record_type')=='forecast':latest_forecast=msg
        elif msg.get('record_type')=='report_result':reports.append(msg)
    if bulletin:
        for n in bulletin.get('notices',[]):
            if n['event_kind'] in KINDS:current[KINDS.index(n['event_kind']),DIRECTIONS.index(n['direction'])]=1
    if latest_forecast and state['forecast_covers_query_night']:
        for n in latest_forecast.get('notices',[]):
            if n['event_kind'] in KINDS[:6] and query_night in n.get('nights',[]):
                forecast[KINDS.index(n['event_kind']),DIRECTIONS.index(n['direction'])]=1
    # Both true and false formal results establish same-time healthy anchors;
    # future hidden faults remain possible. No physical weather value is inferred.
    age=1.;correct=0.;false=0.
    if reports:
        last=reports[-1];age=min(1.,(now-utc(last['issued_at_utc'])).total_seconds()/(7*86400))
        correct=float(last['correct']);false=float(not last['correct'])
    return np.concatenate([terrain,current.ravel(),forecast.ravel(),[age,correct,false]])

def action_metadata(initial, action, tokens, action_start, available_until, seen_messages, query_night):
    """Sixteen public metadata values; for current query pass action=None/tokens=[]."""
    state=publication_state(initial,seen_messages,available_until,query_night)
    def age(moment,scale):
        return min(1.,max(0.,(available_until-moment).total_seconds()/scale)) if moment else 1.
    duration=clip_duration(initial,action_start,action['duration_seconds'])/initial['instrument']['exposure']['max_duration_seconds'] if action else 0.
    assigned=len(tokens)/initial['instrument']['n_fibers'];hits=[t for t in tokens if t['actual_hit']]
    hit_fraction=len(hits)/initial['instrument']['n_fibers']
    columns=initial['targets']['columns'];wi=columns.index('science_weight');ti=columns.index('target_id')
    weight={r[ti]:r[wi] for r in initial['targets']['rows']}
    informative=[t for t in hits if weight[t['target_id']]>0]
    allzero=float(bool(informative) and all(t['score_six_decimal']==0 for t in informative))
    night=next(n for n in initial['survey']['nights'] if n['night_date']==query_night)
    phase=(action_start-utc(night['observing_start_utc'])).total_seconds()/max(1,(utc(night['observing_end_utc'])-utc(night['observing_start_utc'])).total_seconds())
    program=np.eye(3)[PROGRAMS.index(action['program'])] if action else np.zeros(3)
    b=state['bulletin'];f=state['forecast'];r=state['report']
    result=np.array([duration,age(action_start,7*86400),phase,assigned,hit_fraction,allzero,*program,
        age(utc(b['issued_at_utc']) if b and 'issued_at_utc' in b else None,initial['survey']['slot_seconds']),
        age(utc(f['issued_at_utc']) if f else None,7*86400),float(state['forecast_covers_query_night']),
        age(state['quake_first_public_utc'],7*86400),age(utc(r['issued_at_utc']) if r else None,7*86400),
        float(r['correct']) if r else 0.,float(not r['correct']) if r else 0.],dtype=np.float32)
    assert result.shape==(16,) and np.isfinite(result).all()
    return result

def geometry(initial, target, start, duration):
    duration=clip_duration(initial,start,duration)
    if duration<=0:raise ValueError('nonpositive actual duration is outside query domain')
    lat,lon=initial['site']['latitude_deg'],initial['site']['longitude_deg']
    end=start+timedelta(seconds=duration)
    night=next(n for n in initial['survey']['nights'] if utc(n['observing_start_utc'])<=start<utc(n['observing_end_utc']))
    night_start=utc(night['observing_start_utc']);slot_seconds=initial['survey']['slot_seconds']
    result=[];cursor=start
    while cursor<end:
        si=int((cursor-night_start).total_seconds()//slot_seconds)
        right=min(end,night_start+timedelta(seconds=(si+1)*slot_seconds))
        samples=[];seconds=[];piece=cursor
        while piece<right:
            piece_end=min(right,piece+timedelta(seconds=120));sample=piece+(piece_end-piece)/2
            alt,az=radec_to_altaz(target['ra_deg'],target['dec_deg'],sample,lat,lon)
            h=lunar_quality_factor(target['ra_deg'],target['dec_deg'],sample,initial['site'],initial['scoring'])/_normalized_airmass(alt)**initial['scoring']['airmass_exponent']
            samples.append((h,alt,az));seconds.append((piece_end-piece).total_seconds());piece=piece_end
        a=np.asarray(samples);weights=np.asarray(seconds);azrad=np.deg2rad(a[:,2])
        result.append([float(weights@a[:,0]/weights.sum()),float(a[:,0].min()),float(a[:,0].max()),
            float(a[:,1].min()/90),float(a[:,1].max()/90),float(weights@np.sin(azrad)/weights.sum()),
            float(weights@np.cos(azrad)/weights.sum()),float(weights.sum()/duration)])
        cursor=right
    assert len(result)<=5
    altstart,azstart=radec_to_altaz(target['ra_deg'],target['dec_deg'],start,lat,lon)
    altend,azend=radec_to_altaz(target['ra_deg'],target['dec_deg'],end,lat,lon)
    min_alt=min_altitude_during(target['ra_deg'],target['dec_deg'],start,end,{'site':initial['site']})
    return result,(altstart,azstart,altend,azend,min_alt),night

def query_features(initial,target,action,start):
    """Physical F/b only: no best, science weight, declared program or future hit."""
    duration=clip_duration(initial,start,action['duration_seconds']);parts,endpoints,night=geometry(initial,target,start,duration)
    trajectory=np.zeros((5,8));trajectory[:len(parts)]=parts
    a,z,ae,ze,minimum=endpoints
    season=(start-utc(initial['survey']['start_utc'])).total_seconds()/max(1,(utc(initial['survey']['end_utc'])-utc(initial['survey']['start_utc'])).total_seconds())
    phase=(start-utc(night['observing_start_utc'])).total_seconds()/initial['survey']['slot_seconds']%1
    max_duration=initial['instrument']['exposure']['max_duration_seconds']
    tail=[math.log(max(.001,target['feature_flux']))/4,duration/max_duration,a/90,minimum/90,
        math.sin(math.radians(z)),math.cos(math.radians(z)),ae/90,math.sin(math.radians(ze)),
        math.cos(math.radians(ze)),season,phase]
    out=np.concatenate([trajectory.ravel(),tail]).astype(np.float32)
    assert out.shape==(51,) and np.isfinite(out).all()
    return out

def history_target_features(initial,target,action,start,token,now,valid):
    # A zero science weight conveys no factor information through its score.
    # Original geometry/REQ processing retains the public hit separately.
    if target['science_weight']<=0:return np.zeros(24,dtype=np.float32)
    q=query_features(initial,target,action,start);parts=q[:40].reshape(5,8);keep=parts[:,7]>0
    h=float(np.sum(parts[:,0]*parts[:,7]));hmin=float(parts[keep,1].min());hmax=float(parts[keep,2].max())
    actual_hit=float(token['actual_hit']);score=token['score_six_decimal'] or 0.
    program=np.eye(3)[PROGRAMS.index(action['program'])]
    duration=clip_duration(initial,start,action['duration_seconds'])
    end=start+timedelta(seconds=duration)
    altmid,azmid=radec_to_altaz(target['ra_deg'],target['dec_deg'],start+(end-start)/2,
        initial['site']['latitude_deg'],initial['site']['longitude_deg'])
    grid=FiberGrid(initial['instrument']['fiber_area_deg2'],initial['instrument']['gap_deg'],initial['instrument']['n_fibers'])
    offset=grid.tangent_offsets(float(q[42])*90,math.degrees(math.atan2(float(q[44]),float(q[45])))%360,action['pointing']['alt_deg'],action['pointing']['az_deg']) or (0.,0.)
    data=[score/target['science_weight'],actual_hit,1-actual_hit,float(actual_hit and score==0),
        duration/initial['instrument']['exposure']['max_duration_seconds'],math.log(max(.001,target['feature_flux']))/4,*program,
        h,hmin,hmax,float(q[42]),altmid/90,float(q[46]),float(q[43]),
        math.sin(math.radians(azmid)),math.cos(math.radians(azmid)),offset[0]/grid.fov_side_deg,offset[1]/grid.fov_side_deg,
        min(1.,(now-end).total_seconds()/(7*86400)),min(1e6,.5/target['science_weight']),float(valid),1.]
    result=np.asarray(data,dtype=np.float32)
    assert result.shape==(24,) and np.isfinite(result).all()
    return result
