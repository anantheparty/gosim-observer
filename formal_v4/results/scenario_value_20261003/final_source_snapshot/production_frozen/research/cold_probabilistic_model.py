#!/usr/bin/env python3
"""Independent public-model information experiment; no production policy imports.

Leave one local card out. The held-out card's truth is used ONLY in the scorer
side of synthetic, fixed 900s fields; the estimator sees public geometry,
current bulletin and previous exposure's rounded score feedback.
This is a conditional program-choice experiment, NOT a season score replay.
"""
from __future__ import annotations
import csv, json, sys, math, time
from pathlib import Path
from datetime import timedelta
import numpy as np
BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'upstream/gosim-observer-examples/runner'))
from challenge.v4_runner import load_scenario
from challenge.v4_scorer import WeatherTruth, program_band, score_target_exposure, lunar_quality_factor
from challenge.v4_fiber_map import FiberGrid, radec_to_altaz, min_altitude_during
from challenge.tile_geometry_simulator import _normalized_airmass
OUT=BASE/'results/cold_probabilistic_model_20261003'
PROGRAMS=('DARK','BRIGHT','BACKUP')
MULT=np.array([1.2,1.12,1.06])
KINDS=('rain','storm','overcast','haze','cold_snap','earthquake')


def mask(bulletin):
    # Only ALL-scope weather affects the site band; earthquake affects efficiency.
    m=0
    for n in bulletin.get('notices',[]):
        if n['event_kind'] in KINDS and (n.get('direction')=='ALL' or n['event_kind']=='earthquake'):
            m |= 1 << KINDS.index(n['event_kind'])
    return m


def bands(w):
    return np.where(w>=.65,0,np.where(w>=.4,1,2))


def geometry(target,start,site,cfg,duration=900):
    # Same <=120-second midpoint integration as public scorer.
    total=0.
    for sec in range(0,duration,120):
        span=min(120,duration-sec)
        moment=start+timedelta(seconds=sec+span/2)
        alt,_=radec_to_altaz(target['ra_deg'],target['dec_deg'],moment,site['latitude_deg'],site['longitude_deg'])
        total += span*lunar_quality_factor(target['ra_deg'],target['dec_deg'],moment,site,cfg)/_normalized_airmass(alt)**cfg['airmass_exponent']
    return total/duration


