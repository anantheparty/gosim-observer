"""Frozen common physical candidates: projection error != posterior error."""
import sys,json,time,hashlib,math
from datetime import datetime,timezone
import numpy as np
from physical_core import *
from physical_operator import qualities,contributions
from challenge.v4_fiber_map import FiberGrid,radec_to_altaz,altaz_to_radec,min_altitude_during
from strong_feedback_model import fit_feedback,seasonal_quality
from strong_belief_clock import BeliefClock

PROGRAMS=['DARK','BRIGHT','BACKUP']
def candidate_fields(w,j,duration,C,E,best):
    a=w.design['actions'][j];initial=w.design['initial'];site=initial['site'];lat=site['latitude_deg'];lon=site['longitude_deg'];start=datetime.fromtimestamp(a['start'],timezone.utc);end=datetime.fromtimestamp(a['start']+duration,timezone.utc)
    grid=FiberGrid(initial['instrument']['fiber_area_deg2'],initial['instrument']['gap_deg'],16);minimum=site['minimum_altitude_deg']
    source=[a]
    nexts=next((q for q in w.design['actions'][j+1:] if q['night']==a['night']),None)
    if nexts is not None:source.append(nexts)
    for field,b in enumerate(source):
        if field==0:pointing=a['pointing'];ids=b['ids'];ra=b['ra'];dec=b['dec'];fibers=b['fibers']
        else:
            future=datetime.fromtimestamp(b['start'],timezone.utc);center=altaz_to_radec(*b['pointing'],future,lat,lon);pointing=radec_to_altaz(*center,start,lat,lon)
            if not 0<=pointing[0]<=90:continue
            # Same public field pool for every model. A single assignment is
            # formed with the original public point C/E before path evaluation.
            buckets={}
            for z,(idx,r,d) in enumerate(zip(b['ids'],b['ra'],b['dec'])):
                clas=grid.classify_target(float(r),float(d),start,*pointing,lat,lon)
                if clas.region!='glass':continue
                if min_altitude_during(float(r),float(d),start,end,initial)<minimum:continue
                val=max(w.weight[idx]*min(1.,w.flux[idx]*duration*C*E*b['h_public'][z]/450.)-best[idx],0.)
                if clas.fiber_id not in buckets or val>buckets[clas.fiber_id][0]:buckets[clas.fiber_id]=(val,z)
            chosen=[buckets[k][1] for k in sorted(buckets)];ids=b['ids'][chosen];ra=b['ra'][chosen];dec=b['dec'][chosen];fibers=np.array(sorted(buckets))
        legal=np.asarray([min_altitude_during(float(r),float(d),start,end,initial)>=minimum for r,d in zip(ra,dec)],dtype=bool)
        ids=ids[legal];ra=ra[legal];dec=dec[legal];fibers=fibers[legal]
        if len(ids):yield field,ids,ra,dec,fibers,pointing

