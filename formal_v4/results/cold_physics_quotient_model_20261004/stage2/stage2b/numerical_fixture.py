"""Frozen-contract export audit for one calibration state's complete family.

This module does not train, generate worlds, or run a fixture on import. The
caller supplies decoded float32 normalized inputs, exported weights, and the
actual float32 CUDA output. ``cases[*]['rows']`` and
``original_row_indices`` must already index the supplied row subset. The
original case must also supply ``original_target_indices_by_fiber`` from the
public target catalog independently of row selection. Hidden label arrays
are used only to judge the two selected current actions.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PROGRAMS = ("DARK", "BRIGHT", "BACKUP")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODEL = _load("_quotient_fixture_model", ROOT / "model.py")
CONTRACT = _load("_quotient_fixture_contract", ROOT / "numerical_contract.py")


def _digest(value):
    array = np.ascontiguousarray(value)
    return hashlib.sha256(array.tobytes()).hexdigest()


def _array(data, name, n, dtype=None):
    out = np.asarray(data[name], dtype=dtype)
    if out.shape != (n,):
        raise ValueError(f"{name} must have one value per supplied row")
    if out.dtype.kind in "fc" and not np.isfinite(out).all():
        raise ValueError(f"{name} contains a nonfinite value")
    return out


def _require(condition, message):
    if not bool(condition):
        raise AssertionError(message)


def _torch_transform(torch, raw, mean, std, temperature, sigma_multiplier):
    """The model.py transform, decoded and evaluated in CUDA float64."""
    raw = raw.to(dtype=torch.float64)
    logits = raw[:, :15] / temperature
    logits = logits - logits.max(dim=1, keepdim=True).values
    prob = torch.exp(logits)
    prob = prob / prob.sum(dim=1, keepdim=True)
    mu = mean + std * 8 * torch.tanh(raw[:, 15:27] / 8)
    sigma = (.03 + 1.97 * (.5 + .5 * torch.tanh(raw[:, 27:39] / 2))) * sigma_multiplier
    return prob.reshape(-1, 3, 5), mu.reshape(-1, 3, 4), sigma.reshape(-1, 3, 4)


def _torch_gain(torch, prob, mu, sigma, scale, weight, best, scoring):
    """The same analytic lognormal kernel as model.gain; no CDF approximation."""
    device = prob.device

    def tensor(value):
        return torch.as_tensor(value, dtype=torch.float64, device=device)

    a = tensor(scale)[:, None, None]
    w = tensor(weight)[:, None, None]
    b = tensor(best)[:, None, None]
    cdf = lambda x: .5 * torch.erfc(-x / math.sqrt(2))
    outputs = []
    for declared, program in enumerate(PROGRAMS):
        multip = np.full(3, scoring['program']['mismatch_multiplier'], np.float64)
        multip[declared] = scoring['program']['multipliers'][program]
        wm = w * tensor(multip)[None, :, None]
        lo = torch.log(torch.clamp(b / torch.clamp(wm * a, min=1e-300), min=1e-300))
        lo = torch.where(b == 0, -torch.inf, lo)
        hi = torch.log(1 / a)
        interval = cdf((hi - mu) / sigma) - cdf((lo - mu) / sigma)
        moment = torch.exp(mu + .5 * sigma * sigma) * (
            cdf((hi - mu - sigma * sigma) / sigma)
            - cdf((lo - mu - sigma * sigma) / sigma))
        tail = cdf((mu - hi) / sigma)
        value = wm * a * moment - b * interval + (wm - b) * tail
        value = torch.where(b >= wm, 0., torch.minimum(torch.clamp(value, min=0.), wm))
        outputs.append(torch.sum(prob[:, :, 1:] * value, dim=(1, 2)))
    return torch.stack(outputs, dim=1)


def _host_rate(option, data, scoring):
    """Fresh realized science for a selected action; not an actor feature."""
    program = option['program_index']
    total = 0.
    for row in option['selected_rows']:
        band = int(data['b'][row])
        multiplier = (scoring['program']['multipliers'][PROGRAMS[program]]
                      if band == program else scoring['program']['mismatch_multiplier'])
        if bool(data['actual_hit'][row]):
            total += max(float(data['weight'][row]) * float(data['F'][row]) * multiplier
                         - float(data['truebest'][row]), 0.)
    return float(total / option['duration'])


def _fixed_value(option, gain):
    return float(sum(float(gain[r, option['program_index']])
                     for r in option['selected_rows']) / option['duration'])


def _fixed_error(option, error):
    return float(sum(float(error[r]) for r in option['selected_rows']) / option['duration'])


def _identity(option, data, cases):
    case = cases[option['case_index']]
    # The original option and an optimizer option can denote the same action.
    # Ignore their option index when comparing executed-action identity.
    return (int(case['field']), float(option['duration']),
            json.dumps(case['pointing'], sort_keys=True), option['program_index'],
            tuple(sorted((int(data['fiber'][r]), int(data['idx'][r]))
                         for r in option['selected_rows'])))


def _options(gain, error, data, cases):
    """Original action first, then deterministic case/program fiber maxima."""
    originals = [i for i, c in enumerate(cases) if c.get('original_point_case')]
    if len(originals) != 1:
        raise ValueError("fixture requires exactly one complete original point case")
    ci = originals[0]
    original = cases[ci]
    if 'original_row_indices' not in original:
        raise ValueError("original case requires explicit original_row_indices")
    original_rows = [int(r) for r in original['original_row_indices']]
    if len(set(original_rows)) != len(original_rows):
        raise ValueError("original row indices are not unique")
    if not set(original_rows).issubset(set(original['rows'])):
        raise ValueError("an original assignment is absent from its complete case")
    assignments = original['original_assignments']
    if len(original_rows) != len(assignments):
        raise ValueError("original action assignment count changed")
    if {int(data['fiber'][r]) for r in original_rows} != {int(f) for f in assignments}:
        raise ValueError("original action assigned fibers changed")
    if 'original_target_indices_by_fiber' not in original:
        raise ValueError("original case requires independently mapped public target indices")
    expected_targets = {int(f): int(i) for f, i in original['original_target_indices_by_fiber'].items()}
    if set(expected_targets) != {int(f) for f in assignments}:
        raise ValueError("original expected target map has different assigned fibers")
    if any(int(data['idx'][r]) != expected_targets[int(data['fiber'][r])] for r in original_rows):
        raise ValueError("an original action assigned target changed")
    first = dict(option_index=0, case_index=ci, source='full_original',
                 program_index=PROGRAMS.index(original['original_program']),
                 duration=float(original['duration']), selected_rows=original_rows,
                 fiber_certificates=[], assignments_certified=True)
    first['value'] = _fixed_value(first, gain)
    first['upper_error'] = _fixed_error(first, error)
    options = [first]
    for case_index, case in enumerate(cases):
        rows = [int(r) for r in case['rows']]
        fibers = sorted({int(data['fiber'][r]) for r in rows})
        for program_index in range(3):
            selected, certificates, upper = [], [], 0.
            for fiber in fibers:
                candidates = [r for r in rows if int(data['fiber'][r]) == fiber
                              and bool(data['altitude_valid'][r])]
                # Empty assignment has index zero and wins an exact zero tie.
                values = np.asarray([0.] + [gain[r, program_index] for r in candidates])
                bounds = np.asarray([0.] + [error[r] for r in candidates])
                winner = int(np.argmax(values))
                if winner:
                    selected.append(candidates[winner - 1])
                stable = all(values[winner] - values[j] > bounds[winner] + bounds[j]
                             for j in range(len(values)) if j != winner)
                margin = (float(values[winner] - np.max(np.delete(values, winner)))
                          if len(values) > 1 else None)
                slacks = [float(values[winner] - values[j] - bounds[winner] - bounds[j])
                          for j in range(len(values)) if j != winner]
                certificates.append(dict(fiber=fiber, candidates=candidates,
                                         winner_row=candidates[winner - 1] if winner else None,
                                         certified=bool(stable), margin=margin,
                                         minimum_certificate_slack=min(slacks) if slacks else None,
                                         winner_error=float(bounds[winner])))
                upper += float(bounds.max())
            option = dict(option_index=len(options), case_index=case_index,
                          source='same_finite_family', program_index=program_index,
                          duration=float(case['duration']), selected_rows=selected,
                          fiber_certificates=certificates,
                          assignments_certified=all(c['certified'] for c in certificates))
            option['value'] = _fixed_value(option, gain)
            option['upper_error'] = float(upper / option['duration'])
            options.append(option)
    return options


def _action_audit(gain_a, gain_b, error, data, cases, scoring):
    options_a = _options(gain_a, error, data, cases)
    options_b = _options(gain_b, error, data, cases)
    values_a = np.asarray([o['value'] for o in options_a])
    values_b = np.asarray([o['value'] for o in options_b])
    bounds = np.asarray([o['upper_error'] for o in options_a])
    _require(np.all(np.abs(values_a - values_b) <= bounds),
             "a case/program optimized value exceeds its fiber-summed error bound")
    option_certificate = CONTRACT.action_certificate(values_a, values_b, bounds)
    ia, ib = option_certificate['index_a'], option_certificate['index_b']
    winner_a, winner_b = options_a[ia], options_b[ib]
    same_action = _identity(winner_a, data, cases) == _identity(winner_b, data, cases)
    certified = bool(option_certificate['certified'] and winner_a['assignments_certified'])
    _require(not certified or same_action, "certified full case/program/assignment changed")

    # Evaluate the actual CUDA-selected rows with CPU gains. Comparing only
    # case maxima would miss a changed per-fiber assignment inside that case.
    cpu_value_of_cuda_action = _fixed_value(winner_b, gain_a)
    selected_value_loss = float(winner_a['value'] - cpu_value_of_cuda_action)
    selected_loss_bound = _fixed_error(winner_a, error) + _fixed_error(winner_b, error)
    _require(selected_value_loss <= selected_loss_bound + 2e-12,
             "uncertified selected-action value loss exceeds summed row errors")

    assignment_changes = []
    for oa, ob in zip(options_a[1:], options_b[1:]):
        by_fiber_b = {c['fiber']: c for c in ob['fiber_certificates']}
        for ca in oa['fiber_certificates']:
            cb = by_fiber_b[ca['fiber']]
            if ca['winner_row'] != cb['winner_row']:
                _require(not ca['certified'], "certified fiber assignment changed")
                arow, brow = ca['winner_row'], cb['winner_row']
                av = float(gain_a[arow, oa['program_index']]) if arow is not None else 0.
                bv = float(gain_a[brow, oa['program_index']]) if brow is not None else 0.
                eb = (float(error[arow]) if arow is not None else 0.) + (
                    float(error[brow]) if brow is not None else 0.)
                _require(av - bv <= eb + 2e-12,
                         "uncertified fiber change exceeds summed row errors")
                assignment_changes.append(dict(case_index=oa['case_index'],
                    program=PROGRAMS[oa['program_index']], fiber=ca['fiber'],
                    cpu_row=arow, cuda_row=brow, margin=ca['margin'],
                    cpu_value_loss=float(av-bv), value_loss_bound=float(eb)))

    def describe(option):
        case = cases[option['case_index']]
        return dict(option_index=option['option_index'], source=option['source'],
                    case_index=option['case_index'], field=int(case['field']),
                    pointing=case['pointing'], actual_duration=option['duration'],
                    program=PROGRAMS[option['program_index']],
                    selected_rows=option['selected_rows'],
                    assignments=[dict(fiber=int(data['fiber'][r]), target_index=int(data['idx'][r]))
                                 for r in option['selected_rows']],
                    original_assignments=(case['original_assignments']
                                          if option['source'] == 'full_original' else None),
                    original_target_indices_by_fiber=(case['original_target_indices_by_fiber']
                                          if option['source'] == 'full_original' else None),
                    expected_science_rate=option['value'],
                    host_realized_science_rate=_host_rate(option, data, scoring),
                    assignments_certified=option['assignments_certified'],
                    fiber_certificates=option['fiber_certificates'])

    return dict(option_certificate=option_certificate,
                full_action_certified=certified, same_full_action=same_action,
                cpu_selected=describe(winner_a), cuda_selected=describe(winner_b),
                cpu_value_of_cuda_selected_action=cpu_value_of_cuda_action,
                selected_value_loss=selected_value_loss,
                selected_value_loss_bound=float(selected_loss_bound),
                uncertified_assignment_changes=assignment_changes,
                option_values_cpu=values_a.tolist(), option_values_cuda=values_b.tolist(),
                option_error_bounds=bounds.tolist(),
                original_action=describe(options_a[0]),
                tie_rule='original option first; case order; DARK/BRIGHT/BACKUP; empty fiber first; supplied row order')


def audit_fixture(x_normalized_float32, layers_float32, raw_cuda_float32,
                  logr_mean, logr_std, temperature, sigma_multiplier,
                  data, cases, scoring):
    """Audit one supplied calibration state against the predeclared gates.

    Raises on a gate violation, returns a JSON-serializable receipt on success.
    ``raw_cuda_float32`` may be a CUDA float32 tensor or a decoded NumPy
    float32 copy of that output. Analytic CUDA decoding/gain still runs in
    float64 on CUDA. The helper never relaxes a gate after observing values.
    """
    import torch

    numerical_lock = json.loads((ROOT / 'NUMERICAL_CONTRACT.json').read_text())
    micro_lock = json.loads((ROOT / 'MICRO_OBJECTIVE_LOCK.json').read_text())
    x = np.asarray(x_normalized_float32)
    if x.dtype != np.float32 or x.ndim != 2 or x.shape[1] != MODEL.INPUT_DIM or not len(x):
        raise ValueError("normalized input must be nonempty (N,5963) decoded float32")
    _require(np.isfinite(x).all(), "normalized input contains nonfinite values")
    layers = [(np.asarray(w), np.asarray(b)) for w, b in layers_float32]
    shapes = [((128, MODEL.INPUT_DIM), (128,)), ((128, 128), (128,)), ((39, 128), (39,))]
    if len(layers) != len(shapes):
        raise ValueError("fixture requires the frozen three-layer ordinary head")
    for (w, b), (ws, bs) in zip(layers, shapes):
        if w.dtype != np.float32 or b.dtype != np.float32 or w.shape != ws or b.shape != bs:
            raise ValueError("weights/biases must match decoded float32 frozen-head shapes")
        _require(np.isfinite(w).all() and np.isfinite(b).all(), "nonfinite exported weight")
    parameters = np.asarray([logr_mean, logr_std, temperature, sigma_multiplier], np.float64)
    if not np.isfinite(parameters).all() or min(logr_std, temperature, sigma_multiplier) <= 0:
        raise ValueError("invalid transform parameters")
    logr_mean, logr_std, temperature, sigma_multiplier = map(float, parameters)
    _require(torch.cuda.is_available(), "CUDA unavailable for float64 kernel audit")
    _require(not torch.backends.cuda.matmul.allow_tf32, "TF32 must be disabled before fixture")
    if isinstance(raw_cuda_float32, torch.Tensor):
        if raw_cuda_float32.dtype != torch.float32 or raw_cuda_float32.device.type != 'cuda':
            raise ValueError("tensor raw output must be actual CUDA float32")
        raw_gpu = raw_cuda_float32.detach()
        raw = raw_gpu.cpu().numpy()
        provenance = 'supplied_cuda_float32_tensor'
    else:
        raw = np.asarray(raw_cuda_float32)
        if raw.dtype != np.float32:
            raise ValueError("decoded raw output must be float32")
        raw_gpu = torch.as_tensor(raw, dtype=torch.float32, device='cuda')
        provenance = 'supplied_decoded_cuda_float32_copy'
    if raw.shape != (len(x), MODEL.OUTPUT_DIM):
        raise ValueError("CUDA output shape does not match supplied inputs")
    _require(np.isfinite(raw).all(), "CUDA raw output is nonfinite")

    n = len(x)
    arrays = {name: _array(data, name, n, dtype) for name, dtype in [
        ('scale', np.float64), ('weight', np.float64), ('best', np.float64),
        ('actual_hit', bool), ('truebest', np.float64), ('F', np.float64),
        ('b', np.int64), ('idx', np.int64), ('fiber', np.int64), ('altitude_valid', bool)]}
    _require(np.all(arrays['scale'] > 0), "gain scale must be positive")
    _require(np.all(arrays['weight'] >= 0) and np.all(arrays['best'] >= 0)
             and np.all(arrays['truebest'] >= 0), "negative science weight or best")
    _require(np.all((arrays['F'] >= 0) & (arrays['F'] <= 1)), "invalid host factor")
    _require(np.all((arrays['b'] >= 0) & (arrays['b'] < 3)), "invalid host band")
    _require(not np.any(arrays['actual_hit'] & ~arrays['altitude_valid']),
             "host actual hit contradicts public altitude invalidity")
    if not cases or len({int(c['state']) for c in cases}) != 1:
        raise ValueError("fixture must contain a single state's complete family")
    supplied_rows = []
    for case in cases:
        if not math.isfinite(float(case['duration'])) or float(case['duration']) <= 0:
            raise ValueError("case duration must be the actual positive clipped duration")
        rows = [int(r) for r in case['rows']]
        if not rows or len(set(rows)) != len(rows) or min(rows) < 0 or max(rows) >= n:
            raise ValueError("case row subset is invalid")
        if len(set(int(arrays['idx'][r]) for r in rows)) != len(rows):
            raise ValueError("a case repeats one target in multiple fibers")
        supplied_rows.extend(rows)
    if sorted(supplied_rows) != list(range(n)):
        raise ValueError("fixture rows must cover exactly the supplied complete family")
    multipliers = np.asarray([scoring['program']['multipliers'][p] for p in PROGRAMS]
                            + [scoring['program']['mismatch_multiplier']], np.float64)
    if not np.isfinite(multipliers).all() or np.any(multipliers <= 0):
        raise ValueError("program multipliers must be finite and positive")
    wm_max = arrays['weight'] * float(multipliers.max())

    raw_cpu = MODEL.numpy_forward(x, layers)
    logit_bound, layer_trace = CONTRACT.forward_error_bound(x, layers)
    raw_difference = np.abs(raw_cpu - raw.astype(np.float64))
    _require(np.all(raw_difference <= logit_bound), "float32 raw-logit scale bound exceeded")
    prob_a, mu_a, sigma_a = MODEL.transform(raw_cpu, logr_mean, logr_std,
                                           temperature, sigma_multiplier)
    prob_gpu, mu_gpu, sigma_gpu = _torch_transform(torch, raw_gpu, logr_mean, logr_std,
                                                   temperature, sigma_multiplier)
    prob_b, mu_b, sigma_b = (t.cpu().numpy() for t in (prob_gpu, mu_gpu, sigma_gpu))
    _require(all(np.isfinite(v).all() for v in (prob_a, mu_a, sigma_a, prob_b, mu_b, sigma_b))
             and np.all(sigma_a > 0) and np.all(sigma_b > 0), "invalid transformed distribution")
    probability_difference = np.abs(prob_a - prob_b)
    probability_l1 = probability_difference.sum(axis=(1, 2))
    caps = numerical_lock['probability_practical_caps']
    _require(probability_difference.max() <= caps['max_abs'], "probability Linf cap exceeded")
    _require(probability_l1.max() <= caps['max_perrow_l1'], "probability row L1 cap exceeded")

    gains_cpu = MODEL.gain(prob_a, mu_a, sigma_a, arrays['scale'], arrays['weight'],
                           arrays['best'], scoring)
    gains_gpu = _torch_gain(torch, prob_gpu, mu_gpu, sigma_gpu, arrays['scale'],
                            arrays['weight'], arrays['best'], scoring)
    gains_cuda = gains_gpu.cpu().numpy()
    kernel_same_parameters = MODEL.gain(prob_b, mu_b, sigma_b, arrays['scale'],
                                        arrays['weight'], arrays['best'], scoring)
    kernel_error = np.abs(kernel_same_parameters - gains_cuda)
    _require(np.isfinite(gains_cpu).all() and np.isfinite(gains_cuda).all(), "nonfinite analytic gain")
    _require(np.all(kernel_error <= numerical_lock['kernel_allowance_per_Mmax'] * wm_max[:, None]),
             "float64 CPU/CUDA kernel discrepancy exceeds frozen allowance")
    gain_bound = CONTRACT.distribution_gain_bound(prob_a, prob_b, mu_a, mu_b,
                                                  sigma_a, sigma_b, wm_max)
    gain_difference = np.abs(gains_cpu - gains_cuda)
    _require(np.all(gain_difference <= gain_bound[:, None]), "gain coupling bound exceeded")
    _require(np.all(gain_difference <= 1e-4 * wm_max[:, None]), "gain practical cap exceeded")
    # Public legality is usable by the actor. Actual hit and true labels do not
    # enter expected action selection or its error certificate.
    masked_gain_a = np.where(arrays['altitude_valid'][:, None], gains_cpu, 0.)
    masked_gain_b = np.where(arrays['altitude_valid'][:, None], gains_cuda, 0.)
    masked_error = np.where(arrays['altitude_valid'], gain_bound, 0.)
    actions = _action_audit(masked_gain_a, masked_gain_b, masked_error, arrays, cases, scoring)

    def relative_max(values):
        divisor = wm_max[:, None]
        return float(np.divide(values, divisor, out=np.zeros_like(values), where=divisor > 0).max())

    receipt = dict(status='PASS_OBSERVED_SUPPLIED_CALIBRATION_FIXTURE',
        scope='one calibration state; one current exposure finite-family objective',
        states=[int(cases[0]['state'])], rows=n, cases=len(cases),
        no_joint_future_or_formal_score_claim=True,
        cuda_output_provenance=provenance, cuda_device=str(raw_gpu.device),
        cuda_device_name=torch.cuda.get_device_name(raw_gpu.device),
        torch_version=str(torch.__version__), tf32_disabled=True,
        input_sha256=_digest(x), raw_cuda_sha256=_digest(raw),
        weights_sha256=[dict(weight=_digest(w), bias=_digest(b)) for w, b in layers],
        numerical_lock_sha256=hashlib.sha256((ROOT / 'NUMERICAL_CONTRACT.json').read_bytes()).hexdigest(),
        micro_objective_lock_sha256=hashlib.sha256((ROOT / 'MICRO_OBJECTIVE_LOCK.json').read_bytes()).hexdigest(),
        objective=micro_lock['objective'],
        transform=dict(logr_mean=float(logr_mean), logr_std=float(logr_std),
                       temperature=float(temperature), sigma_multiplier=float(sigma_multiplier)),
        raw_logits=dict(max_absolute_difference=float(raw_difference.max()),
                        max_scale_bound=float(logit_bound.max()),
                        max_bound_ratio=float((raw_difference/logit_bound).max()),
                        per_output_max_difference=raw_difference.max(axis=0).tolist(),
                        per_output_max_bound=logit_bound.max(axis=0).tolist(),
                        layers=layer_trace, fixed_absolute_threshold_used=False),
        probability=dict(max_absolute_difference=float(probability_difference.max()),
                         max_perrow_l1=float(probability_l1.max()), caps=caps),
        parameters=dict(max_mu_difference=float(np.abs(mu_a-mu_b).max()),
                        max_sigma_difference=float(np.abs(sigma_a-sigma_b).max())),
        gain=dict(max_absolute_difference=float(gain_difference.max()),
                  max_per_Mmax_difference=relative_max(gain_difference),
                  max_coupling_bound=float(gain_bound.max()),
                  max_float64_kernel_difference=float(kernel_error.max()),
                  max_float64_kernel_per_Mmax=relative_max(kernel_error),
                  practical_cap_per_Mmax=1e-4,
                  kernel_allowance_per_Mmax=numerical_lock['kernel_allowance_per_Mmax']),
        action=actions)
    # Fail immediately if a NumPy scalar, NaN or infinity escaped the receipt.
    json.dumps(receipt, allow_nan=False)
    return receipt
