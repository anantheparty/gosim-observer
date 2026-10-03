#!/usr/bin/env python3
"""Check complete sphere cover and arbitrary-start contiguous exposure caps."""
from pathlib import Path
import sys,json,math,hashlib
import numpy as np
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'upstream/gosim-observer-examples/runner'))
from challenge.v4_runner import load_scenario
OUT=BASE/'results/cold_probabilistic_model_20261003/spatial_support'
RESOURCE=BASE/'results/cold_probabilistic_model_20261003/resource_graph'

def main():
    rng=np.random.default_rng(600103);verified={}
    for card in ('L1','L2'):
        report=json.loads((OUT/f'{card}_summary.json').read_text());cover=report['full_sphere_cover']
        ra=np.r_[rng.uniform(0,360,10000),0.,360-1e-12,1e-12,180.,90.]
        dec=np.r_[np.degrees(np.arcsin(rng.uniform(-1,1,10000))),-90.,90.,89.999999999,-89.999999999,0.]
        cra=(np.floor(ra/cover['longitude_step_deg'])+.5)*cover['longitude_step_deg']
        cdec=-90+(np.minimum(cover['latitude_cells']-1,np.floor((dec+90)/cover['latitude_step_deg']))+.5)*cover['latitude_step_deg']
        cosine=np.sin(np.radians(dec))*np.sin(np.radians(cdec))+np.cos(np.radians(dec))*np.cos(np.radians(cdec))*np.cos(np.radians(ra-cra))
        distance=np.degrees(np.arccos(np.clip(cosine,-1,1)))
        assert distance.max()<=cover['maximum_cover_radius_deg']+1e-9
        data=np.load(RESOURCE/f'{card}_dual_certificate.npz');caps=np.load(OUT/f'{card}_single_exposure_caps.npz')['contiguous_four_slot_factor_cap']
        slots=json.loads((RESOURCE/f'{card}_slot_prices.json').read_text());original=np.array([s['original_slot_index'] for s in slots])
        sc=load_scenario(BASE/f'upstream/gosim-observer-examples/local-cards/{card}/config/v4_scenario.json')
        matrix=np.zeros((len(sc.slots),len(sc.targets)));matrix[original[data['slot_index']],data['target_index']]=data['edge_factor_per_900s_upper']
        nights={}
        for t,s in enumerate(sc.slots):nights.setdefault(s.slot_id.split('-S')[0],[]).append(t)
        groups=list(nights.values());maxviolation=0.;cross=0;partial=0
        for draw in range(4096):
            rows=groups[int(rng.integers(len(groups)))];ti=int(rng.integers(len(sc.targets)));start=int(rng.integers(len(rows)*900));duration=int(rng.integers(1,3601));end=min(start+duration,len(rows)*900)
            dose=0.
            for j in range(start//900,(end-1)//900+1):
                sec=max(0,min(end,(j+1)*900)-max(start,j*900));dose+=sec/900*matrix[rows[j],ti]
            violation=min(1.,dose)-caps[ti];maxviolation=max(maxviolation,violation)
            assert violation<1e-8,(card,draw,start,end,ti,dose,caps[ti])
            cross+=(start//900!=(end-1)//900);partial+=start%900!=0
        source=BASE/'research/cold_probabilistic_spatial_support.py'
        assert hashlib.sha256(source.read_bytes()).hexdigest()==report['source_sha256']
        verified[card]={'sphere_cover_sample_points':len(ra),'max_sampled_cover_distance_deg':float(distance.max()),'cover_radius_deg':cover['maximum_cover_radius_deg'],'pole_and_ra_seam_cases_included':True,'arbitrary_integer_start_windows_checked':4096,'cross_slot_windows':int(cross),'partial_slot_starts':int(partial),'max_contiguous_window_cap_violation':maxviolation,'source_sha256_matches':True,'new_total_upper':report['contiguous_single_exposure_domain']['bound_after_contiguous_domain'],'scope':'Exact coverage/step-integral arguments establish the model; finite samples check numeric implementation. These are not strategy season scores.'}
        print(card,json.dumps(verified[card]),flush=True)
    (OUT/'certificate_verification.json').write_text(json.dumps(verified,indent=2)+'\n')
if __name__=='__main__':main()
