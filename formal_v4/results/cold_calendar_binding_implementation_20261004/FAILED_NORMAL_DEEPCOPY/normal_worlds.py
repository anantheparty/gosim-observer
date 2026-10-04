"""Bounded independent generated worlds, original strong normal replanning.

Research-only expected-science gate, NOT the strict runtime candidate. Every
branch gets only its own real runner snapshots, including loss and request
settlements. The normal 29-file chooser, params, request DP/cache and feedback
are unchanged; only one second-night pre-binding opportunity is proposed.
"""
import os
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
import copy
from datetime import timedelta
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

OUT=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(OUT))
from audit import vr,vs,wg,slots,scenario,fmt,utc,delta,score,site
sys.path.insert(0,str(OUT/'package'))
import binding_agent as entry
from binding_model import PublicScoreLedger,BoundarySearch,proposal_prediction
from research.geometry import parse_utc,format_utc

SEEDS=list(range(912101,912109))


class ExpectedBindingPolicy(entry.frozen.ExactCachedRequestPolicy):
    def __init__(self,initial,enabled):
        super().__init__(initial)
        self.enabled=enabled;self.public=PublicScoreLedger(initial);self.search=BoundarySearch(self,self.public)
        self.probed=False;self.boundary_events=[];self.armed=False

    def _geometric_H(self,start,duration,indices):
        if self._night(start)>=0:return super()._geometric_H(start,duration,indices)
        import numpy as np
        total=np.zeros(len(indices));end=start+timedelta(seconds=duration)
        for a,b in self.planner.nights:
            left=max(start,a);right=min(end,b)
            if left<right:total+=self.search._quality(left,int((right-left).total_seconds()),indices)*self.planner.q0
        return np.maximum(1e-9,total/duration)

    def decide(self,snapshot):
        self.public.ingest(snapshot);original=super().decide(snapshot)
        if not self.enabled or self.probed or original.get('action')!='wait':return original
        now=parse_utc(snapshot['now_utc']);a,b=self.planner.nights[1]
        if not self.planner.nights[0][1]<=now<a:return original
        early=a-timedelta(seconds=2700)
        if now<early:self.armed=True;return {'action':'wait','until_utc':format_utc(early)}
        if now!=early:return original
        self.probed=True
        before=(self.C,self.E,self.scores.copy(),self.factors.copy(),self.factor_lower.copy())
        pre=self.search.search(snapshot,terminal=False,lead=2700,effective_seconds=900)
        inside=self.search.search(snapshot,terminal=False,lead=0,effective_seconds=900)
        # Retain the original strong chooser as a forecast comparison. This
        # isolated copy has no future bulletin/request/feedback supplied.
        counter=copy.deepcopy(self)
        counter.enabled=False
        forecast_snapshot={**snapshot,'now_utc':format_utc(a),'last_result':{'action':'wait'},'new_messages':[]}
        native=counter.decide(forecast_snapshot)
        baseline_gain=0.
        if native.get('action')=='observe':
            program=native.get('program','BACKUP')
            for tid,pred in counter.planner.last_prediction.items():
                m=float(score['program']['multipliers'][program]) if pred.get('predicted_band')==program else float(score['program']['mismatch_multiplier'])
                baseline_gain+=max(0.,self.planner.weight[self.planner.index[tid]]*pred['factor']*m-self.public.best.get(tid,0.))
        reference=max(baseline_gain,inside['chosen']['predicted_science_gain'] if inside['chosen'] else 0.)
        row=pre['chosen'];forecast_delta=row['predicted_science_gain']-reference if row else None
        event={'now_utc':snapshot['now_utc'],'observe_rank':snapshot['observe_action_index'],'pre':pre,'inside':inside,'original_strong_forecast_action':native,
               'original_strong_forecast_first_science':baseline_gain,'same_duration_inside_science':inside['chosen']['predicted_science_gain'] if inside['chosen'] else 0.,
               'forecast_science_delta':forecast_delta,'adopted':bool(row and forecast_delta>0.),
               'gate':'research_only_expected_science_positive','strict_runtime_deployment':False,
               'rank_loss_jain_requests_settled_by_actual_runner':True,'unseen_future_information_used':False}
        self.boundary_events.append(event)
        import numpy as np
        assert self.C==before[0] and self.E==before[1] and np.array_equal(self.scores,before[2]) and np.array_equal(self.factors,before[3]) and np.array_equal(self.factor_lower,before[4])
        if not event['adopted']:return original
        action=row['action'];prediction=proposal_prediction(self,row)
        self.pending={'action':action,'start':now,'prediction':prediction,'notices':list(self.notices),'prior_C':row['C'],'prior_E':row['E']}
        self.planner.last_prediction=prediction
        return action


