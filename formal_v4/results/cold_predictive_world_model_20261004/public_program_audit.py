"""Actual strong prefixes: public score-only teacher history, no hidden quality.

This is a same-physical-action program-ranking audit, not a counterfactual season.
Observation CSV is projected to (observe_index,target_id,score) immediately;
factor/quality/program_multiplier/valid columns are never used.
"""
from pathlib import Path
import csv,json,sys,time
from datetime import datetime,timedelta
from types import SimpleNamespace
import numpy as np
ROOT=Path(__file__).resolve().parent;REPO=ROOT.parents[2];PACKAGE=ROOT/'package'
sys.path.insert(0,str(PACKAGE))
from research.spatial_candidates import SpatialPlanner
from research.geometry import parse_utc
from research.predictive_policy import install_predictive_policy,slot_geometry

def public_initial(card):
    carddir=REPO/'formal_v4/upstream/gosim-observer-examples/local-cards'/card
    config=json.loads((carddir/'config/v4_scenario.json').read_text());fiber=json.loads((carddir/'config/v4_fiber_config.json').read_text())
    score=json.loads((carddir/'config/v4_score_config.json').read_text())
    columns=['target_id','ra_deg','dec_deg','target_class','feature_flux','science_weight','required']
    rows=[]
    for row in csv.DictReader(open(carddir/'public/targets.csv')):
        for key in ['ra_deg','dec_deg','feature_flux','science_weight']:row[key]=float(row[key])
        row['required']=row['required']=='true';rows.append([row[k] for k in columns])
    nights=list(csv.DictReader(open(carddir/'public/v4_night_calendar.csv')))
    glass=np.sqrt(fiber['field']['fiber_area_deg2']);pitch=glass+fiber['field']['gap_deg']
    footprint={}
    for row in csv.DictReader(open(carddir/'public/footprint.csv')):
        footprint.setdefault(row['component_id'],[]).append([float(row['ra_deg']),float(row['dec_deg'])])
    return {'site':{**config['site'],'minimum_altitude_deg':config['minimum_altitude_deg']},
            'instrument':{**fiber['field'],'grid_side':4,'glass_side_deg':round(float(glass),6),
                'pitch_deg':round(float(pitch),6),'fov_side_deg':round(float(4*pitch),6),'exposure':fiber['exposure']},
            'survey':{'slot_seconds':900,'start_utc':nights[0]['observing_start_utc'],'end_utc':nights[-1]['observing_end_utc'],'nights':nights},
            'targets':{'columns':columns,'rows':rows},'scoring':score,
            'footprint':[{'component_id':k,'vertices':v} for k,v in footprint.items()]}

class ReplayBase:
    def __init__(self,initial):
        self.initial=initial;self.planner=SpatialPlanner(initial);self.scores=np.zeros(self.planner.n)
        self.pending=None;self.slot_seconds=900;self.notices=[]
    def _night(self,now):return next((k for k,(a,b) in enumerate(self.planner.nights) if a<=now<b),-1)
    def _ingest_result(self,snapshot):
        for hit in (snapshot.get('last_result') or {}).get('hits',[]):
            i=self.planner.index[str(hit['target_id'])];self.scores[i]=max(self.scores[i],float(hit['score']))
    def decide(self,snapshot):
        self._ingest_result(snapshot)
        for message in snapshot.get('new_messages',[]):
            if message.get('record_type')=='state_resync':
                self.scores[:]=0.
                for item in message['best_scores']:self.scores[self.planner.index[str(item['target_id'])]]=item['best_score']
        self.notices=(snapshot.get('latest_bulletin') or {}).get('notices',[])
        action=snapshot['audit_physical_action'];self.pending={'action':action,'start':parse_utc(snapshot['now_utc']),'notices':self.notices,'prediction':{}}
        return action
    def summary(self):return {}

def main():
    allresults={};changed=[];t=time.time()
    for card in ['L1','L2','L3']:
        run=REPO/'formal_v4/results/request_geometry_integration_20261004/seasons/control'/card
        if card=='L3':run=REPO/'formal_v4/results/request_terminal_pair_20261004/seasons/control/L3'
        policy=install_predictive_policy(ReplayBase)(public_initial(card))
        decisions=list(csv.DictReader(open(run/'decisions.csv')));actions=iter([json.loads(x) for x in open(run/'actions.jsonl') if json.loads(x)['action']=='observe'])
        # Project before constructing any actor snapshot.
        hitrows={}
        for r in csv.DictReader(open(run/'observations.csv')):
            hitrows.setdefault(int(r['observe_index']),[]).append({'target_id':r['target_id'],'score':float(r['score'])})
        messages=sorted([json.loads(x) for x in open(run/'messages.jsonl')],key=lambda m:m.get('issued_at_utc',''))
        previous_result=None;messagepos=0;bulletin={};reqs=[];physical_gates={'55':0,'65':0,'80':0}
        for row in decisions:
            now=parse_utc(row['start_utc']);new=[]
            while messagepos<len(messages) and parse_utc(messages[messagepos]['issued_at_utc'])<=now:
                m=messages[messagepos];new.append(m);messagepos+=1
                if m['record_type']=='bulletin':bulletin=m
                if m['record_type']=='observation_request':reqs.append(m)
            if row['action']=='report':
                policy.quality_history=[];previous_result={'action':'report'};policy.pending=None;continue
            if row['action']!='observe':continue
            action=next(actions)
            snapshot={'now_utc':row['start_utc'],'last_result':previous_result,'new_messages':new,'latest_bulletin':bulletin,
                      'active_requests':[r for r in reqs if now<parse_utc(r['deadline_utc'])],
                      'audit_physical_action':action}
            idx=np.asarray([policy.planner.index[s] for s in action['assignments'].values()])
            geometry=slot_geometry(policy.planner,now,int(row['duration_seconds']),idx)
            if geometry:
                for lower in ['55','65','80']:physical_gates[lower]+=bool(np.min(geometry[2])>=float(lower)+.05)
            result=policy.decide(snapshot)
            if result['program']!=action['program']:
                assert {k:v for k,v in result.items() if k!='program'}=={k:v for k,v in action.items() if k!='program'}
                changed.append({'card':card,'observe_index':int(row['observe_index']),'now_utc':row['start_utc'],
                                'old_program':action['program'],'new_program':result['program'],'duration':action['duration_seconds']})
            # This is a frozen actual prefix audit. Feed only actual public score,
            # including when the hypothetical program recommendation differed.
            policy.pending={'action':action,'start':now,'notices':list(policy.notices),'prediction':{}}
            previous_result={'action':'observe','observe_index':int(row['observe_index']),'hits':hitrows[int(row['observe_index'])]}
        allresults[card]={**policy.summary()['quality_nn'],'physical_min_altitude_gates':physical_gates}
    result={'public_only':True,'same_physical_action':True,'future_feedback_replanned':False,'actor_observation_columns':['observe_index','target_id','score'],
            'cards':allresults,'program_changes':changed,'seconds':time.time()-t,
            'claim':'actual public prefix recommendation audit; no counterfactual outcome/season score'}
    (ROOT/'public_program_audit.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main()
