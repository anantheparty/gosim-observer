"""Same finite science-rate objective and one executable assignment for every predictor.
Truth is read only after predicted assignment/field/duration/program have been fixed.
No knot-threshold mass is used for required/REQ/Jain decisions.
"""
import numpy as np
from target_core import multiplier_matrix,expected_gain,PROGRAMS

def select_reference(predicted,mask,fiber,duration,public_wait=None):
    pred=np.asarray(predicted,float);S,Q,_=pred.shape;assert Q==320
    chosen=[];rates=[]
    for s in range(S):
        if public_wait is not None and public_wait[s]:chosen.append((0,0,[]));rates.append(0.);continue
        best=(-1.,None)
        for c in range(10):
            pool=np.flatnonzero(mask[s,c*32:(c+1)*32])+c*32
            if not len(pool):continue
            for p in range(3):
                assigned=[];value=0
                for f in sorted(set(fiber[s,pool])):
                    rows=pool[fiber[s,pool]==f];j=int(rows[np.argmax(pred[s,rows,p])]);g=pred[s,j,p]
                    if g>0:assigned.append(j);value+=g
                rate=value/duration[s,c]
                if rate>best[0]:best=(rate,(c,p,assigned))
        assert best[1] is not None
        chosen.append(best[1]);rates.append(best[0])
    return chosen,np.asarray(rates)


def select(predicted,mask,fiber,duration,public_wait=None):
    # Vector exact same-fiber maxima; one shared (candidate,program) argmax per state.
    pred=np.asarray(predicted,float);S,Q,_=pred.shape;assert Q==320
    values=pred.reshape(S,10,32,3);allowed=np.asarray(mask).reshape(S,10,32);fs=np.asarray(fiber).reshape(S,10,32)
    cell=np.zeros((S,10,3,16));rowchoice=np.zeros((S,10,3,16),int)
    for f in range(16):
        eligible=np.where((allowed&(fs==f))[...,None],values,-np.inf)
        arg=eligible.argmax(axis=2);maximum=np.take_along_axis(eligible,arg[:,:,None,:],axis=2).squeeze(2)
        cell[...,f]=np.where(np.isfinite(maximum)&(maximum>0),maximum,0);rowchoice[...,f]=arg
    rates=cell.sum(axis=3)/np.asarray(duration,float)[...,None]
    chosen=[];forecast=[]
    for s in range(S):
        if (public_wait is not None and public_wait[s]) or rates[s].max()<=0:chosen.append((0,0,[]));forecast.append(0.);continue
        c,p=divmod(int(np.argmax(rates[s])),3)
        rows=[c*32+int(rowchoice[s,c,p,f]) for f in range(16) if cell[s,c,p,f]>0]
        chosen.append((c,p,rows));forecast.append(float(rates[s,c,p]))
    return chosen,np.asarray(forecast)


def realized(chosen,data,score_config):
    mult=multiplier_matrix(score_config);rate=[];gains=[]
    for s,(c,p,rows) in enumerate(chosen):
        rows=np.asarray(rows,int);actual=np.maximum(0,data['weight'][s,rows]*data['effective'][s,rows]*mult[p,data['b'][s,rows]]-data['truebest'][s,rows]);gain=float(actual.sum());gains.append(gain);rate.append(gain/float(data['duration'][s,c]))
    return np.asarray(rate),np.asarray(gains)

def evaluate_prob(prob,data,score_config):
    pred=expected_gain(prob,data['weight'],data['best'],score_config)
    choices,forecast=select(pred,data['mask'],data['fiber'],data['duration'],data.get('public_wait'));actual,gain=realized(choices,data,score_config)
    point_choices,pointforecast=select(data['point'],data['mask'],data['fiber'],data['duration'],data.get('public_wait'));pointactual,pointgain=realized(point_choices,data,score_config)
    return dict(actual_rate=actual,predicted_rate=forecast,point_actual_rate=pointactual,mean_actual_rate=float(actual.mean()),mean_point_actual_rate=float(pointactual.mean()),mean_delta_vs_point=float((actual-pointactual).mean()),chosen=choices)

def bootstrap_pair(a,b,seed=949221,draws=20000):
    delta=np.asarray(a,float)-np.asarray(b,float);rng=np.random.default_rng(seed);means=delta[rng.integers(len(delta),size=(draws,len(delta)))].mean(1)
    return dict(worlds=len(delta),worldmean_delta=float(delta.mean()),paired_world_bootstrap95=[float(x) for x in np.quantile(means,[.025,.975])],positive_launch_gate=bool(delta.mean()>0 and np.quantile(means,.025)>0),bootstrap_seed=seed,draws=draws)

def finite_oracle(data,score_config):
    mult=multiplier_matrix(score_config);truth=np.maximum(0,data['weight'][...,None]*data['effective'][...,None]*mult[:,data['b']].transpose(1,2,0)-data['truebest'][...,None]);choices,rate=select(truth,data['mask'],data['fiber'],data['duration'],data.get('public_wait'));return rate

def executable_action(initial,data,state,choice):
    """Public action receipt; no effective/F/b/actual_hit label is accessed."""
    c,p,rows=choice
    if not rows:return dict(action='wait',duration_seconds=int(initial['instrument']['exposure']['min_duration_seconds']))
    columns=initial['targets']['columns'];ti=columns.index('target_id');targets=initial['targets']['rows']
    return dict(action='observe',duration_seconds=int(data['duration'][state,c]),program=PROGRAMS[p],pointing=dict(alt_deg=float(data['pointing'][state,c,0]),az_deg=float(data['pointing'][state,c,1])),assignments={str(int(data['fiber'][state,j])):str(targets[int(data['idx'][state,j])][ti]) for j in rows})