def make_world(seed,request):
    from challenge.observing_calendar import Night,Slot
    cfg=json.loads((OUT/'official/challenge/reference/v4/v4_weather_config.json').read_text());cfg['seed']=seed
    first=utc('2026-11-02T00:30:00Z');nights=[];calendar=[]
    for j in range(3):
        a=first+timedelta(days=j);b=a+timedelta(seconds=900);name=f'N_GENERATED_{j}'
        nights.append(Night(name,a.date(),a,b,a,b,1));calendar.append(Slot(name+'-S001',name,a,900))
    truth=wg.generate_weather(cfg,nights,calendar,[],[])
    ss=[vs.SlotTruth(r['slot_id'],utc(r['timestamp_utc']),utc(r['timestamp_utc'])+timedelta(seconds=r['duration_seconds']),r['is_observable']=='true',float(r['seeing_arcsec'] or 0),float(r['transparency'] or 0),float(r['sky_quality'] or 0),float(r['instrument_efficiency'] or 0)) for r in truth]
    public=json.loads((OUT/'public_inputs/L1_initialize_public.json').read_text())
    ts=[dict(zip(public['targets']['columns'],row)) for row in public['targets']['rows']]
    # A request's targets are fixed from public geometry/flux before any policy
    # decisions; the request becomes public only at the second-night start.
    a=nights[1].observing_start_utc;b=nights[1].observing_end_utc
    from challenge.v4_fiber_map import radec_to_altaz,min_altitude_during
    visible=[t for t in ts if min_altitude_during(t['ra_deg'],t['dec_deg'],a,b,{'site':site})>=30]
    targets=sorted(visible,key=lambda t:(-float(t['feature_flux']),str(t['target_id'])))[:32]
    requests=[dict(schema_version='v4-observation-request-v1',record_type='observation_request',request_id='GENERATED_NIGHT_REQUEST',issued_at_utc=a,deadline_utc=b,target_ids=[t['target_id'] for t in targets],minimum_completed=1,completion_factor_threshold=.5,completion_reward=100.,reason='independent_generator_information_stress')] if request else []
    stress=[dict(event_id='GENERATED_LOSS',event_type='data_loss',trigger_mode='fixed_date',trigger_ref=fmt(nights[2].observing_start_utc),window_start_fraction='.4',window_end_fraction='.6',window_max_fraction='.2')]
    sc=scenario('independent_strong_world',ts,ss,requests,stress)
    init=copy.deepcopy(public);init['survey']={'start_utc':fmt(ss[0].start_utc),'end_utc':fmt(ss[-1].end_utc),'slot_seconds':900,
         'nights':[dict(night_id=n.night_id,night_date=n.night_date.isoformat(),observing_start_utc=fmt(n.observing_start_utc),observing_end_utc=fmt(n.observing_end_utc),slot_count=1) for n in nights]}
    # No seed, truth, future request, or loss trigger enters this initialize.
    return sc,init,truth


def run_case(seed,request,enabled):
    sc,init,truth=make_world(seed,request);name=f'normal_{seed}_{"pre" if enabled else "control"}';snapshots=[];owner=None
    def factory(context):
        nonlocal owner
        owner=ExpectedBindingPolicy(init,enabled)
        def actor(snapshot):
            # Simulated participant budget is explicit; all planning keeps the
            # original frozen config. Small worlds still settle the full ledger.
            elapsed=time.perf_counter()-begin
            if elapsed>=900:raise vr.AgentTermination(vr.TERMINATION_WALLCLOCK)
            snapshot={**snapshot,'wallclock':{'remaining_seconds':max(0.,900.-elapsed),'elapsed_seconds':elapsed}}
            action=owner.decide(snapshot);snapshots.append({'snapshot':snapshot,'action':action})
            if time.perf_counter()-begin>=900:raise vr.AgentTermination(vr.TERMINATION_WALLCLOCK)
            return action
        return actor
    stub=OUT/f'{name}_scenario_stub.json';stub.write_text(json.dumps({'independent_seed':seed,'host_request':request})+'\n')
    begin=time.perf_counter()
    with patch.object(vr,'load_scenario',return_value=sc):report=vr.run_scenario(stub,factory,OUT/'runs'/name)
    (OUT/'runs'/name/'public_trace.json').write_text(json.dumps(snapshots,indent=2)+'\n')
    (OUT/'runs'/name/'boundary_events.json').write_text(json.dumps(owner.boundary_events,indent=2)+'\n')
    (OUT/'runs'/name/'owner_summary.json').write_text(json.dumps(owner.summary(),indent=2)+'\n')
    return {'report':report,'events':owner.boundary_events,'seconds':time.perf_counter()-begin,'truth':truth,'original_config':owner.config,
            'termination':report['termination']}


if __name__=='__main__':
    # This declaration and source are frozen before results are inspected.
    begin=time.perf_counter();rows=[]
    for i,seed in enumerate(SEEDS):
        request=i>=4
        control=run_case(seed,request,False);pre=run_case(seed,request,True)
        row={'seed':seed,'unpublished_night_request':request,'control':control,'pre':pre,'delta':delta(control['report'],pre['report'])}
        rows.append(row)
        (OUT/'normal_worlds_partial.json').write_text(json.dumps({'seeds':SEEDS,'rows':rows},indent=2)+'\n')
        print(json.dumps({'seed':seed,'request':request,'adopted':bool(pre['events'] and pre['events'][0]['adopted']),'delta':row['delta'],'seconds':control['seconds']+pre['seconds']},sort_keys=True),flush=True)
    result={'seeds':SEEDS,'worlds':3,'catalog':'exact_original_L1_public_all_targets','source_parameters_unchanged':True,'actual_card_truth_used':False,
            'normal_replanning_own_feedback':True,'rank_loss_requests_jain_full_settlement':True,'rows':rows,'mean_delta':sum(r['delta']['total'] for r in rows)/len(rows),'seconds':time.perf_counter()-begin,
            'deployment':'disabled_pending_independent_validation'}
    (OUT/'normal_worlds.json').write_text(json.dumps(result,indent=2)+'\n')
