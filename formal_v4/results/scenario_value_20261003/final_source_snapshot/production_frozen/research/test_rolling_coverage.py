"""Model semantics checks on public input only, no simulator truth."""
import copy
import json
from pathlib import Path
import sys
import time
import unittest

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from global_lp_pilot import public_initialization
from research.rolling_coverage import RollingCoveragePlanner

BASE=Path(__file__).resolve().parents[1]


class RollingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.init,_=public_initialization(BASE/'upstream/gosim-observer-examples/local-cards/L1')
        cls.p=RollingCoveragePlanner(cls.init,solve_seconds=2)

    def test_prefix_matches_official_mesh(self):
        p=self.p;start=p.nights[0][0]
        start=start.replace(minute=(start.minute+7)%60,second=13)
        prefix=p._quality_prefix(start,3600,p.nights[0][0])
        for duration in (60,179,900,1200,2387,3600):
            np.testing.assert_allclose(prefix(duration),p._H(start,duration,p.nights[0][0]),rtol=2e-15,atol=2e-15)

    def columns(self):
        return [dict(start=0,end=60,targets=[0],gains=[2.],factors=[1.]),
                dict(start=60,end=120,targets=[0],gains=[3.],factors=[1.]),
                dict(start=60,end=120,targets=[1],gains=[1.],factors=[1.])]

    def test_max_science_not_sum_and_required_not_repeated(self):
        p=self.p;missing=np.zeros(p.n,dtype=bool);missing[0]=True
        self.assertEqual(p._value([0,1],self.columns(),missing,[]),3.+p.req_penalty)

    def test_request_quorum_and_window(self):
        p=self.p;r=dict(id='q',targets={0,1},left=2,threshold=.5,reward=100.,issued=0.,end=120.)
        missing=np.zeros(p.n,dtype=bool);columns=self.columns()
        self.assertEqual(p._value([0,1],columns,missing,[r]),3.)
        self.assertEqual(p._value([0,2],columns,missing,[r]),103.)
        r['end']=119.
        self.assertEqual(p._value([0,2],columns,missing,[r]),3.)

    def test_master_enforces_time_and_quorum(self):
        p=self.p;r=dict(id='q',targets={0,1},left=2,threshold=.5,reward=100.,issued=0.,end=120.)
        missing=np.zeros(p.n,dtype=bool);columns=self.columns()
        A,rhs,obj,w,covered,times,nl,nq=p._model(columns,missing,[r]);ne=len(columns)
        result=milp(obj,integrality=np.r_[np.ones(ne),np.zeros(nl),np.ones(nq)],
                    bounds=Bounds(np.zeros(len(obj)),np.ones(len(obj))),constraints=LinearConstraint(A,-np.inf,rhs))
        chosen=np.flatnonzero(result.x[:ne]>.5).tolist()
        self.assertEqual(chosen,[0,2]);self.assertAlmostEqual(-result.fun,103.)

    def test_master_matches_exhaustive_small_schedules(self):
        p=self.p;rng=np.random.default_rng(5723)
        for trial in range(12):
            columns=[]
            for _ in range(6):
                ids=rng.choice(4,size=2,replace=False).tolist();start=int(rng.integers(0,4))*60
                columns.append(dict(start=start,end=start+int(rng.integers(1,4))*60,
                    targets=ids,gains=rng.integers(0,6,size=2).astype(float).tolist(),
                    factors=rng.choice([0.,.6,1.],size=2).tolist()))
            missing=np.zeros(p.n,dtype=bool);missing[:2]=True
            requests=[dict(id='q',targets={0,1,2,3},left=2,threshold=.5,reward=100.,issued=60.,end=300.)]
            best=0.
            for bits in range(1<<len(columns)):
                selected=sorted([k for k in range(len(columns)) if bits&(1<<k)],key=lambda k:columns[k]['start'])
                if all(columns[a]['end'] <= columns[b]['start'] for a,b in zip(selected,selected[1:])):
                    best=max(best,p._value(selected,columns,missing,requests))
            A,rhs,obj,w,covered,times,nl,nq=p._model(columns,missing,requests);ne=len(columns)
            result=milp(obj,integrality=np.r_[np.ones(ne),np.zeros(nl),np.ones(nq)],
                bounds=Bounds(np.zeros(len(obj)),np.ones(len(obj))),constraints=LinearConstraint(A,-np.inf,rhs),
                options={'mip_rel_gap':0.})
            self.assertAlmostEqual(-result.fun,best,places=7,msg=f'trial {trial}')

    def test_adapter_and_short_budget(self):
        p=RollingCoveragePlanner(self.init,horizon=3600,centers=4,solve_seconds=.25)
        scores=np.zeros(p.n);env=dict(quality_scale=.68*.95,program_band_quality_scale=.68,duration_safety=1.1)
        started=time.perf_counter();action=p.choose({'now_utc':self.init['survey']['start_utc']},scores,scores,env,[])
        self.assertIn(action['action'],('observe','wait'))
        self.assertLess(time.perf_counter()-started,15.)
        if action['action']=='observe':
            self.assertGreaterEqual(action['duration_seconds'],p.tmin)
            self.assertLessEqual(action['duration_seconds'],p.tmax)
            self.assertEqual(len(action['assignments']),len(set(action['assignments'].values())))
        out={'tests':'public synthetic/master/adapter','first_action':action,'stats':p.stats,
             'frozen_quality':env,'future_truth_used':False}
        dest=BASE/'results/rolling_coverage_unit';dest.mkdir(parents=True,exist_ok=True)
        (dest/'result.json').write_text(json.dumps(out,indent=2)+'\n')


if __name__=='__main__':unittest.main()
