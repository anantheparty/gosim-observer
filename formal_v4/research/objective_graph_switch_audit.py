#!/usr/bin/env python3
"""Privileged, fixed-exposure L2 program costs used to predeclare one teacher."""
import collections
import csv
from datetime import datetime
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "results/objective_graph_20261004"
sys.path.insert(0, str(BASE/"upstream/gosim-observer-examples"))
from runner.challenge.v4_runner import load_scenario
from runner.challenge.v4_scorer import WeatherTruth, lunar_quality_factor, program_band, program_multiplier
from runner.challenge.v4_fiber_map import radec_to_altaz

MULT = {"DARK":1.2, "BRIGHT":1.12, "BACKUP":1.06}


if __name__ == "__main__":
    card = "L2"
    scenario = load_scenario(BASE/"upstream/gosim-observer-examples/local-cards/L2/config/v4_scenario.json")
    weather = WeatherTruth(scenario.slots, None)
    targets = {t["target_id"]:t for t in scenario.targets}
    trace = BASE/"results/geometry_native_20261003/protocol_phase_control/L2"
    decisions = {int(d["observe_index"]):d for d in csv.DictReader((trace/"decisions.csv").open()) if d["action"]=="observe"}
    observations = list(csv.DictReader((trace/"observations.csv").open()))
    audit = json.loads((OUT/"program_certificate_audit.json").read_text())
    details = next(r["details"] for r in audit["records"] if r["card"]==card)
    records = []
    for rank in sorted(set(t["first_ambiguous_rank"] for t in details)):
        prior, certificate = collections.defaultdict(float), collections.defaultdict(float)
        for h in observations:
            old_rank = int(h["observe_index"])
            if old_rank >= rank:
                continue
            tid = h["target_id"]
            prior[tid] = max(prior[tid], float(h["score"]))
            certificate[tid] = max(certificate[tid], (float(h["score"])-.500001e-6)
                                   /targets[tid]["science_weight"]/MULT[decisions[old_rank]["program"]])
        action = decisions[rank]
        start = datetime.fromisoformat(action["start_utc"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(action["end_utc"].replace("Z", "+00:00"))
        old_gain = backup_gain = 0.
        old_certificates, backup_certificates = [], []
        for h in observations:
            if int(h["observe_index"]) != rank:
                continue
            tid = h["target_id"]
            target = targets[tid]
            altitude = lambda moment:radec_to_altaz(target["ra_deg"], target["dec_deg"], moment,
                         scenario.site["latitude_deg"], scenario.site["longitude_deg"])[0]
            moon = lambda moment:lunar_quality_factor(target["ra_deg"], target["dec_deg"], moment,
                                                      scenario.site, scenario.score_config)
            band = program_band(weather.band_quality(start, end, scenario.score_config, altitude, moon), scenario.score_config)
            assert abs(program_multiplier(action["program"], band, scenario.score_config)-float(h["prog_mult"])) < 1e-6
            new_score = float(h["factor"])*target["science_weight"]*program_multiplier("BACKUP", band, scenario.score_config)
            old_gain += max(0., float(h["score"])-prior[tid])
            backup_gain += max(0., new_score-prior[tid])
            if target["required"] and certificate[tid] < .5:
                if (float(h["score"])-.500001e-6)/target["science_weight"]/MULT[action["program"]] >= .5:
                    old_certificates.append(tid)
                if (new_score-.500001e-6)/target["science_weight"]/1.06 >= .5:
                    backup_certificates.append(tid)
        records.append(dict(card=card, rank=rank, start_utc=action["start_utc"], duration=int(action["duration_seconds"]),
                            original_program=action["program"], old_science_gain=old_gain, backup_science_gain=backup_gain,
                            signed_science_delta=backup_gain-old_gain, old_certificates=old_certificates,
                            backup_certificates=backup_certificates,
                            additional_certificates=sorted(set(backup_certificates)-set(old_certificates))))
    result = dict(offline_truth_band_and_factor=True, observational_fixed_exposure=True, full_continuation=False, records=records)
    (OUT/"program_certificate_switch_L2.json").write_text(json.dumps(result, indent=2)+"\n")
