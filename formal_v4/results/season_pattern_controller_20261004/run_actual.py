"""Measured full-catalogue public states; never executes a full season."""
from __future__ import annotations
import os,time
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
START=time.perf_counter()
import argparse,copy,hashlib,json,sys,traceback,math
from pathlib import Path
from datetime import timedelta
import numpy as np
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT/'baseline_package'))
from sparse_exact import install
install()
from public_states import states
from shared_graph import SharedGraph,Budget,CostStop,rss
from research.spatial_candidates import local_sidereal,PROGRAMS,parse_utc
from research.feedback_model import seasonal_quality

def audit(event,args):
 if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
  parts=Path(os.fsdecode(args[0])).parts
  if 'truth' in parts or 'generated_worlds' in parts:raise PermissionError('actor futuretruth access forbidden')
sys.addaudithook(audit)
def shaobj(obj):return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def dump(p,o):Path(p).write_text(json.dumps(o,indent=2,sort_keys=True,allow_nan=False)+'\n')
def plain(r):return {k:v for k,v in r.items() if k not in ('sigma','lam','support')} if r else None

def score_action(graph,action,env,b):
 p=graph.p;now=graph.now;actor=graph.actor;ledger=b.copy()
 if not action or action.get('action')!='observe':return ledger
 ids=np.asarray([p.index[t] for t in action['assignments'].values()],dtype=int)
 d=int(action['duration_seconds']);pr=PROGRAMS.index(action['program']);start=now;end=start+timedelta(seconds=d)
 a,z=next((a,z) for a,z in p.nights if a<=start<z)
 if end>z:raise ValueError('uncanonical night-clipped action')
 alt,az,hour,vectors=p._altaz(local_sidereal(start,p.lon));center=(float(action['pointing']['alt_deg'])+float(env.get('pointing_offset_alt_deg',0)),float(action['pointing']['az_deg'])+float(env.get('pointing_offset_az_deg',0)))
 fi,hit,_=p._classify(vectors[ids],*center)
 if not np.all(hit):raise ValueError('assigned target outside guarded predicted fibre')
 if list(map(int,action['assignments'].keys()))!=fi.tolist():raise ValueError('assigned fibre mismatches guarded predicted geometry')
 raw=np.zeros(len(ids));qb=np.zeros(len(ids));cursor=start
 while cursor<end:
  slot=math.floor((cursor-a).total_seconds()/actor.slot_seconds);e=min(end,a+timedelta(seconds=(slot+1)*actor.slot_seconds),cursor+timedelta(seconds=120));mid=cursor+(e-cursor)/2
  lst=local_sidereal(mid,p.lon);ma=p._altaz(lst)[0];geo=p._public_quality(mid,lst,ma)[ids]*p.q0
  C,E=actor.belief_clock.prior(actor.C,actor.E,mid,seasonal_quality(mid.timetuple().tm_yday,p.q0)[0]);scale=graph.field.raw_scale_at(mid,ids) if graph.field else np.ones(len(ids));dt=(e-cursor).total_seconds()
  raw+=dt*C*E*geo*scale;qb+=dt*C*geo;cursor=e
 factor=np.minimum(1,p.flux[ids]*raw/p.f0t0);band=np.where(qb/d>=p.dark_threshold,0,np.where(qb/d>=p.bright_threshold,1,2));score=p.weight[ids]*factor*np.where(band==pr,p.multipliers[pr],p.mismatch)
 ledger[ids]=np.maximum(ledger[ids],score);return ledger

