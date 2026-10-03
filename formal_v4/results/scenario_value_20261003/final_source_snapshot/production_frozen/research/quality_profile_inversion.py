"""Post-run quality integral inversion from public catalog and our own outputs.

This module never opens a weather/events/stress truth product. Bounds use explicit
reference-generator geometry domains; they are conditional, not a recovered truth
certificate for an undisclosed generation configuration. No production import.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import time
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile

import numpy as np

from required_opportunity_model import RequiredOpportunityModel, public_initial, parse, stamp
from terrain_version_space import DIRECTIONS, trajectory_envelope

ROUNDING_RADIUS = 0.5e-6
GEOMETRY_GUARD = 1e-9
REFERENCE_Z_CAP = 3.0  # E<=1, tau<=1, sky<=1.5, seeing>=.5.


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def all_target_model(card):
    initial = public_initial(card)
    column = initial['targets']['columns'].index('required')
    for row in initial['targets']['rows']:
        row[column] = True
    return RequiredOpportunityModel(initial)


def load_messages(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def read_output(path,name):
    """Read only canonical participant outputs, including a downloaded ZIP."""
    path=Path(path)
    if name not in ('score_report.json','messages.jsonl','decisions.csv','observations.csv'):
        raise ValueError('only canonical public outputs may be compared')
    if path.is_dir():return (path/name).read_text()
    with ZipFile(path) as z:
        matches=[n for n in z.namelist() if not n.endswith('/') and Path(n).name==name]
        if len(matches)!=1:raise ValueError('public output missing or duplicate')
        return z.read(matches[0]).decode('utf-8').replace('\r\n','\n')


class PublicQualityMatrix:
    """A[row,cell] for the official <=120s midpoint integration.

    Cell boundaries are published 900s slots plus our successful repair times.
    Repairs cannot occur inside our own observe action; coefficients retain the
    original slot-based midpoint subdivision rather than resampling at a repair.
    Generated directional event boundaries are also slot-aligned. An arbitrary
    custom event with an unpublished intra-slot cut would require a new model.
    """
    def __init__(self, model, repairs=()):
        self.model = model
        self.repairs = np.sort(np.asarray(list(repairs), dtype=float))
        cells = []
        slots = []
        for night, (a, b) in enumerate(model.nights):
            for slot_number, left in enumerate(np.arange(a, b, model.slot_seconds)):
                right = min(b, left + model.slot_seconds)
                cuts = np.r_[left, self.repairs[(self.repairs > left) & (self.repairs < right)], right]
                slot = len(slots)
                slots.append((night, slot_number, left, right))
                cells.extend((night, slot, float(x), float(y)) for x, y in zip(cuts[:-1], cuts[1:]))
        self.cells = cells
        self.slots = slots
        self.starts = np.array([c[2] for c in cells])
        self.ends = np.array([c[3] for c in cells])
        self.night_ends = np.array([b for a, b in model.nights])

    def overlaps(self, start, duration):
        end = start + duration
        night = int(np.searchsorted(self.night_ends, start, side='right'))
        if night >= len(self.model.nights):
            raise ValueError('observe begins outside public nights')
        a, b = self.model.nights[night]
        if start < a - 1e-7 or end > b + 1e-7 or duration <= 0:
            raise ValueError('actual observe duration does not fit public night')
        slot = int((start-a)//self.model.slot_seconds)
        out = []
        cursor = start
        while cursor < end - 1e-7:
            right = min(end, b, a + (slot + 1) * self.model.slot_seconds)
            out.append((cursor, right, a + slot * self.model.slot_seconds))
            cursor = right
            slot += 1
        return out

    def coefficients(self, start, duration, indices):
        """Return (cell_indices, coefficients[target,cell]) for one action."""
        samples, widths = [], []
        for left, right, slot_start in self.overlaps(start, duration):
            piece = left
            while piece < right - 1e-7:
                piece_end = min(right, piece + 120)
                samples.append((piece + piece_end) / 2)
                widths.append(piece_end - piece)
                piece = piece_end
        samples, widths = np.asarray(samples), np.asarray(widths)
        cell_idx = np.searchsorted(self.starts, samples, side='right') - 1
        if np.any(samples >= self.ends[cell_idx] + 1e-7):
            raise ValueError('sample outside cell')
        cells = np.unique(cell_idx)
        h = self.model.public_quality(samples, indices) * widths[:, None] / duration
        coeff = np.stack([h[cell_idx == c].sum(axis=0) for c in cells], axis=1)
        return cells, coeff


def sector_certainly_clear(track, direction, max_width, max_altitude):
    """All positions avoid every sector consistent with a coarse compass notice."""
    if track['alt_min'] > max_altitude:
        return True
    if direction not in DIRECTIONS:
        return False
    distance = np.abs((track['az_samples'] - DIRECTIONS[direction] + 180) % 360 - 180)
    return bool(np.all(distance - track['az_radii'] > 22.5 + max_width / 2 + 1e-7))


class ReferenceClearFilter:
    """Conditional clean-row test using published reference width/height ranges.

    Initial terrain notices persist. Each timed bulletin covers its slot only.
    ALL effects already belong to Z. Missing bulletins are only safe if the whole
    trajectory is above the largest reference directional altitude (80 degrees).
    """
    def __init__(self, model, messages):
        self.model = model
        self.bulletins = {parse(m['issued_at_utc']).timestamp(): m for m in messages
                          if m.get('record_type') == 'bulletin'}
        initial = [m for m in messages if m.get('record_type') == 'bulletin' and m.get('initial')]
        self.terrain_known = bool(initial)
        self.terrain = list(dict.fromkeys(n['direction'] for m in initial for n in m.get('notices', [])
                                         if n.get('event_kind') == 'terrain_obstruction'))

    def clear(self, index, overlaps):
        m = self.model
        for left, right, slot_start in overlaps:
            track = trajectory_envelope(m.ra[index], m.dec[index], left, right-left, m.latitude, m.longitude)
            if not self.terrain_known and track['alt_min'] <= 50:
                return False
            if any(not sector_certainly_clear(track, d, 70, 50) for d in self.terrain):
                return False
            bulletin = self.bulletins.get(slot_start)
            if bulletin is None:
                if track['alt_min'] <= 80:
                    return False
                continue
            for notice in bulletin.get('notices', []):
                kind, direction = notice.get('event_kind'), notice.get('direction')
                if direction == 'ALL' or kind in ('earthquake', 'terrain_obstruction'):
                    continue
                width, altitude = (80, 60) if kind == 'rocket_launch' else (120, 80)
                if not sector_certainly_clear(track, direction, width, altitude):
                    return False
        return True


def propagate_intervals(row, col, values, quality, n_cells, *, cap=REFERENCE_Z_CAP,
                        max_iterations=300, tolerance=1e-12):
    """Monotone outer interval propagation; not a uniqueness or LP certificate.

    For each positive row coefficient a_ij:
      x_j >= (L_i - sum[k!=j] a_ik upper_k) / a_ij,
      x_j <= (U_i - sum[k!=j] a_ik lower_k) / a_ij.
    Every feasible solution stays in the returned box. Contradictions are explicit.
    """
    row, col, values, quality = map(np.asarray, (row, col, values, quality))
    row, col = row.astype(int), col.astype(int)
    lower, upper = np.zeros(n_cells), np.full(n_cells, float(cap))
    radius = ROUNDING_RADIUS + GEOMETRY_GUARD
    lo, hi = np.maximum(0, quality-radius), quality+radius
    iteration = 0
    for iteration in range(1, max_iterations+1):
        row_lower = np.bincount(row, values*lower[col], minlength=len(quality))
        row_upper = np.bincount(row, values*upper[col], minlength=len(quality))
        candidate_lower = (lo[row] - row_upper[row] + values*upper[col]) / values
        candidate_upper = (hi[row] - row_lower[row] + values*lower[col]) / values
        new_lower, new_upper = lower.copy(), upper.copy()
        np.maximum.at(new_lower, col, candidate_lower)
        np.minimum.at(new_upper, col, candidate_upper)
        if np.any(new_lower > new_upper + tolerance):
            lower, upper = new_lower, new_upper
            break
        delta = max(float(np.max(new_lower-lower)), float(np.max(upper-new_upper))) if n_cells else 0
        lower, upper = new_lower, new_upper
        if delta <= tolerance:
            break
    row_lower = np.bincount(row, values*lower[col], minlength=len(quality))
    row_upper = np.bincount(row, values*upper[col], minlength=len(quality))
    bad_rows = np.flatnonzero((row_lower > hi+1e-12) | (row_upper < lo-1e-12))
    return {'lower':lower, 'upper':upper, 'iterations':iteration,
            'contradictory_cells':np.flatnonzero(lower > upper+1e-12),
            'contradictory_rows':bad_rows,
            'conditional_cap':float(cap), 'rounding_radius':radius}


def fit_nonnegative_profile(row, col, values, quality, n_cells):
    """Uncapped nonnegative least squares on the chosen rows, without AR filling.

    This is one compatible point prediction, not an identified profile. In
    particular, LSMR's choice on an underdetermined system is not weather evidence.
    SciPy is deliberately optional: production agents do not import this module.
    """
    from scipy.sparse import coo_matrix
    from scipy.optimize import lsq_linear
    matrix = coo_matrix((values,(row,col)),shape=(len(quality),n_cells)).tocsr()
    fit = lsq_linear(matrix,quality,bounds=(0,np.inf),tol=1e-11,
                     lsmr_tol=1e-12,max_iter=100,lsmr_maxiter=1000)
    residual = matrix@fit.x-quality
    return {'profile':fit.x,'status':int(fit.status),'success':bool(fit.success),
            'max_abs_residual':float(np.max(np.abs(residual))) if len(residual) else 0.,
            'rms_residual':float(np.sqrt(np.mean(residual**2))) if len(residual) else 0.,
            'residual_over_rounding_radius':int(np.count_nonzero(np.abs(residual)>ROUNDING_RADIUS+GEOMETRY_GUARD)),
            'scope':'uncapped NNLS point estimate on conditional clean geometry rows; unobserved/aliased cells are not identified'}


def pure_cell_holdout(row, col, values, quality, observation_index, n_cells):
    """Hold out whole observe actions; direct one-cell anchors need no solver.

    Nearby fibres from one exposure are never split across train and validation.
    Only validation rows whose every cell has a training one-cell anchor enter.
    No interpolation is used to manufacture a successful validation comparison.
    """
    row,col=np.asarray(row,int),np.asarray(col,int)
    sizes=np.bincount(row,minlength=len(quality))
    validation=np.asarray(observation_index)%5==0
    anchors=defaultdict(list)
    for r,c,a in zip(row,col,values):
        if not validation[r] and sizes[r]==1:
            anchors[int(c)].append(float(quality[r]/a))
    point=np.full(n_cells,np.nan)
    for c,observed in anchors.items():
        point[c]=float(np.median(observed))
    supported=np.bincount(row,np.isfinite(point[col]),minlength=len(quality))==sizes
    selected=validation & supported & (sizes>0)
    prediction=np.bincount(row,values*np.nan_to_num(point[col]),minlength=len(quality))
    residual=prediction[selected]-quality[selected]
    return {'held_out_observe_actions':int(len(set(np.asarray(observation_index)[selected]))),
            'held_out_quality_rows_supported':int(selected.sum()),
            'training_one_cell_anchors':len(anchors),
            'max_abs_residual':float(np.max(np.abs(residual))) if len(residual) else None,
            'rms_residual':float(np.sqrt(np.mean(residual**2))) if len(residual) else None,
            'scope':'whole-action holdout in one already completed realization; no claim about a second realization'}


def audit(card, result, output):
    began = time.perf_counter()
    card, result, output = map(Path, (card, result, output))
    model = all_target_model(card)
    messages = load_messages(result/'messages.jsonl')
    repairs = [parse(m['issued_at_utc']).timestamp() for m in messages
               if m.get('record_type') == 'report_result' and m.get('correct') and m.get('repaired')]
    public = PublicQualityMatrix(model, repairs)
    clear = ReferenceClearFilter(model, messages)
    decisions = {int(d['observe_index']):d for d in csv.DictReader((result/'decisions.csv').open())
                 if d['action'] == 'observe'}
    groups = defaultdict(list)
    for hit in csv.DictReader((result/'observations.csv').open()):
        groups[int(hit['observe_index'])].append(hit)
    rows, columns, values, quality, row_keys = [], [], [], [], []
    counts = dict(observation_rows=0, factor_capped_rows=0, positive_rows=0, physical_invalidated_rows=0,
                  conditional_geometry_clear_rows=0, conditional_clear_positive_rows=0,
                  ambiguous_zero_rows_excluded=0, coefficient_nnz=0, single_cell_rows=0)
    max_q = 0
    duration_mismatches = []
    for observe_idx, hits in groups.items():
        d = decisions[observe_idx]
        start, end = parse(d['start_utc']).timestamp(), parse(d['end_utc']).timestamp()
        duration = float(d['duration_seconds'])
        if abs(end-start-duration)>1e-7:
            duration_mismatches.append(observe_idx)
            continue
        indices = [model.index[h['target_id']] for h in hits]
        cells, coeff = public.coefficients(start, duration, indices)
        overlaps = public.overlaps(start, duration)
        for j, (hit, index) in enumerate(zip(hits, indices)):
            q = float(hit['quality'])
            counts['observation_rows'] += 1
            counts['factor_capped_rows'] += float(hit['factor']) >= 1
            counts['positive_rows'] += q > 0
            counts['physical_invalidated_rows'] += hit['valid'] != 'true'
            max_q = max(max_q, q)
            if not clear.clear(index, overlaps):
                continue
            counts['conditional_geometry_clear_rows'] += 1
            if q <= 0:
                counts['ambiguous_zero_rows_excluded'] += 1
                continue
            counts['conditional_clear_positive_rows'] += 1
            row = len(quality)
            rows.extend([row]*len(cells));columns.extend(cells.tolist());values.extend(coeff[j].tolist())
            quality.append(q);row_keys.append([observe_idx, hit['target_id']])
            counts['single_cell_rows'] += len(cells)==1
    rows, columns, values, quality = map(np.asarray, (rows, columns, values, quality))
    fit = propagate_intervals(rows, columns, values, quality, len(public.cells))
    nnls = fit_nonnegative_profile(rows.astype(int),columns.astype(int),values,quality,len(public.cells))
    holdout=pure_cell_holdout(rows,columns,values,quality,[r[0] for r in row_keys],len(public.cells))
    support = np.bincount(columns.astype(int), minlength=len(public.cells))
    width = fit['upper']-fit['lower']
    bad = len(fit['contradictory_cells']) or len(fit['contradictory_rows'])
    report = json.loads((result/'score_report.json').read_text())
    counts.update(coefficient_nnz=len(values), public_calendar_cells=len(public.cells),
                  supported_cells=int(np.count_nonzero(support)), unsupported_cells=int(np.count_nonzero(support==0)),
                  width_le_1e_4=int(np.count_nonzero((support>0)&(width<=1e-4)&(width>=0))),
                  width_le_1e_3=int(np.count_nonzero((support>0)&(width<=1e-3)&(width>=0))),
                  width_le_1e_2=int(np.count_nonzero((support>0)&(width<=1e-2)&(width>=0))))
    summary = {'schema':'public-own-output-quality-inversion-v1','card':card.name,
        'scope':'conditional reference-domain interval constraints; not weather truth; no production reuse',
        'unknown':'Z=effectiveE*transparency*sky_quality/seeing; zero for nonobservable slot',
        'conditional_reference_Z_cap':REFERENCE_Z_CAP,'geometry_reference_bounds':{'terrain':[70,50],'weather':[120,80],'rocket':[80,60]},
        'uses_capped_factor_quality':True,'zero_rows_not_forced_to_background_closure':True,
        'counts':counts,'max_output_normalized_quality':max_q,
        'repair_timestamps_utc':[stamp(t) for t in repairs],
        'duration_mismatches':duration_mismatches,'interval_iterations':fit['iterations'],
        'uncapped_nnls':{k:v for k,v in nnls.items() if k!='profile'},
        'one_cell_whole_action_holdout':holdout,
        'no_interval_contradiction_detected':not bool(bad),
        'no_contradiction_is_not_a_global_feasibility_or_uniqueness_certificate':True,
        'contradictory_cells':fit['contradictory_cells'].tolist(),
        'contradictory_row_keys':[row_keys[i] for i in fit['contradictory_rows']],
        'official_scenario_file_only_sha256':report.get('sha256',{}).get('scenario'),
        'input_sha256':{str(p):sha256(p) for p in (card/'public/targets.csv',card/'public/v4_night_calendar.csv',
                        card/'config/v4_score_config.json',result/'decisions.csv',result/'observations.csv',result/'messages.jsonl')},
        'elapsed_seconds':time.perf_counter()-began}
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output.with_suffix('.npz'),cell_start=public.starts,cell_end=public.ends,
                        cell_night=np.array([c[0] for c in public.cells]),cell_slot=np.array([c[1] for c in public.cells]),
                        lower=fit['lower'],upper=fit['upper'],support=support,
                        nnls_point_prediction=nnls['profile'],
                        row=rows,col=columns,coefficient=values,quality=quality,
                        observation_index=np.array([r[0] for r in row_keys]),
                        target_id=np.array([r[1] for r in row_keys]))
    output.write_text(json.dumps(summary,indent=2)+'\n')
    return summary


def compare_runs(first, second):
    """Observed agreement only, never a certificate for the unobserved weather."""
    first, second = Path(first), Path(second)
    read=read_output
    def message_records(p):
        return [json.loads(line) for line in read(p,'messages.jsonl').splitlines() if line.strip()]
    reports = [json.loads(read(p,'score_report.json')) for p in (first, second)]
    public = []
    for p in (first, second):
        records = message_records(p)
        public.append({(m['record_type'],m['issued_at_utc']):json.dumps(m,sort_keys=True,separators=(',',':'))
                       for m in records if m.get('record_type') in ('bulletin','forecast')})
    common = public[0].keys() & public[1].keys()
    different = [key for key in common if public[0][key] != public[1][key]]
    quality = []
    for p in (first, second):
        decisions = {int(d['observe_index']):d for d in csv.DictReader(io.StringIO(read(p,'decisions.csv')))
                     if d['action']=='observe'}
        records = {}
        for h in csv.DictReader(io.StringIO(read(p,'observations.csv'))):
            d = decisions[int(h['observe_index'])]
            records[(h['target_id'],d['start_utc'],d['end_utc'],d['duration_seconds'])] = float(h['quality'])
        quality.append(records)
    overlap = quality[0].keys() & quality[1].keys()
    diffs = [abs(quality[0][k]-quality[1][k]) for k in overlap]
    def repairs(p):
        return [m['issued_at_utc'] for m in message_records(p)
                if m.get('record_type')=='report_result' and m.get('correct') and m.get('repaired')]
    return {'schema':'own-run-observed-stability-v1',
        'first_input':str(first),'second_input':str(second),
        'input_normalized_public_output_sha256':[{name:hashlib.sha256(read(p,name).encode()).hexdigest()
            for name in ('score_report.json','messages.jsonl','decisions.csv','observations.csv')} for p in (first,second)],
        'input_zip_sha256':[sha256(p) if not p.is_dir() else None for p in (first,second)],
        'scenario_YAML_hash_equal':reports[0].get('sha256',{}).get('scenario')==reports[1].get('sha256',{}).get('scenario'),
        'scenario_hash_does_not_cover_weather_truth':True,
        'common_public_bulletin_forecast_records':len(common),'changed_common_public_records':len(different),
        'first_only_public_records':len(public[0].keys()-public[1].keys()),'second_only_public_records':len(public[1].keys()-public[0].keys()),
        'changed_common_public_keys':different,
        'matching_target_time_actual_duration_quality_rows':len(overlap),
        'matching_quality_max_absolute_difference':max(diffs,default=None),
        'matching_quality_difference_over_1e_6':sum(d>1.000001e-6 for d in diffs),
        'repair_times_equal':repairs(first)==repairs(second),'first_repairs':repairs(first),'second_repairs':repairs(second),
        'scope':'agreement on finite published messages and matched measured integrals; no global realization guarantee'}


def cross_validate_profile(card,first_profile,first_run,second_run,*,max_cell_width=1e-4):
    """Predict new-run integrals with previous narrow cells; no interpolation.

    Reject exposures between different corresponding successful repair times.
    Only conditional geometry-clean positive rows with every cell narrowly
    constrained enter. This verifies those measured integrals, not unseen slots.
    """
    began=time.perf_counter()
    model=all_target_model(card)
    def messages(p):return [json.loads(s) for s in read_output(p,'messages.jsonl').splitlines() if s.strip()]
    def repairs(records):return sorted(parse(m['issued_at_utc']).timestamp() for m in records
                    if m.get('record_type')=='report_result' and m.get('correct') and m.get('repaired'))
    old_messages,new_messages=messages(first_run),messages(second_run)
    old_repairs,new_repairs=repairs(old_messages),repairs(new_messages)
    if len(old_repairs)!=len(new_repairs):
        return {'scope':'repair histories cannot be paired; validation not attempted','repair_history_length_mismatch':True}
    repair_gaps=[(min(a,b),max(a,b)) for a,b in zip(old_repairs,new_repairs) if a!=b]
    matrix=PublicQualityMatrix(model,old_repairs)
    profile=np.load(first_profile)
    if not np.array_equal(profile['cell_start'],matrix.starts) or not np.array_equal(profile['cell_end'],matrix.ends):
        raise ValueError('saved cell partition does not match public model and prior repair history')
    low,high,support=profile['lower'],profile['upper'],profile['support']
    eligible=(support>0)&(high>=low)&(high-low<=max_cell_width)
    clear=ReferenceClearFilter(model,new_messages)
    decisions={int(d['observe_index']):d for d in csv.DictReader(io.StringIO(read_output(second_run,'decisions.csv')))
               if d['action']=='observe'}
    groups=defaultdict(list)
    for hit in csv.DictReader(io.StringIO(read_output(second_run,'observations.csv'))):groups[int(hit['observe_index'])].append(hit)
    errors=[];violations=[];actions=set();repair_exposures=0;unsupported_exposures=0
    for observation,hits in groups.items():
        d=decisions[observation]
        start,end=parse(d['start_utc']).timestamp(),parse(d['end_utc']).timestamp()
        duration=float(d['duration_seconds'])
        if any(start<b and end>a for a,b in repair_gaps):repair_exposures+=1;continue
        if abs(end-start-duration)>1e-7:raise ValueError('actual duration mismatch')
        cells,coeff=matrix.coefficients(start,duration,[model.index[h['target_id']] for h in hits])
        if not np.all(eligible[cells]):unsupported_exposures+=1;continue
        overlaps=matrix.overlaps(start,duration)
        for j,hit in enumerate(hits):
            q=float(hit['quality']);index=model.index[hit['target_id']]
            if q<=0 or not clear.clear(index,overlaps):continue
            lo,hi=float(coeff[j]@low[cells]),float(coeff[j]@high[cells])
            point=(lo+hi)/2
            errors.append(point-q);actions.add(observation)
            radius=ROUNDING_RADIUS+GEOMETRY_GUARD
            outside=max(lo-q-radius,q-hi-radius,0)
            if outside>1e-12:
                violations.append({'observe_index':observation,'target_id':hit['target_id'],
                     'start_utc':d['start_utc'],'end_utc':d['end_utc'],'quality':q,
                     'predicted_low':lo,'predicted_high':hi,'outside':outside})
    return {'schema':'own-two-run-profile-cross-validation-v1','card':Path(card).name,
        'first_profile':str(first_profile),'first_profile_sha256':sha256(first_profile),
        'second_input':str(second_run),'second_zip_sha256':sha256(second_run) if not Path(second_run).is_dir() else None,
        'max_prior_cell_width':max_cell_width,'eligible_old_cells':int(eligible.sum()),
        'excluded_repair_gap_exposures':repair_exposures,'excluded_unsupported_exposures':unsupported_exposures,
        'repair_gap_utc':[[stamp(a),stamp(b)] for a,b in repair_gaps],
        'validated_independent_observe_actions':len(actions),'validated_positive_quality_rows':len(errors),
        'max_abs_midpoint_error':max(map(abs,errors),default=None),
        'rms_midpoint_error':float(np.sqrt(np.mean(np.square(errors)))) if errors else None,
        'outside_previous_conditional_interval_rows':len(violations),'violations':violations,
        'elapsed_seconds':time.perf_counter()-began,
        'scope':'finite new-run measured integrals with public geometry and prior narrow conditional cells; not all future weather certified'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--card');parser.add_argument('--result');parser.add_argument('--output')
    parser.add_argument('--compare',nargs=2)
    args=parser.parse_args()
    result=compare_runs(*args.compare) if args.compare else audit(args.card,args.result,args.output)
    print(json.dumps(result,indent=2))
