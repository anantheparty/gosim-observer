import json, sys, shutil
from pathlib import Path
sys.path.insert(0, '/tmp/hs26main')
from challenge.v4_bundle import REFERENCE, SPEC_CONFIGS, build_spec_bundle
out = Path(sys.argv[1]); spec = Path('/tmp/sophon_spec')
shutil.rmtree(spec, ignore_errors=True); shutil.rmtree(out, ignore_errors=True); spec.mkdir()
configs = {name: json.loads((REFERENCE / name).read_text()) for name in SPEC_CONFIGS}
for name in ("v4_catalog_config.json", "v4_weather_config.json"):
    configs[name]["seed"] = 4242
    configs[name]["seed_derivation"] = "sha256-v1"
cat, wx = configs["v4_catalog_config.json"], configs["v4_weather_config.json"]
cat["observability"].update(start_date="2026-10-01", end_date="2026-10-21")
wx["survey"].update(start_date="2026-10-01", end_date="2026-10-21")
cat["targets"]["total_count"] = 6000
cat["footprint"].update(total_area_deg2=1500, n_components=2, component_area_weights=[0.6, 0.4], vertices_per_component=24)
configs["v4_fiber_config.json"]["field"]["n_fibers"] = 25
for name, config in configs.items():
    (spec / name).write_text(json.dumps(config))
card = {"name": "SOPH1", "card_id": "SOPH1", "scenario_slug": "soph1", "phase": "practice", "stress": False,
        "observation_requests": {"count": 0},
        "sophon": {"message": "HI", "glyphs": {"H": ["#...#", "#...#", "#####", "#...#", "#...#"],
                                                 "I": ["#####", "..#..", "..#..", "..#..", "#####"]},
                   "multiplier": 2.5, "first_delay_nights": [1, 3], "gap_nights": [1, 2],
                   "reference": {"seeing_arcsec": 1, "transparency": 1, "sky_quality": 1,
                                 "instrument_efficiency": 1, "airmass": 1, "lunar_factor": 1}}}
(spec / "card.json").write_text(json.dumps(card))
b = build_spec_bundle(out, spec)
print('built', b)
for line in open(out / 'truth' / 'v4_sophon.jsonl'):
    print(line.strip())
