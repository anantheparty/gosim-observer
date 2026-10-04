"""Reuse two frozen public pilots; pattern LP algorithm and cost comparison only."""
from __future__ import annotations
import time
PROCESS_START=time.perf_counter()
import argparse,copy,hashlib,importlib.util,json,os,pickle,resource,sys
from datetime import timedelta
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1');os.environ.setdefault('MKL_NUM_THREADS','1')
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parent
OLD=ROOT.parent/'cold_public_opportunity_cost_20261004'

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(path,obj):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+'\n')

def verify_inputs(world):
    manifest=json.loads((OLD/'MANIFEST.json').read_text());checked={}
    for relative,expected in manifest.items():
        if relative=='pilot.py' or relative.startswith(('baseline_package/','official/','public_inputs/'+world+'/')):
            actual=sha(OLD/relative)
            if actual!=expected:raise RuntimeError('Prior manifest mismatch: '+relative)
            checked[relative]=actual
    return checked

spec=importlib.util.spec_from_file_location('old_public_pilot',OLD/'pilot.py')
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
import numpy as np
import scipy
from pattern_master import PatternGraph
IMPORT_SECONDS=time.perf_counter()-PROCESS_START

class Cost:
    stop_type=old.CostStop
    def __init__(self):self.start=time.perf_counter();self.cpu=time.process_time();self.stages=[];self.samples=[]
    @staticmethod
    def rss():
        value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if sys.platform=='darwin' else value*1024)
    def check(self):
        if time.perf_counter()-self.start>10.:raise self.stop_type('selection total wall exceeded 10 seconds')
        if self.rss()>512*1024**2:raise self.stop_type('selection max RSS exceeded 512 MiB')
    def stage(self,name,start,cpu):
        self.stages.append(dict(stage=name,wall_seconds=time.perf_counter()-start,cpu_seconds=time.process_time()-cpu,max_rss_bytes=self.rss()))
        self.check()
    def result(self):return dict(wall_seconds=time.perf_counter()-self.start,cpu_seconds=time.process_time()-self.cpu,
        max_rss_bytes=self.rss(),stages=self.stages,total_limit_seconds=10.,rss_limit_bytes=512*1024**2,
        import_wall_seconds=IMPORT_SECONDS,total_process_wall_seconds=time.perf_counter()-PROCESS_START,
        memory_includes_imports=True)

