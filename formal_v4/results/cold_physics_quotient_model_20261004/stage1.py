#!/usr/bin/env python3
"""Independent synthetic mechanics only; no model fitting or formal season."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OFFICIAL = REPO/'upstream/gosim-observer-examples/runner'
sys.path.insert(0, str(OFFICIAL))
from challenge.v4_scorer import (WeatherTruth, SlotTruth, score_target_exposure,
    program_band, program_multiplier, lunar_quality_factor)
from challenge.v4_fiber_map import radec_to_altaz, altaz_to_radec
from continuous_posterior import ContinuousPosterior, PublicHit
from quotient_mixture import lognormal_gain

SCORING = dict(q0=.68, flux_zero_point=.5, exposure_zero_point_seconds=900,
    airmass_exponent=.6,
    lunar_model=dict(angular_decay_scale_deg=35., altitude_exponent=1.2,
                     maximum_penalty=.7),
    program=dict(bands=dict(DARK=.65, BRIGHT=.4),
                 multipliers=dict(DARK=1.2, BRIGHT=1.12, BACKUP=1.06),
                 mismatch_multiplier=1.))
SITE = dict(latitude_deg=35., longitude_deg=135.)
START = datetime(2026, 10, 4, 15, 0, tzinfo=timezone.utc)


def slot(c, efficiency, opened=True):
    return SlotTruth('SYNTHETIC-N1-S1', START, START+timedelta(seconds=900),
                     opened, 1., SCORING['q0']*c, 1., efficiency)


def target(k, altitude, azimuth, flux, weight):
    ra, dec = altaz_to_radec(altitude, azimuth, START,
                           SITE['latitude_deg'], SITE['longitude_deg'])
    return dict(target_id=f'SYNTHETIC-T{k:02}', ra_deg=ra, dec_deg=dec,
                feature_flux=flux, science_weight=weight)


def altaz(t, moment):
    return radec_to_altaz(t['ra_deg'], t['dec_deg'], moment,
                         SITE['latitude_deg'], SITE['longitude_deg'])


def hbar(t, seconds):
    unit = WeatherTruth([slot(1., 1.)], None)
    return unit.band_quality(START, START+timedelta(seconds=seconds), SCORING,
        lambda moment: altaz(t, moment)[0],
        lambda moment: lunar_quality_factor(t['ra_deg'], t['dec_deg'],
                                            moment, SITE, SCORING))


def official_score(t, seconds, c, efficiency, declared='BRIGHT', opened=True):
    weather = WeatherTruth([slot(c, efficiency, opened)], None)
    end = START+timedelta(seconds=seconds)
    band_q = weather.band_quality(START, end, SCORING,
        lambda moment: altaz(t, moment)[0],
        lambda moment: lunar_quality_factor(t['ra_deg'], t['dec_deg'],
                                            moment, SITE, SCORING))
    m = program_multiplier(declared, program_band(band_q, SCORING), SCORING)
    scored = score_target_exposure(t, list(weather.segments(START, end)), [],
        weather, seconds, m, SCORING, START, lambda moment: altaz(t, moment), SITE)
    return scored, band_q


def hit(t, seconds, c, e, declared='BRIGHT', opened=True):
    scored, _ = official_score(t, seconds, c, e, declared, opened)
    # This is the exact actor projection; neither factor nor band is passed.
    return PublicHit(round(scored.score, 6), t['science_weight'], t['feature_flux'],
                     seconds, hbar(t, seconds), declared)


def midpoint_gain(posterior, query, nc=800, nz=96):
    """Independent direct positive-part quadrature on the continuous density."""
    weight, flux, seconds, h, declared, best = query
    scale = posterior.scale(flux, seconds, h)
    mass = val = 0.
    for cell in posterior.cells:
        c_cuts = sorted({cell.c_lo, cell.c_hi, *(x for x in posterior.band_cuts(h)
                            if cell.c_lo < x < cell.c_hi)})
        for ca, cb in zip(c_cuts, c_cuts[1:]):
            dc = (cb-ca)/nc
            for ci in range(nc):
                c = ca+(ci+.5)*dc
                za = max(cell.z_lo, posterior.e_lo*c)
                zb = min(cell.z_hi, posterior.e_hi*c)
                if zb <= za:
                    continue
                factor = dc*(zb-za)/c
                mass += factor
                m = posterior.multiplier(declared, posterior.band(c*h))
                z_values = (za+(zi+.5)*(zb-za)/nz for zi in range(nz))
                val += factor*sum(max(weight*m*min(scale*z, 1.)-best, 0.)
                                  for z in z_values)/nz
    return posterior.open_density*val/posterior.normalizer


def main():
    rng = random.Random(970401)
    tests = {}
    # New toy states, generated here. No old truth/world/dataset is loaded.
    targets = [target(k, 48.+2*k, 37.+17*k,
                      [.06,.17,.48,1.6][k%4], .7+.075*k) for k in range(16)]
    official_err = 0.
    quotient_err = 0.
    saturated = 0
    for _ in range(50):
        c, e = rng.uniform(.05,1.7), rng.uniform(.12,.98)
        seconds = rng.randint(60,850)
        for t in targets:
            h = hbar(t, seconds)
            scored, bq = official_score(t, seconds, c, e)
            m = program_multiplier('BRIGHT', program_band(c*h, SCORING), SCORING)
            predicted_factor = min(t['feature_flux']*seconds*h*c*e/450., 1.)
            official_err = max(official_err, abs(scored.score-
                                t['science_weight']*m*predicted_factor), abs(bq-c*h))
            quotient_err = max(quotient_err, abs(scored.quality/h-c*e))
            saturated += scored.factor == 1.
    assert official_err < 4e-14 and quotient_err < 4e-14
    tests['official_800_target_checks'] = dict(max_score_or_band_error=official_err,
        max_quality_quotient_error=quotient_err, saturated_examples=saturated)

    # Truth is only used by the mechanical judge to verify posterior containment.
    c_true, e_true, seconds = .74, .62, 600
    hits = [hit(t, seconds, c_true, e_true) for t in targets]
    posterior = ContinuousPosterior(SCORING, hits)
    assert posterior.contains(c_true, e_true)
    assert len(posterior.cells) <= 2*len(hits)+1
    tests['joint_quantized_likelihood'] = posterior.public_receipt()

    # Duplicating one deterministic score is the same event in the shared latent
    # state, not sixteen independent measurement noise likelihood factors.
    single = ContinuousPosterior(SCORING, [hits[0]])
    repeated = ContinuousPosterior(SCORING, [hits[0]]*16)
    assert single.public_receipt() == repeated.public_receipt()
    tests['same_exposure_duplicate_invariance'] = True

    # A saturated score gives a Z lower bound and no finite inverse upper bound.
    sat_target = target(99, 84., 24., 5., 1.3)
    sat_hit = hit(sat_target, seconds, c_true, e_true)
    sat_post = ContinuousPosterior(SCORING, [sat_hit])
    assert sat_post.contains(c_true, e_true)
    assert any(math.isinf(cell.z_hi) for cell in sat_post.cells)
    tests['saturation_is_one_sided'] = sat_post.public_receipt()

    zero_hits = [hit(t, seconds, c_true, e_true, opened=False) for t in targets]
    zero = ContinuousPosterior(SCORING, zero_hits)
    assert zero.closed_mass/zero.normalizer == 1.
    tests['hit_zero_supports_closed_atom'] = True
    # A geometric miss is omitted from hits; it cannot supply weather-zero data.
    empty = ContinuousPosterior(SCORING, [])
    assert abs(empty.normalizer-1.) < 5e-14
    assert abs(empty.closed_mass/empty.normalizer-.08) < 5e-14
    tests['empty_hit_list_preserves_prior_not_closed_certainty'] = True

    # This deliberately violates the restricted no-directional model. Retain the
    # resulting zero-support failure as an expected refusal, never force a fit.
    bad = [PublicHit(0., h.weight, h.flux, h.seconds, h.geometric_h, h.declared)
           if k == 0 else h for k,h in enumerate(hits)]
    try:
        ContinuousPosterior(SCORING, bad)
    except ValueError as ex:
        tests['mixed_zero_positive_rejected_in_restricted_scope'] = str(ex)
    else:
        raise AssertionError('restricted zero-support case silently accepted')

    query = (1.15, .58, 550., hbar(targets[8], 550), 'DARK', .37)
    expected = posterior.expected_gain(*query)
    quadrature = midpoint_gain(posterior, query)
    assert abs(expected-quadrature) < 3e-7
    tests['continuous_expected_hinge_vs_direct_quadrature'] = dict(
        analytic=expected, direct_density_midpoint=quadrature,
        absolute_error=abs(expected-quadrature))

    max_inv_err = 0.
    for _ in range(250):
        w, flux, duration, h = (rng.uniform(.1,2.),rng.uniform(.01,3.),
                               rng.uniform(30.,850.),rng.uniform(.25,1.))
        b = rng.uniform(0.,2.)
        prog = rng.choice(['DARK','BRIGHT','BACKUP'])
        g = posterior.expected_gain(w,flux,duration,h,prog,b)
        larger_b = posterior.expected_gain(w,flux,duration,h,prog,b+.03)
        larger_flux = posterior.expected_gain(w,flux*1.1,duration,h,prog,b)
        scaled = posterior.expected_gain(w*2.3,flux,duration,h,prog,b*2.3)
        max_inv_err = max(max_inv_err, abs(scaled-2.3*g))
        assert larger_b <= g+2e-12 and larger_flux >= g-2e-12
        assert g-larger_b <= .03+2e-12
        bm = posterior.expected_gain(w,flux,duration,h,prog,b+.015)
        assert bm <= (g+larger_b)/2+2e-12, dict(
            query=(w,flux,duration,h,prog,b), gain=g, middle=bm,
            larger_best=larger_b, convex_gap=bm-(g+larger_b)/2)
    assert max_inv_err < 2e-11
    tests['250_fixed_history_gain_invariants'] = dict(
        decreasing_convex_one_lipschitz_in_best=True,
        monotone_in_future_flux=True,
        joint_weight_best_homogeneity_error=max_inv_err)

    # A direct expectation changes a feasible single-fiber query even when the
    # mean contribution and current best coincide. No future schedule is solved.
    random_scores = [0.,4.]
    gain = statistics.mean(max(s-2.,0.) for s in random_scores)
    plug = max(statistics.mean(random_scores)-2.,0.)
    assert gain == 1. and plug == 0.
    tests['mean_before_best_counterexample'] = dict(expected_positive_part=gain,
                                                 positive_part_of_mean=plug)

    # Independently integrate in the underlying standard-normal coordinate. This
    # exercises a future continuous NN head's kernel without fitting a network.
    ln_error=0.
    for mu,sigma,scale,best in [(-.8,.4,.8,.25),(.2,.7,1.3,.8),
                               (-1.1,1.2,3.,0.),(.9,.2,.04,.2)]:
        w,m=1.3,1.12
        exact=lognormal_gain(w,m,scale,best,mu,sigma)
        dx=18/30000
        direct=sum(max(w*m*min(scale*math.exp(mu+sigma*(-9+(k+.5)*dx)),1.)-best,0.)*
                   math.exp(-.5*(-9+(k+.5)*dx)**2)/math.sqrt(2*math.pi)*dx
                   for k in range(30000))
        ln_error=max(ln_error,abs(exact-direct))
    assert ln_error < 2e-7
    tests['unfitted_lognormal_kernel_vs_normal_quadrature']=dict(
        cases=4, max_absolute_error=ln_error)

    # Mechanism prototype timing only. This host is not a 2CPU/2GiB actor container.
    update_times, score_times = [], []
    q = [(1.+j/100,.03+j/20,60.+j*20,.35+j/100,
          ['DARK','BRIGHT','BACKUP'][j%3], j/60) for j in range(32)]
    for _ in range(30):
        tic=time.perf_counter()
        p=ContinuousPosterior(SCORING,hits)
        update_times.append(time.perf_counter()-tic)
        tic=time.perf_counter()
        values=[p.expected_gain(*args) for args in q]
        score_times.append(time.perf_counter()-tic)
        assert all(math.isfinite(x) for x in values)
    tests['local_unrestricted_prototype_cost'] = dict(
        update_16hits_median_seconds=statistics.median(update_times),
        score_32queries_median_seconds=statistics.median(score_times),
        measured_actor_2cpu_2gib_cost=False,
        python=sys.version, platform=sys.platform)
    names=['v4_scorer.py','v4_fiber_map.py','v4_runner.py','v4_workflow.py',
           'tile_geometry_simulator.py']
    source_hashes={str(OFFICIAL/'challenge'/n):hashlib.sha256(
        (OFFICIAL/'challenge'/n).read_bytes()).hexdigest() for n in names}
    weather=REPO/'results/cold_public_opportunity_cost_20261004/official/challenge/v4_weather_simulator.py'
    source_hashes[str(weather)]=hashlib.sha256(weather.read_bytes()).hexdigest()
    assert source_hashes[str(weather)] == 'b4675ead09e8cf333c12841ac051786c523394d4fb3cfb0b52397ad75dcc753a'
    result=dict(status='PASS_RESTRICTED_MECHANICS_ONLY', seed=970401,
        no_fitting=True, no_formal_season=True, no_old_teacher_or_truth=True,
        scope='one slot; constant C/E; no directional event; explicit toy prior',
        tests=tests, read_source_sha256=source_hashes)
    (HERE/'STAGE1_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        (HERE/f'FAILED_STAGE1_{stamp}.txt').write_text(traceback.format_exc())
        raise
