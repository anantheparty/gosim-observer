"""Conservative angular-error bound for six-decimal public footprint phases.

Uses spherical triangle inequality, analytic centre derivatives and the DFT
triangle inequality. No seed, hidden truth or stochastic error assumption.
"""
from __future__ import annotations

import argparse,csv,json,math
from pathlib import Path
import numpy as np


def bounds(path):
    groups = {}
    for row in csv.DictReader(Path(path).open()):groups.setdefault(row['component_id'],[]).append(row)
    epsilon = math.radians(.5e-6)
    records = []
    for component,data in sorted(groups.items()):
        data.sort(key=lambda row:int(row['vertex_index']))
        ra = np.deg2rad(np.array([float(row['ra_deg']) for row in data]))
        dec = np.deg2rad(np.array([float(row['dec_deg']) for row in data]))
        if len(data)%4:raise ValueError('need quarter-turn vertex')
        quarter = len(data)//4
        a = abs((ra[quarter]-ra[0]+math.pi)%(2*math.pi)-math.pi)
        amin,amax = max(0,a-2*epsilon),a+2*epsilon
        dmin,dmax = max(0,abs(dec[quarter])-epsilon),abs(dec[quarter])+epsilon
        if amax>=math.pi/2 or dmax>=math.pi/2:raise ValueError('centre branch bound not valid')
        denominator = 1-math.sin(amax)**2*math.cos(dmin)**2
        product = .5 if dmin<=math.pi/4<=dmax else max(math.sin(2*dmin),math.sin(2*dmax))/2
        centre_dec_error = epsilon*math.cos(amin)/denominator+2*epsilon*product*math.sin(amax)/denominator
        centre_dec = math.atan(math.tan(dec[quarter])/math.cos(a))
        centre_error = centre_dec_error+epsilon*math.cos(max(0,abs(centre_dec)-centre_dec_error))
        point_errors = epsilon*(1+np.cos(np.maximum(0,np.abs(dec)-epsilon)))
        # Extra guard is far above double-precision geometry/FFT roundoff here.
        coefficient_error = centre_error+float(point_errors.mean())+1e-11
        dot = np.sin(dec)*math.sin(centre_dec)+np.cos(dec)*math.cos(centre_dec)*np.cos(ra-ra[0])
        radii = np.arccos(np.clip(dot,-1,1))
        coefficients = np.fft.rfft(radii)/len(data)
        angles = [math.asin(min(1,coefficient_error/abs(value))) for value in coefficients[1:4]]
        records.append({'component':component,'coefficient_error_bound_rad':coefficient_error,
                        'phase_error_bounds_rad':angles})
    return records


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cards',default='formal_v4/practice_cards')
    parser.add_argument('--out',default='formal_v4/research/phase_rounding_bound_result.json')
    args=parser.parse_args()
    result={'coordinate_rounding_degrees':.5e-6,'numerical_guard_rad':1e-11,
            'cards':{name:bounds(Path(args.cards)/name/name/'public/footprint.csv')
                     for name in ('alpha','beta','gamma','delta')}}
    result['max_phase_error_bound_rad']=max(max(row['phase_error_bounds_rad'])
                                         for rows in result['cards'].values() for row in rows)
    result['within_scan_tolerance']=result['max_phase_error_bound_rad']<1e-4
    Path(args.out).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'max_phase_error_bound_rad':result['max_phase_error_bound_rad'],
                      'within_scan_tolerance':result['within_scan_tolerance']}))
