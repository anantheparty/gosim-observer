"""Bounded CPU pilot using only public footprint and target catalogue files.

Recovers Fourier phases of the published footprint and tests a narrow set of
candidate master seeds against public generator RNG consumption. This is not a
generic secret-seed attack and does not access any server or truth-side products.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import sys
import tempfile
import time

import numpy as np

CLASSES = ("ELG", "BGS", "LRG", "QSO", "Star")
TWO_PI = 2 * math.pi


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def public_footprint(path):
    grouped = {}
    with Path(path).open() as handle:
        for row in csv.DictReader(handle):
            grouped.setdefault(row["component_id"], []).append(
                (int(row["vertex_index"]), float(row["ra_deg"]), float(row["dec_deg"])))
    result = []
    for key, vertices in sorted(grouped.items()):
        vertices.sort()
        if len(vertices) % 4:
            raise ValueError("phase reconstruction needs the published quarter-turn vertex")
        ra0 = vertices[0][1]
        quarter = vertices[len(vertices) // 4]
        dec0 = math.degrees(math.atan(math.tan(math.radians(quarter[2]))
                    / math.cos(math.radians(quarter[1] - ra0))))
        ra, dec = np.deg2rad(np.asarray([(r, d) for _, r, d in vertices]).T)
        vectors = np.column_stack((np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)))
        a, d = math.radians(ra0), math.radians(dec0)
        center = np.asarray([math.cos(d)*math.cos(a), math.cos(d)*math.sin(a), math.sin(d)])
        radii = np.arccos(np.clip(vectors @ center, -1, 1))
        transform = np.fft.rfft(radii)
        relative_amplitudes = 2 * np.abs(transform[1:]) / len(vertices) / radii.mean()
        order = int(np.max(np.flatnonzero(relative_amplitudes > 1e-5)) + 1)
        phases = np.angle(transform[1:order+1]) % TWO_PI
        result.append({"component_id": key, "vertices": len(vertices),
                       "center_ra_deg": ra0, "center_dec_deg": dec0,
                       "harmonic_order": order, "phases_rad": phases.tolist(),
                       "relative_amplitudes": relative_amplitudes[:order].tolist(),
                       "higher_amplitude_max": float(relative_amplitudes[order:].max(initial=0))})
    return result


def stream(seed, hashed=True):
    if not hashed:
        return random.Random(int(seed))
    digest = hashlib.sha256(f"{int(seed)}:v4.catalog".encode()).digest()
    return random.Random(int.from_bytes(digest[:16], "big"))


def phase_signature(seed, center_pool, components, harmonics, hashed):
    rng = stream(seed, hashed)
    rng.sample(range(center_pool), components)
    phases = []
    for _ in range(components):
        phases.extend(rng.uniform(0, TWO_PI) for _ in range(harmonics))
        for _ in range(harmonics):
            rng.random() # Harmonic amplitude draws; magnitude does not affect RNG consumption.
    return phases, rng


def class_signature(rng, target_rows):
    counts = collections.Counter(row["target_class"] for row in target_rows)
    roster = [name for name in CLASSES for _ in range(counts[name])]
    rng.shuffle(roster)
    return roster


def error(observed, predicted):
    observed = np.asarray(observed)
    predicted = np.asarray(predicted)
    return float(np.max(np.abs((observed-predicted+math.pi) % TWO_PI-math.pi)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-repo", type=Path, required=True)
    parser.add_argument("--cards", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-seed", type=int, default=10000)
    parser.add_argument("--max-center-pool", type=int, default=16)
    args = parser.parse_args()
    began = time.monotonic()
    sys.path.insert(0, str(args.official_repo.resolve()))
    from challenge import v4_catalog_generator
    spec_path = args.official_repo / "scripts/make_v4_demo_card.py"
    spec = importlib.util.spec_from_file_location("public_demo_config", spec_path)
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    demo_root = args.official_repo / "archive/starter_kit_v4/cards/demo/public"
    demo_fp = public_footprint(demo_root / "footprint.csv")
    observed_demo = sum((c["phases_rad"] for c in demo_fp), [])
    predicted, rng = phase_signature(demo.DEMO_SEED, len(demo.CATALOG["footprint"]["component_centers"]),
                                      len(demo_fp), len(demo.CATALOG["footprint"]["harmonic_amplitude_ranges"]), True)
    with (demo_root / "targets.csv").open() as handle:
        demo_rows = list(csv.DictReader(handle))
    predicted_classes = class_signature(rng, demo_rows)
    required_indices = {i for i,row in enumerate(demo_rows) if row["required"] == "true"}
    predicted_required = set(rng.sample(range(len(demo_rows)),len(required_indices)))
    control = {"known_public_seed": demo.DEMO_SEED, "phase_max_error_rad": error(observed_demo,predicted),
               "all_target_classes_exact": predicted_classes == [row["target_class"] for row in demo_rows],
               "all_required_flags_exact": predicted_required == required_indices}
    with tempfile.TemporaryDirectory(prefix="gosim-public-seed-positive-control-") as temporary:
        work = Path(temporary)
        config = work / "catalog.json"
        config.write_text(json.dumps(demo.CATALOG))
        v4_catalog_generator.generate_catalog(config, work / "generated")
        generated = work / "generated" / "targets.csv"
        with generated.open() as handle:
            regenerated_rows = list(csv.DictReader(handle))
        control.update(first_target_exact=regenerated_rows[0] == demo_rows[0],
                       full_targets_sha_exact=sha(generated) == sha(demo_root/"targets.csv"),
                       full_footprint_sha_exact=sha(work/"generated/footprint.csv") == sha(demo_root/"footprint.csv"))
    cards = {}
    for name in ("alpha","beta","gamma","delta"):
        root = args.cards / name / name
        fp = public_footprint(root/"public/footprint.csv")
        with (root/"public/targets.csv").open() as handle:
            rows = list(csv.DictReader(handle))
        with (root/"public/v4_night_calendar.csv").open() as handle:
            nights = list(csv.DictReader(handle))
        cards[name] = {"footprint":fp,"rows":rows,
                       "observed_phases":sum((c["phases_rad"] for c in fp),[]),
                       "first_night":nights[0]["night_date"],"last_night":nights[-1]["night_date"],
                       "public_file_sha256": {rel:sha(root/rel) for rel in (
                           "public/footprint.csv","public/targets.csv","public/v4_night_calendar.csv",
                           "config/v4_scenario.json","config/v4_fiber_config.json","config/v4_score_config.json")}}
    public_dates = {20260929,202610,20261101,20261108,20261115,20261122}
    public_dates.update(20261000+day for day in range(1,32))
    public_dates.update(int(card["first_night"].replace("-","")) for card in cards.values())
    seeds = sorted(set(range(args.max_seed+1)) | public_dates)
    modes = (True,False)
    tolerance = 1e-4
    hits = []
    checks = 0
    for seed in seeds:
        for hashed in modes:
            for pool in range(3,args.max_center_pool+1):
                predicted, _ = phase_signature(seed,pool,3,3,hashed)
                checks += len(cards)
                for name,card in cards.items():
                    if error(card["observed_phases"],predicted) < tolerance:
                        _,rng = phase_signature(seed,pool,3,3,hashed)
                        classes = class_signature(rng,card["rows"])
                        hits.append({"card":name,"candidate_seed":seed,"center_pool_size":pool,
                                     "derivation":"sha256-v1" if hashed else "legacy",
                                     "phase_error_rad":error(card["observed_phases"],predicted),
                                     "all_target_classes_exact":classes==[row["target_class"] for row in card["rows"]]})
    result = {"schema":"public-catalog-seed-pilot-v1","scope":"only public/config files; no truth or server reads",
              "official_source_commit":"e01939d060f304c2a7cf04d9b3e46009b564fc23",
              "generator_sha256":sha(args.official_repo/"challenge/v4_catalog_generator.py"),
              "positive_control":control,"seed_count":len(seeds),"small_integer_seed_range":[0,args.max_seed],
              "additional_public_date_candidates":sorted(set(seeds)-set(range(args.max_seed+1))),
              "center_pool_range":[3,args.max_center_pool],"modes":["sha256-v1","legacy"],
              "phase_tolerance_rad":tolerance,"card_signature_checks":checks,"matches":hits,
              "elapsed_seconds":round(time.monotonic()-began,3),
              "cards":{name:{k:v for k,v in card.items() if k not in ("rows","observed_phases")} for name,card in cards.items()},
              "unresolved_parameters":["master seed entropy/range","candidate center pool size outside tested range",
                 "possible generator version or RNG consumption changes","catalog clustering centers/count/sigma",
                 "exact flux distributions and rejection/window config","weather/request stream generator config"]}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:result[k] for k in ("positive_control","seed_count","card_signature_checks","matches","elapsed_seconds")},ensure_ascii=False))


if __name__ == "__main__":
    main()
