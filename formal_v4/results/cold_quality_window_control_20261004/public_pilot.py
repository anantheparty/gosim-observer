"""Whole public-catalog Bellman tensor/capacity pilot. Never reads future truth.

The declared weather PMF is deliberately uncalibrated and must not be used as
an actor-quality claim. One target service per night, public geometry maximized
over three starts, is a finite relaxation/surrogate, not a legal season planner.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, math, os, sys, time, resource
from datetime import timedelta
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'formal_v4/results/request_geometry_integration_20261004/control_package'))
from research.spatial_candidates import SpatialPlanner, local_sidereal, parse_utc, DEG
from window_control import OutcomeModel, priced_iterations


def public_initial(card):
    base = ROOT/'formal_v4/practice_cards'/card/card
    paths = [base/'public/targets.csv', base/'public/v4_night_calendar.csv',
             base/'config/v4_score_config.json', base/'config/v4_fiber_config.json']
    with paths[0].open() as f:
        reader = csv.DictReader(f); columns = reader.fieldnames; rows = list(reader)
    with paths[1].open() as f:
        nights = list(csv.DictReader(f))
    scoring, fiber = (json.loads(path.read_text()) for path in paths[2:])
    instrument = {**fiber['field'], 'exposure': fiber['exposure']}
    return dict(site={**fiber['site'], 'minimum_altitude_deg': 30.}, scoring=scoring,
                instrument=instrument, targets=dict(columns=columns,
                    rows=[[row[k] for k in columns] for row in rows]),
                survey=dict(nights=nights)), paths


def min_alt_vector(planner, start, duration):
    ls0 = local_sidereal(start, planner.lon)
    ls1 = local_sidereal(start+timedelta(seconds=int(duration)), planner.lon)
    a0 = planner._altaz(ls0)[0]; a1 = planner._altaz(ls1)[0]
    minimum = np.minimum(a0, a1)
    ha = (ls0-planner.ra) % 360
    sweeps_lower = (180-ha) % 360 <= duration*360.98564736629/86400
    lower_sin = planner.sin_lat*planner.sin_dec-planner.cos_lat*planner.cos_dec
    minimum[sweeps_lower] = np.minimum(minimum[sweeps_lower],
        np.arcsin(np.clip(lower_sin[sweeps_lower], -1, 1))/DEG)
    return minimum


def integrated_public(planner, start, duration):
    result = np.zeros(planner.n)
    left = 0
    while left < duration:
        right = min(duration, left+120)
        t = start+timedelta(seconds=(left+right)/2)
        lst = local_sidereal(t, planner.lon)
        alt = planner._altaz(lst)[0]
        result += (right-left)*planner._public_quality(t, lst, alt)
        left = right
    result /= duration
    result[min_alt_vector(planner, start, duration) < planner.min_alt] = 0
    return result


def build_model(planner):
    durations = np.array([900, 1800, 3600], dtype=int)
    w, n = len(planner.nights), planner.n
    geometry = np.zeros((w, len(durations), n), np.float32)
    for k, (start, end) in enumerate(planner.nights):
        for j, duration in enumerate(durations):
            slack = (end-start).total_seconds()-duration
            if slack < 0:
                continue
            for fraction in (0., .5, 1.):
                moment = start+timedelta(seconds=slack*fraction)
                geometry[k, j] = np.maximum(geometry[k, j],
                    integrated_public(planner, moment, int(duration)))
    # Site transparency*sky/seeing and instrument efficiency are distinct.
    # Fixed per-night regimes are shared across duration/program alternatives.
    weather = np.array([.38, .60, .86], dtype=float)
    efficiency = np.array([.95, .95, .95], dtype=float)
    probabilities = np.broadcast_to([.25, .5, .25], (w, 3)).copy()
    c = np.zeros((w, 9, 3, n), np.float32)
    g = np.zeros_like(c)
    dd = np.zeros((w, 9), dtype=float)
    for j, duration in enumerate(durations):
        band_q = geometry[:, j, None, :] * weather[None, :, None]
        factor = np.minimum(1, planner.flux[None, None, :] * duration * band_q *
                            efficiency[None, :, None] / planner.f0t0)
        band = np.where(band_q >= planner.dark_threshold, 0,
                        np.where(band_q >= planner.bright_threshold, 1, 2))
        for p in range(3):
            action = 3*j+p
            g[:, action] = factor
            c[:, action] = factor*np.where(band == p, planner.multipliers[p], planner.mismatch)
            dd[:, action] = duration
    model = OutcomeModel(c, g, probabilities, dd, planner.weight,
                         planner.required.astype(float)*planner.req_penalty,
                         planner.req_threshold)
    return model, geometry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--card', default='delta', choices=('alpha','beta','gamma','delta'))
    parser.add_argument('--iterations', type=int, default=3)
    args = parser.parse_args()
    started = time.perf_counter()
    initial, paths = public_initial(args.card)
    planner = SpatialPlanner(initial)
    model, geometry = build_model(planner)
    built = time.perf_counter()
    capacity = np.array([(end-start).total_seconds()*planner.nfib for start,end in planner.nights])
    prices, logs = priced_iterations(model, capacity, iterations=args.iterations,
                                     score_bins=13, probability_bins=5)
    elapsed = time.perf_counter()-started
    thresholds = planner.req_threshold*planner.f0t0/(planner.flux*planner.tmax)
    best_h = geometry[:,2].max(0)
    reachable_mass = np.sum(model.probabilities[:, :, None] *
        (model.raw_factor[:,6] >= planner.req_threshold), axis=1)
    rare = (reachable_mass > 0).sum(0)
    summary = dict(card=args.card, catalog_targets=planner.n, nights=len(planner.nights),
        model='one service/target/night; 3 public starts per duration; uncalibrated 3-regime PMF',
        geometry_seconds=built-started, total_seconds=elapsed,
        max_rss_reported=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        max_rss_unit='bytes on Darwin; KiB on Linux',
        tensors=dict(outcome_shape=list(model.normalized_score.shape),
                     state_shape=[planner.n,13,5],
                     outcome_bytes=int(model.normalized_score.nbytes+model.raw_factor.nbytes),
                     policy_bytes=len(planner.nights)*planner.n*13*5,
                     production_suffix_float32_bytes=(len(planner.nights)+1)*planner.n*25*9*4),
        required_count=int(planner.required.sum()),
        required_no_modeled_threshold_nights=int(np.sum(planner.required & (rare == 0))),
        required_at_most_three_modeled_threshold_nights=int(np.sum(planner.required & (rare <= 3))),
        required_positive_modeled_threshold_nights_quantiles=np.quantile(rare[planner.required], [0,.25,.5,.75,1]).tolist(),
        required_quality_hurdle_quantiles=np.quantile(thresholds[planner.required], [0,.25,.5,.75,1]).tolist(),
        retained_price_nonzero=int(np.count_nonzero(prices)), iterations=logs,
        public_sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        forbidden_inputs_read=[], deployed=False, full_season_run=False)
    target_rows = [dict(target_id=planner.ids[i], required=bool(planner.required[i]),
                        flux=float(planner.flux[i]), weight=float(planner.weight[i]),
                        required_quality_3600=float(thresholds[i]),
                        max_public_geometric_quality=float(best_h[i]),
                        modeled_threshold_nights=int(rare[i]),
                        modeled_threshold_night_mass=float(reachable_mass[:,i].sum()))
                   for i in range(planner.n)]
    out=Path(__file__).parent
    (out/f'{args.card}_public_pilot.json').write_text(json.dumps(summary,indent=2)+'\n')
    with (out/f'{args.card}_public_targets.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=list(target_rows[0])); writer.writeheader();writer.writerows(target_rows)
    print(json.dumps({k:v for k,v in summary.items() if k not in ('iterations','public_sources')}, indent=2))
    print(json.dumps({'dual_iterations':logs},indent=2))

if __name__ == '__main__':
    main()
