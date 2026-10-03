#!/usr/bin/env python3
"""Small cold audit. Reads only upstream source and public/config products; no card truth."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
UPSTREAM = ROOT / "upstream/gosim-observer-examples"
sys.dont_write_bytecode = True
sys.path.insert(0, str(UPSTREAM / "runner"))
from challenge.contracts import derive_stream_seed
from challenge.v4_fiber_map import radec_to_altaz
from challenge.v4_scorer import SlotTruth, WeatherTruth, score_target_exposure


def csv_rows(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def pearson(x, y):
    mx, my = statistics.fmean(x), statistics.fmean(y)
    den = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / den if den else None


def seed_keys(value, prefix=""):
    if isinstance(value, dict):
        return [prefix + str(key) for key in value if "seed" in str(key).lower()] + [
            item for key, child in value.items() for item in seed_keys(child, prefix + str(key) + ".")
        ]
    if isinstance(value, list):
        return [item for i, child in enumerate(value) for item in seed_keys(child, prefix + str(i) + ".")]
    return []


bundles = {name: UPSTREAM / "local-cards" / name for name in ("L1", "L2", "L3", "L4")}
bundles.update({name: ROOT / "practice_cards" / name / name for name in ("alpha", "beta", "gamma", "delta")})
summary = {}
catalogs = {}
inputs = {}
for name, bundle in bundles.items():
    public = bundle / "public"
    rows = csv_rows(public / "targets.csv")
    catalogs[name] = {r["target_id"]: r for r in rows}
    ids = [int(r["target_id"].replace("V4T", "")) for r in rows]
    classes = Counter(r["target_class"] for r in rows)
    required = [float(r["required"].lower() == "true") for r in rows]
    flux = [float(r["feature_flux"]) for r in rows]
    ras = [math.sin(math.radians(float(r["ra_deg"]))) for r in rows]
    decs = [math.sin(math.radians(float(r["dec_deg"]))) for r in rows]
    configs = [json.loads(path.read_text()) for path in sorted((bundle / "config").glob("*.json"))]
    summary[name] = {
        "n_targets": len(rows), "n_required": int(sum(required)), "classes": dict(classes),
        "id_dense_in_file_order": ids == list(range(1, len(rows) + 1)),
        "seed_keys_in_public_configs": [k for c in configs for k in seed_keys(c)],
        "coordinate_decimals": 6,
        "order_lag1_correlations": {"sin_ra": pearson(ras[:-1], ras[1:]), "sin_dec": pearson(decs[:-1], decs[1:]),
                                    "flux": pearson(flux[:-1], flux[1:]), "required": pearson(required[:-1], required[1:])},
        "same_class_adjacent_fraction": sum(a["target_class"] == b["target_class"] for a, b in zip(rows, rows[1:])) / (len(rows) - 1),
        "same_class_iid_marginal_fraction": sum((c / len(rows)) ** 2 for c in classes.values()),
    }
    forecasts_path, bulletins_path = public / "v4_forecasts.jsonl", public / "v4_bulletins.jsonl"
    if forecasts_path.exists() and bulletins_path.exists():
        forecast_rows = [json.loads(line) for line in forecasts_path.read_text().splitlines() if line]
        bulletin_rows = [json.loads(line) for line in bulletins_path.read_text().splitlines() if line]
        bulletin_pairs = {}
        for row in bulletin_rows:
            night = row["night_id"][1:]
            date = f"{night[:4]}-{night[4:6]}-{night[6:]}"
            for notice in row["notices"]:
                pair = (date, notice["event_kind"], notice["direction"])
                bulletin_pairs.setdefault(pair, utc(row["issued_at_utc"]))
        forecasts = []
        for row in forecast_rows:
            for notice in row["notices"]:
                for date in notice["nights"]:
                    pair = (date, notice["event_kind"], notice["direction"])
                    actual = bulletin_pairs.get(pair)
                    lead = (actual - utc(row["issued_at_utc"])).total_seconds() if actual else None
                    forecasts.append({"pair": pair, "issued_at_utc": row["issued_at_utc"], "matched_public_bulletin": actual is not None,
                                      "lead_seconds_to_first_bulletin": lead})
        positive = [r["lead_seconds_to_first_bulletin"] for r in forecasts if r["lead_seconds_to_first_bulletin"] is not None and r["lead_seconds_to_first_bulletin"] > 0]
        pairs = {tuple(r["pair"]) for r in forecasts}
        event_pairs = {p for p in bulletin_pairs if p[1] not in ("terrain_obstruction", "earthquake")}
        summary[name]["forecast_public_bulletin_check"] = {
            "n_forecast_records": len(forecast_rows), "n_forecast_night_notices": len(forecasts),
            "matching_night_kind_direction": sum(r["matched_public_bulletin"] for r in forecasts),
            "positive_warning_entries": len(positive),
            "simultaneous_publication_entries": sum(r["lead_seconds_to_first_bulletin"] == 0 for r in forecasts),
            "negative_lead_entries": sum(r["lead_seconds_to_first_bulletin"] is not None and r["lead_seconds_to_first_bulletin"] < 0 for r in forecasts),
            "median_positive_lead_hours": statistics.median(positive) / 3600 if positive else None,
            "unmatched_forecasts": [r for r in forecasts if not r["matched_public_bulletin"]],
            "unforecasted_public_non_quake_non_terrain_pairs": sorted(event_pairs - pairs),
            "caveat": "Future publications used for offline public consistency only. Online must filter issued_at <= now.",
        }
        (OUT / f"{name}_forecast_checks.json").write_text(json.dumps(forecasts, indent=2) + "\n")
    for path in sorted((bundle / "public").glob("*")) + sorted((bundle / "config").glob("*.json")):
        if path.is_file():
            inputs[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()

overlap = []
for a in bundles:
    for b in bundles:
        if list(bundles).index(b) <= list(bundles).index(a):
            continue
        common = catalogs[a].keys() & catalogs[b].keys()
        overlap.append({"a": a, "b": b, "common_target_ids": len(common),
                        "same_ra_dec_for_common_id": sum(catalogs[a][i]["ra_deg"] == catalogs[b][i]["ra_deg"] and catalogs[a][i]["dec_deg"] == catalogs[b][i]["dec_deg"] for i in common),
                        "identical_full_public_row_for_common_id": sum(catalogs[a][i] == catalogs[b][i] for i in common)})

# A runner-contract counterexample, built from public target/score/site and synthetic hidden slots.
# This does NOT read truth and does NOT claim to reproduce any v4 platform seed.
l1 = bundles["L1"]
scenario = json.loads((l1 / "config/v4_scenario.json").read_text())
score = json.loads((l1 / "config/v4_score_config.json").read_text())
night = csv_rows(l1 / "public/v4_night_calendar.csv")[0]
start = utc(night["observing_start_utc"])
site = scenario["site"]
target = next(r for r in catalogs["L1"].values() if float(r["feature_flux"]) < .3 and radec_to_altaz(float(r["ra_deg"]), float(r["dec_deg"]), start, float(site["latitude_deg"]), float(site["longitude_deg"]))[0] > 45)
target = {**target, "ra_deg": float(target["ra_deg"]), "dec_deg": float(target["dec_deg"]), "feature_flux": float(target["feature_flux"]), "science_weight": float(target["science_weight"])}
duration = 900
cases = []
for label, observable, seeing, transparency, sky, efficiency in [
    ("good", True, 1.0, .9, .9, .95), ("poor", True, 2.0, .45, .5, .6), ("background_closed", False, 0, 0, 0, 0)
]:
    slot = SlotTruth("SYNTHETIC", start, start + timedelta(seconds=duration), observable, seeing, transparency, sky, efficiency)
    weather = WeatherTruth([slot], None)
    result = score_target_exposure(target, [(duration, slot)], [], weather, duration, 1.0, score, start,
                                   lambda t: radec_to_altaz(target["ra_deg"], target["dec_deg"], t, float(site["latitude_deg"]), float(site["longitude_deg"])), site)
    cases.append({"synthetic_case": label, "factor": result.factor, "quality": result.quality, "score": result.score})

# Synthetic counterexample to "hashing alone eliminates low-entropy seed enumeration".
# The hidden value and domain here are authored by this script, unrelated to official cards.
synthetic_hidden = 2718
known_domain = range(4096)
observed = tuple(round(random.Random(derive_stream_seed(synthetic_hidden, "tiles")).random(), 6) for _ in range(1))
candidates = [seed for seed in known_domain if tuple(round(random.Random(derive_stream_seed(seed, "tiles")).random(), 6) for _ in range(1)) == observed]
synthetic_enumeration = {"domain": "0..4095 (explicit synthetic assumption)", "authored_hidden_seed": synthetic_hidden,
                         "published_synthetic_first_draw_rounded_6": observed[0], "candidate_seeds": candidates,
                         "note": "This demonstrates low-entropy dictionary enumeration. No official/public card seed was recovered."}

result = {"scope": "public/config only; no truth/teacher/platform/SSH/GPU/season", "catalogs": summary, "cross_card_common_ids": overlap,
          "state_nonuniqueness": {"basis": "same public target, site, score and empty notices; synthetic hidden slot, exact official scorer", "target_id": target["target_id"], "start_utc": start.isoformat(), "cases": cases},
          "synthetic_low_entropy_seed_check": synthetic_enumeration}
(OUT / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
(OUT / "input_manifest.json").write_text(json.dumps(inputs, indent=2) + "\n")
print(json.dumps({"catalog_counts": {n: {k: v for k, v in s.items() if k in ("n_targets", "n_required", "id_dense_in_file_order", "seed_keys_in_public_configs")} for n, s in summary.items()},
                  "forecast_checks": {n: s.get("forecast_public_bulletin_check") for n, s in summary.items() if "forecast_public_bulletin_check" in s},
                  "state_nonuniqueness": result["state_nonuniqueness"], "synthetic_low_entropy": synthetic_enumeration}, indent=2))
