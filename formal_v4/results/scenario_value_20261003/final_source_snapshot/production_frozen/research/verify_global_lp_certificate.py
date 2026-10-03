#!/usr/bin/env python3
"""Independent exact-rational verification of the saved finite-pool LP dual.

This verifies a numerical candidate master, not geometry completeness, quality
forecasts, the whole legal action universe, or real stochastic competition UB.
"""
import argparse
from fractions import Fraction
import json
from pathlib import Path


def verify(directory):
    result=json.loads((directory/'result.json').read_text())
    candidates=json.loads((directory/'candidates.json').read_text())
    by_target=json.loads((directory/'target_shadow_prices.json').read_text())
    times=json.loads((directory/'time_shadow_prices.json').read_text())
    layers={}
    for entries in by_target.values():
        for entry in entries:
            w,a=Fraction(entry['layer_weight_exact']),Fraction(entry['shadow_exact'])
            assert 0 <= a <= w
            layers[entry['layer_index']]={**entry,'w':w,'a':a}
    assert sorted(layers)==list(range(result['model_size']['coverage_layers']))
    beta=[Fraction(t['shadow_exact']) for t in times]
    assert all(b >= 0 for b in beta)
    gaps=[]
    for c in candidates:
        scores=dict(zip(c['targets'],c['scores']));factors=dict(zip(c['targets'],c['factors']))
        value=Fraction(0)
        for layer in layers.values():
            i=layer['target_index']
            if i not in scores:continue
            cover=(scores[i] >= layer['score_threshold']) if layer['kind']=='science' else factors[i] >= layer['factor_threshold']
            if cover:value+=layer['a']
        occupied=[k for k,t in enumerate(times) if c['start'] <= t['midpoint_seconds'] < c['end']]
        assert occupied
        cost=sum((beta[k] for k in occupied),Fraction(0));gaps.append(value-cost)
        assert value <= cost
    bound=sum(beta,Fraction(0))+sum((l['w']-l['a'] for l in layers.values()),Fraction(0))
    assert bound==Fraction(result['lp_utility_upper_exact_certificate'])
    return {'verified':True,'columns_checked':len(candidates),'layers_checked':len(layers),
        'all_layer_and_time_nonnegative':True,'max_reduced_profit_exact':str(max(gaps)),
        'bound_exact':str(bound),'bound_float':float(bound),
        'scope':'specified finite numerical candidate master only; no completeness/real-future certificate'}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('directory',type=Path);args=ap.parse_args()
    result=verify(args.directory);(args.directory/'certificate_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
