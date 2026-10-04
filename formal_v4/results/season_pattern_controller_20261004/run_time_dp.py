"""New full-catalogue public experiment using target-dual interval paths."""
import os,time
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('MKL_NUM_THREADS','1')
import argparse,sys,json,copy,hashlib,traceback
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT/'baseline_package'))
from sparse_exact import install
install()
from public_states import states
from shared_graph import SharedGraph,Budget,CostStop,rss
from target_dual_dp import solve,oracle,physical_control
from run_actual import score_action,shaobj,dump
def plain(r):return {k:v for k,v in r.items() if k not in ('sigma','control','trace','paths')}
def serial_control(r):return {k:(v.tolist() if hasattr(v,'tolist') else v) for k,v in r['control'].items()}
def run(card,night,limit=52,reuse=False):
 out=ROOT/('time_dp_reuse' if reuse else 'time_dp')/f'{card}_night{night+1:02d}';out.mkdir(parents=True,exist_ok=True);process_start=time.perf_counter()
 result=dict(card=card,night_index=night,state_scope='full actual public catalogue and reconstructed past public score ledger; action parity not claimed',futuretruth_used=False)
 budget=None;g=None
 try:
  actor,snapshot,env,meta=next(states(card,[night]));budget=Budget(limit,1536);p=actor.planner
  B=p.choose(copy.deepcopy(snapshot),actor.scores,actor.factor_lower,copy.deepcopy(env),snapshot['active_requests'])
  result.update(meta=meta,baseline_action=B,ledger=dict(science_sum=float(actor.scores.sum()),positive_targets=int(np.count_nonzero(actor.scores)),required_debt=int(np.count_nonzero(p.required&(actor.factor_lower<p.req_threshold))),active_requests=len(snapshot['active_requests'])))
  dump(out/'CURRENT_PUBLIC_SNAPSHOT.json',snapshot);np.savez_compressed(out/'CURRENT_PUBLIC_LEDGER.npz',best_scores=actor.scores,factor_lower=actor.factor_lower)
  if reuse:
   prior=ROOT/'time_dp'/f'{card}_night{night+1:02d}';saved=np.load(prior/'CURRENT_PUBLIC_LEDGER.npz')
   if not np.array_equal(saved['best_scores'],actor.scores) or shaobj(snapshot)!=shaobj(json.loads((prior/'CURRENT_PUBLIC_SNAPSHOT.json').read_text())):raise RuntimeError('cached public state mismatched')
   t=time.perf_counter();g=SharedGraph.load(prior/'SHARED_PUBLIC_GRAPH.npz',actor,snapshot,budget);budget.stage('reused_shared_public_graph',t)
   result['cached_graph_reused']=True;result['shared_graph_sha256']=hashlib.sha256((prior/'SHARED_PUBLIC_GRAPH.npz').read_bytes()).hexdigest()
  else:g=SharedGraph(actor,snapshot,budget);g.save(out/'SHARED_PUBLIC_GRAPH.npz')
  result['graph']=g.metadata();b=actor.scores.copy()
  t=time.perf_counter();initial=solve(g,b,g.now.timestamp(),seconds=5.);budget.stage('initial_target_dual_time_DP',t)
  if initial is None:raise CostStop('no completed target dual oracle')
  result['initial']=plain(initial);dump(out/'INITIAL_TRACE.json',initial['trace']);dump(out/'INITIAL_CONTROL.json',serial_control(initial));np.savez_compressed(out/'INITIAL_PRICE.npz',sigma=initial['sigma'])
  # The concrete first schedule actions, plus all-current reduced-price maxima,
  # are valid proposals. They come from the shared full season, not old B's menu.
  values,_=g.oracle(b,initial['sigma'],np.zeros(g.nt),np.ones(g.na,dtype=np.uint8));now_actions=np.flatnonzero(g.starts==g.now.timestamp());order=now_actions[np.lexsort((now_actions,-values[now_actions]))]
  proposals=[];seen=set()
  for e in order:
   a,pred=g.action(e,b,initial['sigma'],env)
   if a is None:continue
   h=shaobj(a)
   if h in seen:continue
   seen.add(h);proposals.append(dict(action=a,graph_action=int(e),reduced_current_value=float(values[e]),differs_from_B=h!=shaobj(B)))
   if len(proposals)==2:break
  result['proposals']=proposals;branches=[];path_pool=list(initial['paths']);branch_inputs=[]
  for name,action in [('B',B)]+[(f'priced{k}',q['action']) for k,q in enumerate(proposals)]:
   first=score_action(g,action,env,b);current_gain=float((first-b).sum());blocked=g.now.timestamp()+int(action['duration_seconds']);t=time.perf_counter()
   model=solve(g,first,blocked,seconds=3.,sigma0=initial['sigma']);budget.stage('common_'+name,t)
   if model is None:branches.append(dict(name=name,status='no_oracle'));continue
   path_pool.extend(model['paths']);branch_inputs.append((name,action,first,blocked))
   dump(out/f'TRACE_{name}.json',model['trace']);dump(out/f'CONTROL_{name}.json',dict(first_action=action,first_ledger=first.tolist(),future=serial_control(model)))
   branches.append(dict(name=name,current_gain=current_gain,joint_feasible_lower=current_gain+model['feasible_lower'],joint_full_upper=current_gain+model['upper'],model=plain(model)))
  result['unshared_incumbent_branches']=copy.deepcopy(branches)
  # Every branch receives the same concrete path pool before comparing lower
  # bounds. Different finite solver progress must not masquerade as first-step
  # action value. The physical max ledger is rerun for each branch and path.
  unique_paths=sorted(set(tuple(path) for path in path_pool));t=time.perf_counter()
  for row,(name,action,first,blocked) in zip(branches,branch_inputs):
   controls=[physical_control(g,first,[e for e in path if g.starts[e]>=blocked-1e-7]) for path in unique_paths]
   best=max(controls,key=lambda c:c['increment']);row['joint_feasible_lower']=row['current_gain']+best['increment'];row['common_path_pool_size']=len(unique_paths)
   if row['joint_feasible_lower']>row['joint_full_upper']+1e-6:raise RuntimeError('common physical path lower exceeds full finite dual')
   dump(out/f'COMMON_CONTROL_{name}.json',dict(first_action=action,first_ledger=first.tolist(),future={k:(v.tolist() if hasattr(v,'tolist') else v) for k,v in best.items()}))
  budget.stage('common_physical_path_incumbent_revaluation',t,path_pool=len(unique_paths));dump(out/'COMMON_PATH_POOL.json',[list(x) for x in unique_paths]);result['branches']=branches
  if all('joint_feasible_lower' in q for q in branches):
   winner=max(branches,key=lambda q:(q['joint_feasible_lower'],q['name']=='B'));base=branches[0]
   result.update(status='completed',feasible_continuation_winner=winner['name'],joint_feasible_delta=winner['joint_feasible_lower']-base['joint_feasible_lower'],different_action=winner['name']!='B',strict_finite_model_certificate=winner['joint_feasible_lower']>base['joint_full_upper']+1e-7 if winner['name']!='B' else False)
  else:result['status']='incomplete'
 except (CostStop,StopIteration) as exc:result.update(status='cost_stop',reason=str(exc))
 except Exception as exc:result.update(status='error',reason=str(exc),traceback=traceback.format_exc())
 finally:
  result.update(process_seconds=time.perf_counter()-process_start,peak_rss_bytes=rss())
  if budget:result['cost']=dict(selector_seconds=time.perf_counter()-budget.start,limit=budget.limit,stages=budget.stages)
  dump(out/'RESULT.json',result);print(json.dumps({k:result.get(k) for k in ('card','night_index','status','reason','process_seconds','peak_rss_bytes','different_action','joint_feasible_delta','strict_finite_model_certificate')}),flush=True)
 return result
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--card',choices=['L1','L2'],required=True);ap.add_argument('--night',type=int,required=True);ap.add_argument('--seconds',type=float,default=52);ap.add_argument('--reuse-graph',action='store_true');a=ap.parse_args();run(a.card,a.night,a.seconds,a.reuse_graph)
