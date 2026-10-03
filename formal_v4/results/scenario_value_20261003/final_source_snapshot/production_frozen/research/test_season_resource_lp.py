"""Small exact resource cases and public visibility checks."""
import copy
from datetime import timedelta
from pathlib import Path
import unittest

import numpy as np

from global_lp_pilot import public_initialization
from season_resource_lp import solve,visible_seconds
from spatial_candidates import SpatialPlanner,local_sidereal,parse_utc


class ResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.init,_=public_initialization(Path(__file__).resolve().parents[1]/'upstream/gosim-observer-examples/local-cards/L1')

    def toy(self,first_cap=.5):
        init=copy.deepcopy(self.init);start=parse_utc(init['survey']['start_utc']);end=start+timedelta(seconds=60)
        init['survey']['nights']=copy.deepcopy(init['survey']['nights'][:1])
        init['survey']['nights'][0]['observing_end_utc']=end.isoformat();init['survey']['end_utc']=end.isoformat()
        init['instrument'].update(n_fibers=1,grid_side=1,fov_side_deg=init['instrument']['pitch_deg'])
        init['instrument']['exposure'].update(min_duration_seconds=60,max_duration_seconds=60)
        col={c:k for k,c in enumerate(init['targets']['columns'])};rows=copy.deepcopy(init['targets']['rows'][:2])
        for i,r in enumerate(rows):
            r[col['ra_deg']]=local_sidereal(start,float(init['site']['longitude_deg']))
            r[col['dec_deg']]=float(init['site']['latitude_deg']);r[col['science_weight']]=1.
            r[col['required']]=i==0;r[col['feature_flux']]=([first_cap,.25][i])*450/(60*.95)
        init['targets']['rows']=rows
        return init

    def test_shared_time_and_single_exposure_cap(self):
        r,prices,nights=solve(self.toy())
        self.assertAlmostEqual(r['science_plus_required_relaxed_bound_or_surrogate'],.6,places=7)
        self.assertAlmostEqual(r['science_relaxed_total'],.6,places=7)
        self.assertGreater(r['night_positive_price_count'],0)
        self.assertLessEqual(nights[0]['allocated_fiber_seconds'],60+1e-7)
        self.assertTrue(all(0<=v['science_price_per_score']<=1+1e-8 for v in prices.values()))

    def test_below_single_exposure_threshold_cannot_accumulate_required(self):
        r,_,_=solve(self.toy(.49))
        self.assertEqual(r['required_unreachable_in_frozen_single_exposure'],1)
        self.assertAlmostEqual(r['required_avoided_penalty_relaxed'],0,places=7)
        self.assertAlmostEqual(r['science_relaxed_total'],.49*1.2,places=7)

    def test_history_science_floor_retained(self):
        r,_,_=solve(self.toy(),scores=np.array([0.,.3]))
        self.assertAlmostEqual(r['science_current'],.3,places=7)
        self.assertAlmostEqual(r['science_relaxed_total'],.9,places=7)

    def test_analytic_visibility_matches_fine_public_geometry(self):
        init=copy.deepcopy(self.init);init['targets']['rows']=init['targets']['rows'][::500]
        p=SpatialPlanner(init);start,end=p.nights[0];exact=visible_seconds(p,start,end)
        step=30;counts=np.zeros(p.n)
        for second in np.arange(step/2,(end-start).total_seconds(),step):
            alt=p._altaz(local_sidereal(start+timedelta(seconds=float(second)),p.lon))[0]
            counts+=(alt>=p.min_alt)*step
        np.testing.assert_allclose(exact,counts,rtol=0,atol=step+1e-7)


if __name__=='__main__':unittest.main()
