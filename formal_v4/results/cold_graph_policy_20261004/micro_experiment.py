"""Official 900-second synthetic domain and joint-gate/quotient audits.

Only reads official implementation, L1 public constants and this directory.
Does not import any production strategy, prior trace, teacher or bulk label.
"""
from pathlib import Path
import copy
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import itertools
import json
import math
import random
import sys
import time

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OFFICIAL = ROOT / "formal_v4/upstream/gosim-observer-examples"
sys.path.insert(0, str(OFFICIAL / "runner"))
from challenge.v4_fiber_map import FiberGrid, altaz_to_radec, radec_to_altaz
from challenge.v4_runner import load_scenario, run_scenario
from challenge.v4_scorer import (BestLedger, WeatherTruth, lunar_quality_factor,
                                 score_target_exposure, settle_observation_requests)
from joint_occurrence_dp import Column, solve


def utc(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def offset_target(center_alt, center_az, d_alt, d_az, moment, site):
    a, z = map(math.radians, (center_alt, center_az))
    center = (math.cos(a)*math.cos(z), math.cos(a)*math.sin(z), math.sin(a))
    up = (-math.sin(a)*math.cos(z), -math.sin(a)*math.sin(z), math.cos(a))
    right = (-math.sin(z), math.cos(z), 0.)
    v = [c + math.radians(d_alt)*u + math.radians(d_az)*r
         for c, u, r in zip(center, up, right)]
    norm = math.sqrt(sum(x*x for x in v))
    alt = math.degrees(math.asin(v[2]/norm))
    az = math.degrees(math.atan2(v[1], v[0])) % 360
    return altaz_to_radec(alt, az, moment, site["latitude_deg"], site["longitude_deg"])


def create_synthetic():
    folder = HERE / "synthetic_card"
    folder.mkdir(exist_ok=True)
    constants = OFFICIAL / "local-cards/L1/config"
    fiber = json.loads((constants / "v4_fiber_config.json").read_text())
    score = json.loads((constants / "v4_score_config.json").read_text())
    site = {**fiber["site"], "sun_altitude_limit_deg": -18.}
    grid = FiberGrid.from_config(fiber)
    start = datetime(2026, 11, 2, 2, 0, tzinfo=timezone.utc)
    end = start + timedelta(seconds=900)
    # Place all targets in the same occupied RA band, so Jain is exactly 1 for
    # both nonempty policies and cannot hide the request mechanism.
    from challenge.tile_geometry_simulator import _local_sidereal_deg
    ra_center = (int(_local_sidereal_deg(start, site["longitude_deg"])/10)*10 + 5) % 360
    targets, science_actions = [], []
    for exposure in range(15):
        moment = start + timedelta(seconds=60*exposure)
        dec = -70. + 3*exposure
        alt, az = radec_to_altaz(ra_center, dec, moment, site["latitude_deg"], site["longitude_deg"])
        assignments = {}
        for fid in (5, 6, 9, 10):
            d_alt, d_az = grid.fiber_center_offset(fid)
            ra, target_dec = offset_target(alt, az, d_alt, d_az, moment, site)
            target_id = f"B{exposure:02d}F{fid:02d}"
            targets.append(dict(target_id=target_id, ra_deg=ra, dec_deg=target_dec,
                                target_class="QSO", feature_flux=7.5,
                                science_weight=1.7, required="false"))
            assignments[str(fid)] = target_id
        science_actions.append(dict(action="observe", pointing=dict(alt_deg=alt, az_deg=az),
                                    assignments=assignments, duration_seconds=60, program="DARK"))
    alt, az = radec_to_altaz(ra_center, -12., start, site["latitude_deg"], site["longitude_deg"])
    shared_assignments = {}
    for target_index, fid in enumerate((1, 2, 5, 6, 9, 10)):
        d_alt, d_az = grid.fiber_center_offset(fid)
        ra, dec = offset_target(alt, az, d_alt, d_az, start, site)
        target_id = f"R{target_index}"
        targets.append(dict(target_id=target_id, ra_deg=ra, dec_deg=dec,
                            target_class="Star", feature_flux=.2,
                            science_weight=.3, required="false"))
        shared_assignments[str(fid)] = target_id
    for q in range(2):
        for i in range(2):
            targets.append(dict(target_id=f"Z{q}{i}", ra_deg=ra_center,
                                dec_deg=-15.-.1*i, target_class="Star",
                                feature_flux=0., science_weight=.3, required="false"))
    shared_action = dict(action="observe", pointing=dict(alt_deg=alt, az_deg=az),
                         assignments=shared_assignments, duration_seconds=900, program="DARK")
    requests = [dict(schema_version="v4-observation-request-v1", record_type="observation_request",
                     request_id=f"Q{q}", issued_at_utc=utc(start), deadline_utc=utc(end),
                     target_ids=[f"R{i}" for i in range(6)] + [f"Z{q}{i}" for i in range(2)],
                     minimum_completed=6, completion_factor_threshold=.5,
                     completion_reward=100., reason="declared synthetic shared follow-up")
                for q in range(2)]
    (folder / "v4_fiber_config.json").write_text(json.dumps(fiber, indent=2)+"\n")
    (folder / "v4_score_config.json").write_text(json.dumps(score, indent=2)+"\n")
    write_csv(folder / "targets.csv", targets,
              ("target_id", "ra_deg", "dec_deg", "target_class", "feature_flux", "science_weight", "required"))
    write_csv(folder / "slots.csv", [dict(slot_id="N20261101-S001", timestamp_utc=utc(start), duration_seconds=900)],
              ("slot_id", "timestamp_utc", "duration_seconds"))
    write_csv(folder / "weather.csv", [dict(slot_id="N20261101-S001", is_observable="true",
                                          seeing_arcsec=.5, transparency=1., sky_quality=1., instrument_efficiency=1.)],
              ("slot_id", "is_observable", "seeing_arcsec", "transparency", "sky_quality", "instrument_efficiency"))
    write_csv(folder / "events.csv", [], ("event_id", "event_type", "actual_start_utc", "actual_end_utc", "scope_type",
              "azimuth_start_deg", "azimuth_end_deg", "min_altitude_deg", "max_altitude_deg",
              "seeing_multiplier", "transparency_multiplier", "sky_quality_multiplier", "instrument_efficiency_multiplier", "force_close"))
    write_csv(folder / "footprint.csv", [dict(component_id="C00", vertex_index=i, ra_deg=r, dec_deg=d)
              for i, (r, d) in enumerate(((ra_center-4, -75), (ra_center+4, -75), (ra_center+4, -5), (ra_center-4, -5)))],
              ("component_id", "vertex_index", "ra_deg", "dec_deg"))
    (folder / "bulletins.jsonl").write_text(json.dumps(dict(record_type="bulletin", issued_at_utc=utc(start),
              slot_id="N20261101-S001", night_id="N20261101", initial=True, notices=[]))+"\n")
    (folder / "forecasts.jsonl").write_text("")
    (folder / "requests.jsonl").write_text("".join(json.dumps(r)+"\n" for r in requests))
    scenario = dict(schema_version="v4-scenario-v1", name="joint-gate-synthetic-900s", site=site,
              minimum_altitude_deg=30., fiber_config="v4_fiber_config.json", score_config="v4_score_config.json",
              products=dict(targets_csv="targets.csv", footprint_csv="footprint.csv", slots_csv="slots.csv",
                            weather_truth_csv="weather.csv", events_csv="events.csv", bulletins_jsonl="bulletins.jsonl",
                            forecasts_jsonl="forecasts.jsonl", observation_requests_jsonl="requests.jsonl"),
              stress=dict(enabled=False))
    path = folder / "v4_scenario.json"
    path.write_text(json.dumps(scenario, indent=2)+"\n")
    loaded = load_scenario(path)
    # Tune only a declared synthetic target flux: every common target has raw
    # factor .55 in the long action, avoiding threshold roundoff or saturation.
    weather = WeatherTruth(loaded.slots, [])
    for target in loaded.targets:
        if not target["target_id"].startswith("R"):
            continue
        scored = score_target_exposure(target, list(weather.segments(start, end)), [], weather,
                 900, 1., score, start,
                 lambda t, target=target: radec_to_altaz(target["ra_deg"], target["dec_deg"], t,
                         site["latitude_deg"], site["longitude_deg"]), site)
        flux = .55*score["flux_zero_point"]*score["exposure_zero_point_seconds"]/(900*scored.quality)
        next(row for row in targets if row["target_id"] == target["target_id"])["feature_flux"] = flux
    write_csv(folder / "targets.csv", targets,
              ("target_id", "ra_deg", "dec_deg", "target_class", "feature_flux", "science_weight", "required"))
    (HERE / "frozen_actions.json").write_text(json.dumps(dict(science=science_actions, shared=[shared_action]), indent=2)+"\n")
    return path, science_actions, [shared_action], requests


def tape_factory(actions):
    def factory(context):
        todo = iter(copy.deepcopy(actions))
        return lambda snapshot: next(todo, {"action": "finish"})
    return factory


def official_synthetic():
    path, science, shared, requests = create_synthetic()
    base = run_scenario(path, tape_factory(science), HERE / "official_science")
    joint = run_scenario(path, tape_factory(shared), HERE / "official_shared")
    cost = base["components"]["sum_best_scores"] - joint["components"]["sum_best_scores"]
    masks = [((1 << 8)-1), ((1 << 8)-1) << 8]
    shared_mask = sum(1 << (q*8+i) for q in range(2) for i in range(6))
    columns = [Column(0., 900., cost, shared_mask, shared[0])]
    reduced = solve(columns, masks, [6, 6], [100., 100.], quotient=True)
    raw = solve(columns, masks, [6, 6], [100., 100.], quotient=False)
    independent_pursues = [cost < r["completion_reward"] for r in requests]
    observations = list(csv.DictReader((HERE / "official_shared/observations.csv").open()))
    assert len(observations) == 6 and all(abs(float(row["factor"])-.55) < 1e-6 for row in observations)
    assert base["termination"]["reason"] == joint["termination"]["reason"] == "survey_complete"
    assert base["counts"]["observe_actions"] == 15 and joint["counts"]["observe_actions"] == 1
    assert base["components"]["observation_request_reward"] == 0
    assert joint["components"]["observation_request_reward"] == 200
    assert not any(independent_pursues) and reduced["chosen"] == (0,)
    assert abs(reduced["value"]-(joint["total"]-base["total"])) < 2e-6
    assert reduced["value"] == raw["value"]
    assert reduced["atom_count"] == 1 and raw["atom_count"] == 12
    for report in (base, joint):
        assert report["components"]["required_penalty"] == 0
        assert report["components"]["uniformity_penalty"] == 0
        assert report["components"]["report_settlement"] == 0
    return dict(science_control=base["total"], shared_joint=joint["total"], delta=joint["total"]-base["total"],
                components_control=base["components"], components_joint=joint["components"],
                action_cost=cost, each_request_reward=100., independent_pursues=independent_pursues,
                joint_plan=reduced, uncompressed_plan=raw,
                state_capacity_before=1 << 16, state_capacity_active_uncompressed=1 << 12,
                state_capacity_after=2, current_requests=len(requests),
                scope="900-second official synthetic finite action domain; no production/season claim")


def official_six_column():
    """Six shared completion columns, with same-duration additive science costs.

    Each 60s R field yields .198 science; the fixed same-interval B action
    yields 32.64. Each request needs all six columns, so each rejects the
    194.652 plan in isolation while their joint reward 200 pays it once.
    """
    folder = HERE / "synthetic_six_column_card"
    folder.mkdir(exist_ok=True)
    old = HERE / "synthetic_card"
    fiber = json.loads((old / "v4_fiber_config.json").read_text())
    score = json.loads((old / "v4_score_config.json").read_text())
    scenario = json.loads((old / "v4_scenario.json").read_text())
    site = scenario["site"]
    grid = FiberGrid.from_config(fiber)
    start = datetime(2026, 11, 2, 2, 0, tzinfo=timezone.utc)
    end = start+timedelta(seconds=360)
    from challenge.tile_geometry_simulator import _local_sidereal_deg
    ra_center = (int(_local_sidereal_deg(start, site["longitude_deg"])/10)*10+5) % 360
    targets, base_actions, shared_actions = [], [], []
    for exposure in range(6):
        moment = start+timedelta(seconds=60*exposure)
        alt, az = radec_to_altaz(ra_center, -70.+3*exposure, moment, site["latitude_deg"], site["longitude_deg"])
        assignments = {}
        for fid in range(16):
            ra, dec = offset_target(alt, az, *grid.fiber_center_offset(fid), moment, site)
            target_id = f"B{exposure}F{fid:02d}"
            targets.append(dict(target_id=target_id, ra_deg=ra, dec_deg=dec,
                                target_class="QSO", feature_flux=7.5, science_weight=1.7, required="false"))
            assignments[str(fid)] = target_id
        base_actions.append(dict(action="observe", pointing=dict(alt_deg=alt, az_deg=az),
                                 assignments=assignments, duration_seconds=60, program="DARK"))
        alt, az = radec_to_altaz(ra_center, -35.+5*exposure, moment, site["latitude_deg"], site["longitude_deg"])
        ra, dec = offset_target(alt, az, *grid.fiber_center_offset(5), moment, site)
        targets.append(dict(target_id=f"R{exposure}", ra_deg=ra, dec_deg=dec,
                            target_class="Star", feature_flux=.2, science_weight=.3, required="false"))
        shared_actions.append(dict(action="observe", pointing=dict(alt_deg=alt, az_deg=az),
                                   assignments={"5": f"R{exposure}"}, duration_seconds=60, program="DARK"))
    for q in range(2):
        for i in range(2):
            targets.append(dict(target_id=f"Z{q}{i}", ra_deg=ra_center, dec_deg=-15.-.1*i,
                                target_class="Star", feature_flux=0., science_weight=.3, required="false"))
    fields = ("target_id", "ra_deg", "dec_deg", "target_class", "feature_flux", "science_weight", "required")
    for name in ("v4_fiber_config.json", "v4_score_config.json", "events.csv", "footprint.csv", "bulletins.jsonl", "forecasts.jsonl"):
        (folder / name).write_bytes((old / name).read_bytes())
    write_csv(folder / "targets.csv", targets, fields)
    write_csv(folder / "slots.csv", [dict(slot_id="N20261101-S001", timestamp_utc=utc(start), duration_seconds=900)],
              ("slot_id", "timestamp_utc", "duration_seconds"))
    (folder / "weather.csv").write_bytes((old / "weather.csv").read_bytes())
    requests = [dict(schema_version="v4-observation-request-v1", record_type="observation_request",
                     request_id=f"Q{q}", issued_at_utc=utc(start), deadline_utc=utc(end),
                     target_ids=[f"R{i}" for i in range(6)]+[f"Z{q}{i}" for i in range(2)],
                     minimum_completed=6, completion_factor_threshold=.5, completion_reward=100.,
                     reason="declared synthetic shared six-column follow-up") for q in range(2)]
    (folder / "requests.jsonl").write_text("".join(json.dumps(r)+"\n" for r in requests))
    scenario["name"] = "joint-gate-synthetic-six-columns"
    path = folder / "v4_scenario.json"
    path.write_text(json.dumps(scenario, indent=2)+"\n")
    loaded = load_scenario(path)
    weather = WeatherTruth(loaded.slots, [])
    for i in range(6):
        target = next(t for t in loaded.targets if t["target_id"] == f"R{i}")
        left, right = start+timedelta(seconds=60*i), start+timedelta(seconds=60*(i+1))
        scored = score_target_exposure(target, list(weather.segments(left, right)), [], weather, 60, 1., score, left,
                    lambda t, target=target: radec_to_altaz(target["ra_deg"], target["dec_deg"], t,
                                    site["latitude_deg"], site["longitude_deg"]), site)
        next(t for t in targets if t["target_id"] == f"R{i}")["feature_flux"] = .55*450/(60*scored.quality)
    write_csv(folder / "targets.csv", targets, fields)
    # Keep the official 900-second slot grid. The compared request domain is
    # its first 360s; both finite-domain policies then take the same 540s wait.
    base_actions.append(dict(action="wait", duration_seconds=540))
    shared_actions.append(dict(action="wait", duration_seconds=540))
    (HERE / "frozen_six_column_actions.json").write_text(json.dumps(dict(science=base_actions, shared=shared_actions), indent=2)+"\n")
    base = run_scenario(path, tape_factory(base_actions), HERE / "official_six_column_science")
    joint = run_scenario(path, tape_factory(shared_actions), HERE / "official_six_column_shared")
    baseline_rows = list(csv.DictReader((HERE / "official_six_column_science/observations.csv").open()))
    shared_rows = list(csv.DictReader((HERE / "official_six_column_shared/observations.csv").open()))
    costs = [sum(float(r["score"]) for r in baseline_rows if int(r["observe_index"]) == i)
             - sum(float(r["score"]) for r in shared_rows if int(r["observe_index"]) == i) for i in range(6)]
    columns = [Column(60*i, 60*(i+1), costs[i], (1 << i) | (1 << (8+i)), shared_actions[i]) for i in range(6)]
    masks = [(1 << 8)-1, ((1 << 8)-1) << 8]
    independent = []
    for q in range(2):
        only_this_request = [Column(c.start, c.end, c.cost, c.occurrences & masks[q], c.tag) for c in columns]
        independent.append(solve(only_this_request, [masks[q]], [6], [100.]))
    reduced = solve(columns, masks, [6, 6], [100., 100.])
    raw = solve(columns, masks, [6, 6], [100., 100.], quotient=False)
    assert len(shared_rows) == 6 and all(abs(float(r["factor"])-.55) < 1e-6 for r in shared_rows)
    assert all(r["termination"]["reason"] == "survey_complete" for r in (base, joint))
    assert all(not p["chosen"] and p["value"] == 0 for p in independent)
    assert reduced["chosen"] == tuple(range(6)) and reduced["value"] == raw["value"]
    assert abs(reduced["value"]-(joint["total"]-base["total"])) < 2e-6
    assert all(abs(cost-32.442) < 1e-6 for cost in costs)
    assert all(r["components"][key] == 0 for r in (base, joint)
               for key in ("required_penalty", "uniformity_penalty", "report_settlement"))
    return dict(science_control=base["total"], shared_joint=joint["total"], delta=joint["total"]-base["total"],
                components_control=base["components"], components_joint=joint["components"], column_costs=costs,
                complete_plan_cost=sum(costs), independent_plans=independent, joint_plan=reduced, uncompressed_plan=raw,
                state_capacity_before=1 << 16, state_capacity_active_uncompressed=1 << 12,
                state_capacity_after=1 << reduced["atom_count"],
                scope="360-second request domain in official 900s synthetic slot, common final 540s wait; same-duration science regret cost, no native claim")


def audit_random():
    rng = random.Random(20261004)
    start = datetime(2026, 11, 2, 2, 0, tzinfo=timezone.utc)
    errors, reductions, state_saved = [], 0, 0
    cases = 300
    for case in range(cases):
        target_ids = [f"T{i}" for i in range(rng.randint(2, 6))]
        requests, request_masks, occurrence_bits = [], [], {}
        bit = 0
        for q in range(rng.randint(2, 3)):
            ids = rng.sample(target_ids, rng.randint(1, len(target_ids)))
            issued = rng.choice((0, 20, 40))
            deadline = rng.choice((60, 80, 100))
            requests.append(dict(request_id=f"Q{q}", issued_at_utc=start+timedelta(seconds=issued),
                          deadline_utc=start+timedelta(seconds=deadline), target_ids=ids,
                          minimum_completed=rng.randint(1, len(ids)), completion_factor_threshold=.5,
                          completion_reward=float(rng.choice((20, 30, 50)))))
            mask = 0
            for target in ids:
                occurrence_bits[q, target] = bit
                mask |= 1 << bit
                bit += 1
            request_masks.append(mask)
        columns, records = [], []
        history = BestLedger()
        if rng.random() < .5:
            for target in rng.sample(target_ids, rng.randint(1, len(target_ids))):
                history.record(-1, target, .6, .6, start, start+timedelta(seconds=20))
        initial = 0
        initial_statuses, _ = settle_observation_requests(requests, history)
        for q, status in enumerate(initial_statuses):
            for target in status["completed_target_ids"]:
                initial |= 1 << occurrence_bits[q, target]
        for c in range(rng.randint(2, 9)):
            left = rng.choice((40, 60, 80))
            right = left + rng.choice((20, 40))
            if right > 100:
                right = 100
            hits = {target: rng.choice((.4, .6)) for target in rng.sample(target_ids, rng.randint(1, len(target_ids)))}
            mask = 0
            for q, req in enumerate(requests):
                if (req["issued_at_utc"] <= start+timedelta(seconds=left)
                        and start+timedelta(seconds=right) <= req["deadline_utc"]):
                    for target in req["target_ids"]:
                        if hits.get(target, 0) >= .5:
                            mask |= 1 << occurrence_bits[q, target]
            columns.append(Column(left, right, float(rng.randrange(0, 31)), mask))
            records.append(hits)
        qargs = ([r["minimum_completed"] for r in requests], [r["completion_reward"] for r in requests])
        reduced = solve(columns, request_masks, *qargs, initial=initial)
        raw = solve(columns, request_masks, *qargs, initial=initial, quotient=False)
        exhaustive = settle_observation_requests(requests, history)[1]
        for schedule_mask in range(1 << len(columns)):
            selected = sorted((i for i in range(len(columns)) if schedule_mask & (1 << i)),
                              key=lambda i: (columns[i].start, columns[i].end))
            if any(columns[a].end > columns[b].start for a, b in zip(selected, selected[1:])):
                continue
            ledger = copy.deepcopy(history)
            for i in selected:
                col = columns[i]
                for target, factor in records[i].items():
                    ledger.record(i, target, factor, factor, start+timedelta(seconds=col.start),
                                  start+timedelta(seconds=col.end))
            _, official_reward = settle_observation_requests(requests, ledger)
            objective = official_reward-sum(columns[i].cost for i in selected)
            exhaustive = max(exhaustive, objective)
        if reduced["value"] != exhaustive or raw["value"] != exhaustive:
            errors.append(dict(case=case, expected=exhaustive, raw=raw, reduced=reduced))
        reductions += reduced["atom_count"] < raw["atom_count"]
        state_saved += raw["reachable_states"]-reduced["reachable_states"]
    assert not errors, errors[:3]
    return dict(cases=cases, official_ledger_exhaustive_failures=len(errors),
                compressed_vs_raw_failures=len(errors), atom_reduced_cases=reductions,
                reachable_states_saved=state_saved,
                tested="overlapping/nonidentical windows, shared targets, repeated witnesses, initial completed targets and nonoverlap schedules",
                excluded="geometry, future invalidation, online feedback and science/Jain trajectory prices")


def window_counterexample():
    start = datetime(2026, 11, 2, 2, 0, tzinfo=timezone.utc)
    req = [dict(request_id=f"Q{i}", issued_at_utc=start+timedelta(seconds=100*i),
                deadline_utc=start+timedelta(seconds=100*(i+1)), target_ids=["T"],
                minimum_completed=1, completion_factor_threshold=.5, completion_reward=100.)
           for i in range(2)]
    ledger = BestLedger()
    ledger.record(0, "T", .6, .6, start, start+timedelta(seconds=60))
    status, reward = settle_observation_requests(req, ledger)
    col = Column(0, 60, 0, 1)
    plan = solve([col], [1, 2], [1, 1], [100, 100])
    assert reward == plan["value"] == 100 and [s["completed"] for s in status] == [True, False]
    return dict(official_reward=reward, occurrence_dp_reward=plan["value"],
                incorrect_global_target_mask_reward=200,
                completed=[s["completed"] for s in status])


def main():
    started = time.perf_counter()
    result = dict(synthetic=official_synthetic(), six_column=official_six_column(), random_audit=audit_random(),
                  window_counterexample=window_counterexample())
    result["elapsed_seconds"] = time.perf_counter()-started
    sources = [HERE / "joint_occurrence_dp.py", HERE / "micro_experiment.py"]
    sources += [OFFICIAL / "runner/challenge" / name for name in ("v4_runner.py", "v4_scorer.py", "v4_fiber_map.py")]
    result["source_sha256"] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    (HERE / "summary.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
