"""V2: learn negative-report background, then price the last free diagnostic."""
from __future__ import annotations
import collections,math,copy
from datetime import timedelta
import numpy as np
from persistent_fault_guard import PersistentFaultGuard as FixedGuard,parse_utc

ADAPTIVE_DEFAULTS=dict(background_distinct_slots=8,background_min_nights=2,
    background_relative_iqr_max=.20,new_drop_ratio_upper=.70,minimum_changed_slots=6,
    change_fault_prior=.10,log_ratio_sigma_per_night=.22,hypothetical_fault_multiplier=.50,
    minimum_fault_posterior=.90,future_fault_probability_max=.10,
    novel_science_extrapolation_fraction=.05,future_quota_science_capture_fraction=.05)

class AdaptiveFaultGuard(FixedGuard):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.adaptive_cfg=dict(ADAPTIVE_DEFAULTS)
        self.negative_utc=None;self.background=None;self.adaptive_features={}

    def ingest(self,snapshot):
        last=self.last;result=snapshot.get('last_result') or {}
        super().ingest(snapshot)
        if last and last['action']['action']=='report' and result.get('action')=='report' and result.get('correct'):
            self.negative_utc=None;self.background=None

    def release_false(self,snapshot):
        action=super().release_false(snapshot)
        self.negative_utc=snapshot['now_utc'];self.background=None
        return action

    def learn_background(self):
        if not self.negative_utc or self.background:return
        groups=collections.defaultdict(list)
        for row in self.rows:
            if row['start_utc']>=self.negative_utc:groups[(row['night'],row['slot'])].append(row)
        keys=list(groups)
        count=int(self.adaptive_cfg['background_distinct_slots'])
        if len(keys)<count:return
        selected=keys[-count:]
        if len({x[0] for x in selected})<int(self.adaptive_cfg['background_min_nights']):return
        lo=[float(np.median([r['ratio_lo'] for r in groups[k]])) for k in selected]
        hi=[float(np.median([r['ratio_hi'] for r in groups[k]])) for k in selected]
        q25,q75=np.quantile(hi,[.25,.75]);center=float(np.median(hi))
        if center<=0 or (q75-q25)/center>float(self.adaptive_cfg['background_relative_iqr_max']):return
        self.background={'ratio_lo':float(np.median(lo)),'ratio_hi':center,
                         'last_key':selected[-1],'nights':len({x[0] for x in selected}),
                         'end_utc':max(r['now_utc'] for k in selected for r in groups[k]),
                         'negative_report_utc':self.negative_utc}
        self.event('negative_report_background_learned',**self.background)

    def new_change(self,snapshot):
        self.learn_background()
        if not self.background:return {'qualified':False,'reason':'no_stable_negative_background'}
        groups=collections.defaultdict(list)
        for row in self.rows:
            if row['start_utc']>=self.background['end_utc']:groups[(row['night'],row['slot'])].append(row)
        keys=list(groups)[-int(self.cfg['distinct_public_slots']):]
        slots=[{'night':k[0],'key':k,'hi':float(np.median([r['ratio_hi'] for r in groups[k]])),'rows':groups[k]} for k in keys]
        threshold=self.background['ratio_lo']*float(self.adaptive_cfg['new_drop_ratio_upper'])
        low=[x for x in slots if x['hi']<threshold]
        nights=len({x['night'] for x in low});sectors={r['field_sector'] for x in low for r in x['rows']}
        ratio=float(np.median([x['hi'] for x in slots]))/max(1e-9,self.background['ratio_lo']) if slots else 1.
        x=math.log(max(1e-9,ratio));sigma=float(self.adaptive_cfg['log_ratio_sigma_per_night'])/math.sqrt(max(1,nights))
        mu=math.log(float(self.adaptive_cfg['hypothetical_fault_multiplier']))
        log_lr=(x*x-(x-mu)*(x-mu))/(2*sigma*sigma)
        prior=float(self.adaptive_cfg['change_fault_prior']);log_odds=math.log(prior/(1-prior))+log_lr
        posterior=1/(1+math.exp(-max(-700,min(700,log_odds))))
        qualified=(len(slots)>=int(self.cfg['distinct_public_slots']) and len(low)>=int(self.adaptive_cfg['minimum_changed_slots'])
                   and nights>=int(self.cfg['minimum_nights']) and len(sectors)>=int(self.cfg['minimum_field_sectors'])
                   and posterior>=float(self.adaptive_cfg['minimum_fault_posterior']))
        f={'qualified':qualified,'ratio_to_negative_background_upper':ratio,'low_slots':len(low),'distinct_slots':len(slots),
           'nights':nights,'field_sectors':len(sectors),'fault_posterior_model':posterior,'log_likelihood_ratio_model':log_lr,
           'background':self.background,'evidence_ranks':[r['rank'] for a in low for r in a['rows']]}
        self.adaptive_features=f
        return f

    def quota_value(self,snapshot,action,posterior):
        now=parse_utc(snapshot['now_utc'])
        remaining=sum(max(0.,(b-max(now,a)).total_seconds()) for a,b in self.p.nights)
        total=sum((b-a).total_seconds() for a,b in self.p.nights)
        pc=self.initial['scoring']['program'];maxmult=max([float(pc['mismatch_multiplier']),*map(float,pc['multipliers'].values())])
        room=float(np.sum(np.maximum(0.,self.p.weight*maxmult-self.actor.scores)))
        m=float(self.adaptive_cfg['hypothetical_fault_multiplier']);gain=0.
        predictions=(self.actor.pending or {}).get('prediction',{})
        for tid in action['assignments'].values():
            pred=predictions.get(tid)
            if not pred:continue
            i=self.p.index[tid];factor=max(0.,min(1.,float(pred.get('factor',0))))
            declared=action['program'];mult=float(pc['multipliers'][declared]) if pred.get('predicted_band')==declared else float(pc['mismatch_multiplier'])
            before=max(float(self.actor.scores[i]),float(self.p.weight[i])*factor*mult)
            after=max(float(self.actor.scores[i]),float(self.p.weight[i])*min(1.,factor/m)*mult)
            gain+=max(0.,after-before)
        B=min(room,gain*remaining/max(1,int(action['duration_seconds']))*float(self.adaptive_cfg['novel_science_extrapolation_fraction']))
        reward=float(self.reporting['correct_reward'])
        futureprob=float(self.adaptive_cfg['future_fault_probability_max'])*remaining/max(1.,total)
        V=futureprob*(reward+float(self.adaptive_cfg['future_quota_science_capture_fraction'])*room)
        ev=posterior*(reward+B)-(1-posterior)*V
        return {'current_action_repair_science_model':gain,'future_repair_science_model':B,'public_science_room':room,
                'future_fault_probability_model':futureprob,'last_quota_opportunity_value_model':V,'diagnostic_net_value_model':ev}

    def propose(self,snapshot,action,decision_started=None,analytical=False):
        first=super().propose(snapshot,action,decision_started,analytical)
        if first.get('action')=='report' or not self.enabled or self.cached is not None:return first
        if action.get('action')!='observe':return action
        free=int(self.reporting.get('false_report_free_allowance',0))-self.false_count
        if free!=1 or not self.negative_utc:return action
        f=self.new_change(snapshot)
        if not f['qualified']:return action
        value=self.quota_value(snapshot,action,float(f['fault_posterior_model']))
        f.update(value)
        if value['diagnostic_net_value_model']<=0:return action
        # All common time/rank, cooldown and live wallclock checks are inherited.
        old_reserve=self.cfg['free_quota_reserve'];old_negative=self.negative_level
        self.cfg['free_quota_reserve']=0;self.negative_level=None
        old_evidence=self.evidence
        self.latest_features={**f,'median_ratio_upper':float(self.background['ratio_hi'])*f['ratio_to_negative_background_upper']}
        self.evidence=lambda s:self.latest_features
        try:
            result=super().propose(snapshot,action,decision_started,analytical)
        finally:
            self.cfg['free_quota_reserve']=old_reserve;self.negative_level=old_negative;self.evidence=old_evidence
        if result.get('action')=='report':self.event('last_free_quota_priced_for_new_change',now_utc=snapshot['now_utc'],features=f)
        return result

    def summary(self):
        return {**super().summary(),'adaptive_parameters':self.adaptive_cfg,'negative_background':self.background,
                'new_change_features':self.adaptive_features,'decision_priors_are_unvalidated':True}