def run(world):
    checked=verify_inputs(world);cost=Cost();out=ROOT/'pilot'/world;out.mkdir(parents=True,exist_ok=True)
    trace=[];result=dict(world=world,future_truth_used=False,host_truth_scoring=False,initial_only=True,
        reuse_existing_public_pilot=True,environment=dict(python=sys.version,executable=sys.executable,
            scipy=scipy.__version__,numpy=np.__version__,platform=sys.platform,threads=1),verified_inputs=checked)
    try:
        t=time.perf_counter();cpu=time.process_time()
        initial=json.loads((OLD/'public_inputs'/world/'initialize.json').read_text())
        actor=old.wrapper.wrapped(copy.deepcopy(initial));now=old.parse_utc(initial['survey']['start_utc'])
        snapshot=dict(now_utc=old.format_utc(now),survey_end_utc=initial['survey']['end_utc'],observe_action_index=0,
            active_requests=[],new_messages=[],latest_bulletin=None,latest_forecast=None,last_result=None,
            wallclock=dict(remaining_seconds=120.))
        B=actor.decide(copy.deepcopy(snapshot));p=actor.planner
        result.update(initial_sha256=old.digest(initial),public_snapshot_sha256=old.digest(snapshot),baseline_action=B,
            baseline_pending_pickle_sha256=hashlib.sha256(pickle.dumps(actor.pending,protocol=5)).hexdigest(),targets=p.n,nights=len(p.nights))
        previous=json.loads((OLD/'pilot'/world/'RESULT.json').read_text())
        result['baseline_action_matches_prior']=old.digest(B)==old.digest(previous['baseline_action'])
        if not result['baseline_action_matches_prior']:raise RuntimeError('Original B action changed in this environment')
        cost.stage('public_initialization_and_original_B',t,cpu)
        geom=old.PublicGeometry(p,int(initial['survey']['slot_seconds']),cost);anchor=old.anchors(p)
        t=time.perf_counter();cpu=time.process_time();cols=[];start_set=set()
        for a,b in p.nights:
            for q in range(4):
                moment=(a+(b-a)*q/4).replace(microsecond=0);start_set.add(moment.timestamp())
                cols.extend(old.columns_at(p,geom,moment,anchor))
        base_end=now+timedelta(seconds=int(B['duration_seconds']))
        if base_end.timestamp() not in start_set:
            cols.extend(old.columns_at(p,geom,base_end,anchor));start_set.add(base_end.timestamp())
        cost.stage('whole_calendar_public_geometry_and_columns',t,cpu)
        t=time.perf_counter();cpu=time.process_time();graph=PatternGraph(p.n,p.nfib,cols)
        cost.stage('initial_pattern_graph_and_seed',t,cpu);result['initial_graph']=graph.metadata()
        model,sigma,lam,support=graph.solve(np.zeros(p.n),now.timestamp(),now.timestamp(),cost,'initial_pattern_LP',trace)
        result['initial_LP']=model
        if not model['converged']:raise old.CostStop('Initial full pricing not converged within declared working set budget')
        result['initial_value_difference_vs_prior']=model['value']-previous['initial_LP']['value']
        if abs(result['initial_value_difference_vs_prior'])>1e-6:raise RuntimeError('Pattern master differs from preserved prior value')
        proposals,price_meta=old.pricing(p,geom,now,sigma,graph,lam,cost)
        result.update(pricing=price_meta,proposals=proposals,proposals_outside_B=[old.digest(x['action'])!=old.digest(B) for x in proposals])
        t=time.perf_counter();cpu=time.process_time()
        for prop in proposals:
            end=now+timedelta(seconds=prop['action']['duration_seconds'])
            if end.timestamp() not in start_set:
                cols.extend(old.columns_at(p,geom,end,anchor));start_set.add(end.timestamp())
        patterns=graph.patterns;graph=PatternGraph(p.n,p.nfib,cols,patterns=patterns)
        cost.stage('common_end_union_pattern_graph_and_seed',t,cpu);result['common_graph']=graph.metadata()
        candidates=[('B',B)]+[(f'priced{k}',r['action']) for k,r in enumerate(proposals)]+[
            ('y_current=0',dict(action='none',duration_seconds=0)),
            ('empty_B_duration',dict(action='none',duration_seconds=B['duration_seconds']))]
        rows=[]
        for name,action in candidates:
            b=old.score_action(p,geom,action,now);blocked=now.timestamp()+action['duration_seconds']
            model,_,_,support=graph.solve(b,blocked,now.timestamp(),cost,f'common_recourse_{name}',trace)
            t=time.perf_counter();cpu=time.process_time();control=graph.greedy(b,blocked,now.timestamp(),support)
            if control['increment']>model['full_feasible_dual_upper']+1e-6:raise RuntimeError('Feasible integer control exceeds model upper bound')
            cost.stage(f'feasible_integer_control_{name}',t,cpu)
            dump(out/f'CONTROL_{name.replace("=","_")}.json',dict(first_action=action,control=control))
            dump(out/f'MASTER_SUPPORT_{name.replace("=","_")}.json',support)
            row=dict(name=name,action=action,current_nominal_gain=float(b.sum()),future_LP_increment=model['value'],
                joint_nominal_LP_value=float(b.sum()+model['value']),
                joint_full_feasible_dual_upper=float(b.sum()+model['full_feasible_dual_upper']),
                joint_feasible_integer_control=float(b.sum()+control['increment']),model=model,
                control_observations=len(control['schedule']))
            rows.append(row);result['recourse']=rows
            if not model['converged']:raise old.CostStop('Common branch '+name+' pricing not converged within declared budget')
        baseline=rows[0];observes=[r for r in rows if r['action']['action']=='observe'];winner=observes[0]
        for r in observes[1:]:
            if r['joint_nominal_LP_value']>winner['joint_nominal_LP_value']+1e-7:winner=r
        result.update(selected=winner['name'],selected_action=winner['action'],
            selected_model_delta_vs_B=winner['joint_nominal_LP_value']-baseline['joint_nominal_LP_value'],
            changed_first_action=winner['name']!='B',status='completed',
            geometry_cache=dict(entries=geom.calls,integration_pieces=geom.integration_pieces,
                wall_seconds=geom.wall_seconds,cpu_seconds=geom.cpu_seconds),final_graph=graph.metadata())
        np.savez_compressed(out/'PUBLIC_NOMINAL_GRAPH.npz',target=graph.target,score=graph.score,
            edge_action=graph.edge_action,fiber=graph.fiber,starts=graph.starts,ends=graph.ends,
            centers=np.asarray([c['center'] for c in cols]),program=np.asarray([c['program'] for c in cols]),
            duration=np.asarray([c['duration'] for c in cols]),endpoints=graph.endpoints)
        cost.check()
    except old.CostStop as e:result.update(status='cost_stop',reason=str(e))
    except Exception as e:result.update(status='error',error_type=type(e).__name__,reason=str(e))
    result['cost']=cost.result();dump(out/'PRICING_TRACE.json',trace);dump(out/'RESULT.json',result)
    print(json.dumps(dict(world=world,status=result['status'],wall_seconds=result['cost']['wall_seconds'],
        max_rss_bytes=result['cost']['max_rss_bytes'],selected=result.get('selected'),reason=result.get('reason'))))
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--world',choices=['W90501','W90502'],required=True)
    args=parser.parse_args();run(args.world)