def family(w,j,repaired,C,E,best,bank):
    a=w.design['actions'][j];initial=w.design['initial'];night=w.design['nights'][a['night']];tail=int(night.observing_end_utc.timestamp()-a['start']);durations=sorted({min(tail,int(a['duration'])),*[min(tail,d) for d in [300,900,1800,3600]]})
    truth=path(w,j,repaired);point=dict(c=[C]*5,e=[E]*5,o=[1]*5,fault=[0]*5,events=[]);allpaths=[*bank,truth,point]
    real=[];pred=[];desc=[];quant=[];banderr=[];boundary=[];actualhits=[];nominal=[]
    nearest=int(np.argmin(np.sum((np.load(ROOT/'bank_features.npy')-path_feature(truth))**2,axis=1)))
    grid=FiberGrid(initial['instrument']['fiber_area_deg2'],initial['instrument']['gap_deg'],16);site=initial['site'];start=datetime.fromtimestamp(a['start'],timezone.utc)
    for duration in durations:
        for field,ids,ra,dec,fibers,pointing in candidate_fields(w,j,duration,C,E,best):
            qb,qz=qualities(w,j,ra,dec,duration,allpaths)
            hits=grid.assigned_hits(dict(zip(fibers,map(str,ids))),dict(zip(map(str,ids),zip(ra,dec))),start,*pointing,site['latitude_deg'],site['longitude_deg'],*w.offset)
            actual=np.array([hits[str(i)] for i in ids]);actualhits.append(int(actual.sum()))
            # Original strong direction prior is a public expectation. It is
            # applied to nominal Q only; true/path values use exact sector mesh.
            aa=np.asarray([radec_to_altaz(float(r),float(d),start,site['latitude_deg'],site['longitude_deg'])[1] for r,d in zip(ra,dec)])
            scale=np.ones(len(ids));si=int(a['slots'][0]);notices=w.bulletins[si]['notices']
            for n in notices:
                if n['direction'] not in DIRECTIONS:continue
                delta=np.abs((aa-DIRECTIONS[n['direction']]+180)%360-180)
                if n['event_kind'] in ['overcast','haze','rocket_launch','terrain_obstruction']:scale*=np.where(delta<30,.28 if n['event_kind']=='terrain_obstruction' else .55,1.)
            for n in w.bulletins[0]['notices']:
                if n['event_kind']=='terrain_obstruction' and n['direction'] in DIRECTIONS:
                    delta=np.abs((aa-DIRECTIONS[n['direction']]+180)%360-180);scale*=np.where(delta<25,.05,1.)
            qz[-1]*=scale
            for program in range(3):
                score=contributions(qb,qz,w.flux[ids],w.weight[ids],duration,program)
                gains=np.maximum(score-best[ids][None,:],0.)
                # Assignment is public and common; path hit prediction is the
                # commanded zero-offset nominal hit. Host actual offset affects
                # only realized value, and is never an actor model input.
                values=gains.sum(1)/duration;values[-2]=np.maximum(score[-2]*actual-best[ids],0.).sum()/duration
                real.append(values[-2]);pred.append(values[:len(bank)]);desc.append([field,duration,program,len(ids)])
                quant.extend(np.abs(score[nearest]-score[-2]).tolist());banderr.extend((np.where(qb[nearest]>=.65,0,np.where(qb[nearest]>=.4,1,2))!=np.where(qb[-2]>=.65,0,np.where(qb[-2]>=.4,1,2))).tolist())
                boundary.extend(np.minimum(np.abs(qb[-2]-.4),np.abs(qb[-2]-.65)).tolist())
                # Nominal baseline is the final point row, with the same family.
                nominal.append(values[-1])
    return np.asarray(real),np.asarray(pred),np.asarray(nominal),desc,quant,banderr,boundary,actualhits