def prepare(card):
    sc=load_scenario(BASE/f'upstream/gosim-observer-examples/local-cards/{card}/config/v4_scenario.json')
    weather=WeatherTruth(sc.slots,[e for e in sc.events if e.event_type=='instrument_fault'])
    grid=FiberGrid.from_config(sc.fiber_config)
    directional=[e for e in sc.events if e.scope_type=='HORIZON_SECTOR']
    vectors=np.array([[math.cos(math.radians(t['dec_deg']))*math.cos(math.radians(t['ra_deg'])),math.cos(math.radians(t['dec_deg']))*math.sin(math.radians(t['ra_deg'])),math.sin(math.radians(t['dec_deg']))] for t in sc.targets])
    rows=[]
    for k,slot in enumerate(sc.slots):
        ts=slot.start_utc
        # Deterministic centers from the PUBLIC catalog; high altitude protects
        # probes from much of the terrain/rocket contamination but does not use
        # any hidden event boundary to choose a field.
        stride=max(1,len(sc.targets)//160)
        centers=[]
        for j in range(k%stride,len(sc.targets),stride):
            a,z=radec_to_altaz(sc.targets[j]['ra_deg'],sc.targets[j]['dec_deg'],ts,sc.site['latitude_deg'],sc.site['longitude_deg'])
            if 52<a<84:
                centers.append((j,a,z))
        if not centers:
            rows.append(None);continue
        center,a,z=centers[k%len(centers)]
        inds=np.flatnonzero(np.sum(vectors*vectors[center],axis=1) > math.cos(math.radians(1.83)))
        byfiber={}
        for j in inds:
            t=sc.targets[int(j)]
            cl=grid.classify_target(t['ra_deg'],t['dec_deg'],ts,a,z,sc.site['latitude_deg'],sc.site['longitude_deg'])
            if cl.region=='glass' and min_altitude_during(t['ra_deg'],t['dec_deg'],ts,slot.end_utc,sc.config)>=30:
                # Prefer a faint public target for non-censored feedback.
                if cl.fiber_id not in byfiber or t['feature_flux']<byfiber[cl.fiber_id]['feature_flux']:
                    byfiber[cl.fiber_id]=t
        targets=list(byfiber.values())
        if not targets:
            rows.append(None);continue
        geom=np.array([geometry(t,ts,sc.site,sc.score_config) for t in targets])
        actual=[];factors=[];b=[]
        segments=list(weather.segments(ts,slot.end_utc))
        active=[e for e in directional if e.overlaps(ts,slot.end_utc)]
        for t in targets:
            pos=lambda moment,t=t:radec_to_altaz(t['ra_deg'],t['dec_deg'],moment,sc.site['latitude_deg'],sc.site['longitude_deg'])
            bb=weather.band_quality(ts,slot.end_utc,sc.score_config,lambda moment:pos(moment)[0],lambda moment,t=t:lunar_quality_factor(t['ra_deg'],t['dec_deg'],moment,sc.site,sc.score_config))
            scored=score_target_exposure(t,segments,active,weather,900,1.,sc.score_config,ts,pos,sc.site)
            b.append(PROGRAMS.index(program_band(bb,sc.score_config)));actual.append(scored.score);factors.append(scored.factor)
        w=slot.transparency*slot.sky_quality/slot.seeing_arcsec/sc.score_config['q0'] if slot.is_observable else 0.
        rows.append(dict(time=ts.isoformat(),night=slot.slot_id.split('-S')[0],mask=mask(sc.bulletins[k]),w=w,e=slot.instrument_efficiency if slot.is_observable else 0.,geo=geom,x=np.array([t['feature_flux']*900/(.5*900) for t in targets])*geom,weight=np.array([t['science_weight'] for t in targets]),base=np.array(actual),factor=np.array(factors),band=np.array(b),target_ids=[t['target_id'] for t in targets]))
    return rows


def prior_particles(training,curmask,prevmask=None):
    # Empirical adjacent-slot transition prior. Day boundaries use the current
    # bulletin prior, since resetting across nights avoids assuming persistence.
    p=[];weights=[]
    for rows in training:
        for i,r in enumerate(rows):
            if r is None:continue
            prev=rows[i-1] if i else None
            adjacent=prev is not None and r['night']==prev['night']
            p.append((prev['w'] if adjacent else r['w'],prev['e'] if adjacent else r['e'],r['w'],r['e']))
            weight=1. if r['mask']==curmask else .025
            if prevmask is not None and adjacent and prev['mask']!=prevmask:weight*=.1
            weights.append(weight)
    return np.array(p),np.array(weights)


def scores(particles,row,program,columns=(2,3)):
    ww=particles[:,columns[0],None];ee=particles[:,columns[1],None]
    cap=np.minimum(row['x'][None,:]*ww*ee,1.)*row['weight'][None,:]
    bm=bands(ww*row['geo'][None,:])
    return cap*np.where(bm==program,MULT[program],1.)


def estimate_weights(particles,weights,prev,feedback,program):
    predicted=scores(particles,prev,program,(0,1))/prev['weight'][None,:]
    observed=feedback/prev['weight']
    # Score noise is zero except 1e-6 rounding; model discrepancy accounts for
    # unknown directional loss and the sparse empirical prior. Censoring is
    # naturally represented through min(...,1), never inverted as an equality.
    scale=.035+.09*np.maximum(observed,.15)
    loss=np.mean(np.minimum(((predicted-observed[None,:])/scale[None,:])**2,12.),axis=1)
    # A small contamination component keeps abrupt weather changes possible.
    return weights*(.01+.99*np.exp(-.5*loss))


def evaluate(cards):
    summary={};detail=[]
    for card,rows in cards.items():
        train=[v for k,v in cards.items() if k!=card]
        policies=('bulletin_prior','effective_as_band','joint_mean_band','joint_expected_premium')
        histories={p:None for p in policies}
        totals={p:0. for p in policies};oracle=0.;n=0;choices={p:[0,0,0] for p in policies}
        cert={'guaranteed_complete':0,'guaranteed_incomplete':0,'ambiguous':0,'ambiguity_actual_incomplete':0,'guaranteed_state_errors':0}
        for i,r in enumerate(rows):
            if r is None:continue
            truthscores=np.array([np.sum(r['base']*np.where(r['band']==p,MULT[p],1.)) for p in range(3)])
            oracle+=float(np.max(truthscores));n+=1
            for policy in policies:
                hist=histories[policy]
                adjacent=hist is not None and hist[0]['night']==r['night']
                part,prior=prior_particles(train,r['mask'],hist[0]['mask'] if adjacent else None)
                post=prior
                if adjacent and policy!='bulletin_prior':
                    post=estimate_weights(part,prior,*hist)
                post=post/post.sum()
                if policy=='effective_as_band' and adjacent:
                    prev,feedback,p=hist
                    unsat=feedback/prev['weight']<.999
                    if unsat.any():
                        # Common direct-feedback estimate, with optimistic match
                        # correction but no separate efficiency state.
                        val=np.median((feedback[unsat]/prev['weight'][unsat])/(prev['x'][unsat]*MULT[p]))
                    else:val=float(np.sum(post*part[:,2]*part[:,3]))
                    ch=int(bands(np.array([val*np.average(r['geo'],weights=r['weight'])]))[0])
                elif policy=='joint_mean_band':
                    val=float(np.sum(post*part[:,2]))
                    ch=int(bands(np.array([val*np.average(r['geo'],weights=r['weight'])]))[0])
                else:
                    expectations=np.array([np.sum(post*scores(part,r,p).sum(axis=1)) for p in range(3)])
                    ch=int(np.argmax(expectations))
                total=float(truthscores[ch]);totals[policy]+=total;choices[policy][ch]+=1
                feedback=np.round(r['base']*np.where(r['band']==ch,MULT[ch],1.),6)
                histories[policy]=(r,feedback,ch)
                if policy=='joint_expected_premium':
                    rr=feedback/r['weight'];eps=.500001e-6/r['weight']
                    low=np.maximum(0.,rr-eps)/max(MULT[ch],1.);high=np.minimum(rr+eps,1.)
                    good=low>=.5;bad=high<.5;amb=~(good|bad)
                    cert['guaranteed_complete']+=int(good.sum());cert['guaranteed_incomplete']+=int(bad.sum());cert['ambiguous']+=int(amb.sum())
                    cert['ambiguity_actual_incomplete']+=int(np.sum(amb&(r['factor']<.5)))
                    cert['guaranteed_state_errors']+=int(np.sum(good&(r['factor']<.5-1e-6))+np.sum(bad&(r['factor']>=.5)))
            if i%100==0:print(card,i,'/',len(rows),flush=True)
        summary[card]={'exposures':n,'oracle_program_science_sum':oracle,'policy_science_sum':totals,'policy_program_choices':choices,'raw_factor_certificate':cert,'scope':'Repeated fixed public fields, 900s, conditional on nominal geometry hits, unrepaired local faults, official per-target scorer. No best ledger / required settlement / stress hit simulation; conditional program regret only.'}
        print(json.dumps({card:summary[card]}),flush=True)
    return summary


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    started=time.time();cards={}
    for card in ('L1','L2','L3','L4'):
        print('prepare',card,flush=True);cards[card]=prepare(card)
    summary=evaluate(cards)
    report={'schema':'cold-probabilistic-model-v1','elapsed_seconds':time.time()-started,'method':'Leave-one-card-out empirical adjacent-slot Bayesian weather/efficiency prior. Heldout estimator uses only public bulletin, public lunar/airmass geometry, previous declared program and rounded scores. Truth isolated in scorer/environment.','results':summary}
    (OUT/'conditional_program_experiment.json').write_text(json.dumps(report,indent=2)+'\n')
    print('saved',OUT/'conditional_program_experiment.json',flush=True)
if __name__=='__main__':main()