def run(card,night,seconds,solve_seconds,build_only=False):
 out=ROOT/'actual'/f'{card}_night{night+1:02d}';out.mkdir(parents=True,exist_ok=True)
 result=dict(card=card,night_index=night,status='started',actor_futuretruth_used=False,actual_execution=False,
  state_scope='reconstructed from past public hits/scores/messages; no historical action parity claimed',
  model_scope='fixed conditional deterministic science best-only; finite one-hour geometry candidate domain')
 graph=None;budget=None
 try:
  t=time.perf_counter();state=next(states(card,[night]));actor,snapshot,env,meta=state
  result.update(meta=meta,history_rebuild_seconds=time.perf_counter()-t,environment=dict(python=sys.version,numpy=np.__version__,platform=sys.platform,threads=1))
  dump(out/'CURRENT_PUBLIC_SNAPSHOT.json',snapshot);dump(out/'CURRENT_ENV.json',{k:v.tolist() if hasattr(v,'tolist') else v for k,v in env.items()})
  np.savez_compressed(out/'CURRENT_PUBLIC_LEDGER.npz',best_scores=actor.scores,best_factor_lower=actor.factor_lower,required=actor.planner.required)
  result['current_ledger']=dict(science_sum=float(actor.scores.sum()),positive_targets=int(np.count_nonzero(actor.scores)),required_debt=int(np.count_nonzero(actor.planner.required&(actor.factor_lower<actor.planner.req_threshold))),active_requests=len(snapshot['active_requests']))
  budget=Budget(seconds=seconds,rss_mb=1536);t=time.perf_counter();B=actor.planner.choose(copy.deepcopy(snapshot),actor.scores,actor.factor_lower,copy.deepcopy(env),snapshot['active_requests']);Bpred=copy.deepcopy(actor.planner.last_prediction)
  result['baseline_action']=B;result['baseline_action_sha256']=shaobj(B);budget.stage('original_strong_request_planner_action',t)
  graph=SharedGraph(actor,snapshot,budget);result['graph']=graph.metadata()
  if build_only:result['status']='graph_completed';return result
  b=actor.scores.copy();initial=graph.solve(b,graph.now.timestamp(),seconds=solve_seconds,relative_gap=.005);result['initial_model']=plain(initial)
  if initial is None:raise CostStop('no completed restricted master before initial solver budget')
  np.savez_compressed(out/'INITIAL_DUAL.npz',sigma=initial['sigma'],lambda_time=initial['lam'],endpoints=graph.endpoints)
  allowed=np.ones(graph.na,dtype=np.uint8);r,_=graph.oracle(b,initial['sigma'],initial['lam'],allowed)
  current=np.flatnonzero(graph.starts==graph.now.timestamp());order=current[np.lexsort((current,-r[current]))];proposals=[];seen=set()
  for e in order:
   action,pred=graph.action(int(e),b,initial['sigma'],env)
   if action is None:continue
   h=shaobj(action)
   if h in seen:continue
   seen.add(h);proposals.append(dict(graph_action=int(e),action=action,prediction=pred,pricing_value=float(r[e]),action_differs_from_B=h!=shaobj(B)))
   if len(proposals)==2:break
  result['proposals']=proposals
  branches=[('B',B)]+[(f'priced{k}',p['action']) for k,p in enumerate(proposals)]
  rows=[]
  for name,action in branches:
   budget.check();first=score_action(graph,action,env,b);blocked=graph.now.timestamp()+int(action['duration_seconds']);t=time.perf_counter()
   model=graph.solve(first,blocked,seconds=solve_seconds,relative_gap=.005)
   if model is None:rows.append(dict(name=name,status='no_completed_master'));continue
   control=graph.greedy(first,model['support']);current_gain=float((first-b).sum())
   row=dict(name=name,current_gain=current_gain,joint_feasible_lower=current_gain+control['increment'],joint_full_upper=current_gain+model['upper'],joint_relaxed_lower=current_gain+model['lower'],model=plain(model),control_exposures=len(control['schedule']))
   rows.append(row);dump(out/f'CONTROL_{name}.json',dict(first_action=action,first_ledger=first.tolist(),schedule=control,model=plain(model)))
   dump(out/f'MASTER_SUPPORT_{name}.json',model['support']);budget.stage('branch_'+name,t)
  result['branches']=rows
  complete=[q for q in rows if 'joint_feasible_lower' in q]
  if len(complete)==len(branches):
   base=complete[0];winner=max(complete,key=lambda x:(x['joint_feasible_lower'],x['name']=='B'))
   result['selected_by_feasible_continuation']=winner['name'];result['selected_nominal_delta_lower']=winner['joint_feasible_lower']-base['joint_feasible_lower']
   result['strict_finite_model_certificate']=winner['name']!='B' and winner['joint_feasible_lower']>base['joint_full_upper']+1e-7
   result['different_current_action']=winner['name']!='B';result['status']='completed'
  else:result['status']='incomplete_branch_comparison'
 except (CostStop,StopIteration) as exc:result.update(status='cost_stop',reason=str(exc))
 except Exception as exc:result.update(status='error',reason=str(exc),error_type=type(exc).__name__,traceback=traceback.format_exc())
 finally:
  result.update(process_seconds=time.perf_counter()-START,peak_rss_bytes=rss())
  if budget:result['selector_cost']=dict(seconds=time.perf_counter()-budget.start,limit_seconds=budget.limit,stages=budget.stages)
  if graph:result['final_graph']=graph.metadata();dump(out/'PRICING_TRACE.json',graph.trace)
  dump(out/'RESULT.json',result);print(json.dumps({k:result.get(k) for k in ('card','night_index','status','reason','process_seconds','peak_rss_bytes','different_current_action','strict_finite_model_certificate')},allow_nan=False),flush=True)
 return result
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--card',choices=['L1','L2'],required=True);ap.add_argument('--night',type=int,required=True);ap.add_argument('--seconds',type=float,default=35);ap.add_argument('--solve-seconds',type=float,default=4);ap.add_argument('--build-only',action='store_true');a=ap.parse_args()
 run(a.card,a.night,a.seconds,a.solve_seconds,a.build_only)