def run(split):
    data=np.load(ROOT/('test_data.npz' if split=='test' else 'fit_data.npz'));bank=json.loads((ROOT/'physical_bank.json').read_text());bf=np.load(ROOT/'bank_features.npy');model=Predictor(ROOT/'physical_model.npz');training=np.load(ROOT/'fit_data.npz');prior=np.zeros(len(bank))
    for ix,y in zip(training['train_ix'],training['train_y']):prior[ix]+=y
    prior/=prior.sum();seeds=sorted(set(map(int,data[split+'_seed'])));results=[];quant=[];banderr=[];boundary=[];started=time.time()
    for seed in seeds:
        positions=np.flatnonzero(data[split+'_seed']==seed);order=np.random.default_rng(seed+9211).choice(positions,min(16,len(positions)),replace=False);wanted={int(data[split+'_j'][i]):i for i in order if data[split+'_x'][i,HISTORY*TOKEN_DIM+9]<.5}
        w=World(seed);state=PublicHistory(w);repaired=set();rng=np.random.default_rng(seed+401);chosen=set(rng.choice(np.arange(8,len(w.geometry)),min(128,len(w.geometry)-8),replace=False));best=np.zeros(len(w.flux));ledger=[]
        C,E=seasonal_quality(w.design['nights'][0].night_date.timetuple().tm_yday);clock=BeliefClock(w.design['initial']['survey']['nights'],900,w.design['initial']['survey']['start_utc']);loss=next((x for x in w.stress if x['event_type']=='data_loss'),None);lossdone=False
        if loss:losstime=next(e for e in w.events if e.event_id==loss['trigger_ref']).actual_end_utc.timestamp()
        for j,a in enumerate(w.geometry):
            if loss and not lossdone and a['start']>=losstime:
                state.resync_count+=1;first=int(float(loss['window_start_fraction'])*j);last=int(float(loss['window_end_fraction'])*j);best.fill(0)
                for rank,ids,s in ledger:
                    if not first<=rank<last:np.maximum.at(best,ids,s)
                lossdone=True
            sc=seasonal_quality(datetime.fromtimestamp(a['start'],timezone.utc).timetuple().tm_yday)[0];cp,ep=clock.prior(C,E,a['start'],sc)
            if j in wanted:
                i=wanted[j];x=state.feature(w,j);assert np.array_equal(x,data[split+'_x'][i]),(seed,j,np.max(np.abs(x-data[split+'_x'][i])))
                realized,table,point,desc,qe,be,bd,ah=family(w,j,repaired,cp,ep,best,bank)
                if len(realized):
                    p=model.probabilities(x);truth=path(w,j,repaired);nearest=int(np.argmin(np.sum((bf-path_feature(truth))**2,axis=1)));ix,ys,_=label_weights(truth,bf)
                    picks={'posterior':int(np.argmax(table@p)),'unconditional':int(np.argmax(table@prior)),'strong_point':int(np.argmax(point)),'nearest_prototype':int(np.argmax(table[:,nearest])),'perfect_soft_projection':int(np.argmax(table[:,ix]@ys))}
                    oracle=float(realized.max());regrets={k:oracle-float(realized[v]) for k,v in picks.items()};bankchoices=np.argmax(table,axis=0);bankoracle=float(realized[bankchoices].max())
                    results.append(dict(seed=seed,j=j,candidates=len(realized),regret=regrets,oracle_rate=oracle,dictionary_oracle_regret=oracle-bankoracle,chosen={k:desc[v] for k,v in picks.items()},posterior_vs_point_rate=float(realized[picks['posterior']]-realized[picks['strong_point']]),posterior_vs_prior_rate=float(realized[picks['posterior']]-realized[picks['unconditional']]),min_actual_hits=min(ah),max_actual_hits=max(ah)))
                    quant.extend(qe);banderr.extend(be);boundary.extend(bd)
            if rng.random()<.012:
                fault=w.active(a['start'],repaired);state.report(a['start'],fault is not None)
                if fault is not None:repaired.add(fault.event_id)
                E=.95
                if fault is None:C=sc
                clock.mark(a['start'])
            scores=w.score(j,repaired)[0];state.ingest(w,j,scores);np.maximum.at(best,a['ids'],scores);ledger.append((j,a['ids'],scores))
            if len(scores):
                fit=fit_feedback(scores,w.weight[a['ids']],w.flux[a['ids']],a['duration'],a['h_public'],PROGRAMS[a['program']],w.design['initial']['scoring'],cp,ep)
                if fit['informative'] and fit['loss']<2:C,E=fit['C'],fit['E'];clock.mark(a['start']+a['duration']/2)
        print(json.dumps(dict(split=split,seed=seed,queries=sum(r['seed']==seed for r in results),seconds=time.time()-started)),flush=True)
    keys=list(results[0]['regret']);means={k:float(np.mean([r['regret'][k] for r in results])) for k in keys};win=sum(r['posterior_vs_point_rate']>1e-12 for r in results);lose=sum(r['posterior_vs_point_rate']< -1e-12 for r in results);ties=len(results)-win-lose
    change={dimension:sum(r['chosen']['posterior'][pos]!=r['chosen']['strong_point'][pos] for r in results) for dimension,pos in [('field',0),('duration',1),('program',2)]}
    close=np.asarray(boundary)<.02
    out=dict(split=split,queries=len(results),regret_means=means,dictionary_oracle_regret_mean=float(np.mean([r['dictionary_oracle_regret'] for r in results])),posterior_vs_point=dict(win=win,lose=lose,tie=ties,mean_rate=float(np.mean([r['posterior_vs_point_rate'] for r in results]))),selection_change=change,prototype_score_error_quantiles=np.quantile(quant,[0,.5,.9,.99,1]).tolist(),prototype_band_mismatch=float(np.mean(banderr)),prototype_band_mismatch_near_boundary=float(np.mean(np.asarray(banderr)[close])) if close.any() else None,boundary_count=int(close.sum()),seconds=time.time()-started,scope='same finite public two-field x5-duration x3-program science gain/second family, common assignments; not full strong policy scores; clairvoyant dictionary oracle is coverage upper bound only',rows=results)
    (ROOT/(split+'_decision_regret.json')).write_text(json.dumps(out,indent=2));print(json.dumps({k:v for k,v in out.items() if k!='rows'}),flush=True)
if __name__=='__main__':run(sys.argv[1] if len(sys.argv)>1 else 'val')
