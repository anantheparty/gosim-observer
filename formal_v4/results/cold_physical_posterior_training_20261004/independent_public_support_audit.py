"""Read-only cal/val physical-support audit; never loads test data or worlds.

Run with a Python environment containing NumPy. Writes only the two audit
artifacts beside this script. No fitted model, source lock or data is modified.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from physical_core import DIRS, HISTORY, KINDS, TOKEN_DIM, Predictor


ROOT = Path(__file__).resolve().parent
COARSE = {
    "rainy": "rain", "cloudy": "overcast", "smoggy": "haze",
    "cold_wave": "cold_snap", "tornado": "storm",
    "rocket_launch": "rocket_launch", "terrain_obstruction": "terrain_obstruction",
}
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def sha(name):
    return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()


def event_direction(event):
    center = (event["az0"] + ((event["az1"] - event["az0"]) % 360) / 2) % 360
    return COMPASS[int((center + 22.5) // 45) % 8]


def summarize(compatible, probabilities):
    incompatible_mass = (probabilities * ~compatible).sum(axis=1)
    counts = compatible.sum(axis=1)
    return {
        "rows": len(probabilities),
        "zero_matching_classes": int((counts == 0).sum()),
        "zero_matching_fraction": float((counts == 0).mean()),
        "matching_class_count_quantiles_0_50_90_100": np.quantile(counts, [0, .5, .9, 1]).tolist(),
        "incompatible_mass_quantiles_0_50_90_99_100": np.quantile(incompatible_mass, [0, .5, .9, .99, 1]).tolist(),
    }


def run():
    bank = json.loads((ROOT / "physical_bank.json").read_text())
    model = Predictor(ROOT / "physical_model.npz")
    data = np.load(ROOT / "fit_data.npz")
    terrain = np.zeros((len(bank), len(DIRS)), dtype=np.uint8)
    current_directional = np.zeros((len(bank), len(KINDS), len(DIRS)), dtype=np.uint8)
    for k, path in enumerate(bank):
        for event in path["events"]:
            kind = COARSE[event["kind"]]
            direction = DIRS.index(event_direction(event))
            if kind == "terrain_obstruction":
                terrain[k, direction] = 1
            # Formal generated directional events have slot-aligned boundaries.
            # The current bulletin publishes overlap with [0,900), not coverage
            # of the commanded field, so event direction is a global notice.
            elif event["start"] < 900 and event["end"] > 0:
                current_directional[k, KINDS.index(kind), direction] = 1

    healthy = np.asarray([path["fault"][0] == 0 for path in bank])
    closed = np.asarray([path["o"][0] == 0 for path in bank])
    out = {
        "scope": "Only cal/val features, frozen model and independent synthetic prototype bank; no test data, actual private truth, world reconstruction or fitting.",
        "formulas": {
            "physical_C": "C_k = transparency_k * sky_quality_k / (seeing_k * q0)",
            "band_quality": "B_i,e = sum_p span_p * O_k(p) * C_k(p) * H_i(t_p) / T_e; slot-boundary <=120-second mesh",
            "science_quality": "Q_i,e = sum_p span_p * O_k(p) * C_k(p) * E_k(p) * directional_attenuation_i(t_p) * H_i(t_p) / T_e; slot and per-path event boundaries then <=120-second mesh",
            "public_score": "round(weight_i * min(1, flux_i*T_e*Q_i,e/(f0*T0)) * program_multiplier(B_i,e), 6)",
            "direction": "center=(az0+((az1-az0)%360)/2)%360; index=floor((center+22.5)/45)%8",
            "terrain_compatibility": "deduplicated coarse terrain direction set of bank path == terrain direction set in current public query tail",
            "directional_weather_compatibility": "deduplicated non-ALL weather/rocket notices from path events overlapping first slot == current public query non-ALL weather/rocket notices",
            "incompatible_mass": "sum_k p(k|x) * 1[path k incompatible with public evidence]",
            "report_compatibility": "same-timestamp true OR false report => unrepaired active fault flag in current slot == 0",
            "force_close_compatibility": "current ALL rain OR storm => first-slot open flag == 0, conditional on this experiment's frozen reference weather config",
        },
        "qualification": {
            "terrain": "Permanent terrain sectors are all announced on the opening bulletin, with coarse directions deduplicated; all are retained in every five-slot path.",
            "directional_weather": "Exact non-ALL notice-set condition uses this experiment's slot-aligned official generated event spans. ALL weather events are not stored as path event records and cannot be audited by this equality.",
            "force_close": "This is a conditional reference-config check, not a universal all-task-card rule. Numeric weather generation config is absent from initialize.",
            "interpretation": "Incompatible mass is a support violation relative to public evidence. Zero matching classes cannot be fixed by a probability hard mask without extending or transforming the dictionary.",
        },
        "source_review": {
            "future_leak": "No actual future truth use found in PublicHistory inputs or candidate_fields assignment. Host future path is confined to supervision/projection/realized values. All-path scoring groups each prototype's event-boundary signature independently, avoiding host truth changing prototype quadrature.",
            "five_slots": "Slot-origin-relative event relocation and separate band/science meshes match reviewed official operator for <=3600-second night-clipped candidates. Existing operator_gate: 1743 checks, max error 8.881784197001252e-16; that gate does not validate posterior support.",
            "report": "path restoration divides only repaired fault multipliers, clips E to 1 and preserves quake/jitter. Predictor has same-timestamp healthy support mask. evaluate.py:79 excludes these immediate-post-report rows from the regret-query subset.",
            "assignment_scope": "evaluate.py:19 uses source field-0 assignments without zero-offset nominal-hit filtering. Public-design cache contains 2 such target misses among 13404 L1 assigned candidates and 2 among 14900 L2 candidates; predicted path values presume all candidates hit. Host actual offset affects realized value only, as declared.",
            "source_lock": "Reviewed sources match SOURCE_LOCK. SAMPLING_LOCK's initial physical_operator hash differs; SOURCE_LOCK records its authorized equivalence-preserving amendment.",
        },
        "classes": len(bank),
        "hashes_sha256": {name: sha(name) for name in [
            "physical_model.npz", "physical_bank.json", "bank_features.npy", "fit_data.npz",
            "physical_core.py", "world.py", "build_data.py", "physical_operator.py",
            "evaluate.py", "SAMPLING_LOCK.json", "SOURCE_LOCK.json",
            "official/challenge/v4_weather_simulator.py",
            "official/challenge/reference/v4/v4_weather_config.json",
            "independent_public_support_audit.py",
        ]},
        "splits": {},
    }
    origin = HISTORY * TOKEN_DIM
    for split in ["cal", "val"]:
        x = data[split + "_x"]
        probabilities = model.probabilities(x)
        observed = x[:, origin + 16:origin + 16 + len(KINDS) * len(DIRS)].reshape(-1, len(KINDS), len(DIRS)) > .5
        terrain_compatible = np.all(terrain[None, :, :] == observed[:, None, KINDS.index("terrain_obstruction"), :], axis=2)
        weather_observed = observed.copy()
        weather_observed[:, KINDS.index("terrain_obstruction"), :] = False
        weather_observed[:, KINDS.index("earthquake"), :] = False
        weather_observed[:, :, DIRS.index("ALL")] = False
        weather_compatible = np.all(current_directional[None, :, :, :] == weather_observed[:, None, :, :], axis=(2, 3))
        same_report = x[:, origin + 9] > .5
        report_mass = (probabilities[same_report] * ~healthy).sum(axis=1)
        force_close = observed[:, KINDS.index("rain"), DIRS.index("ALL")] | observed[:, KINDS.index("storm"), DIRS.index("ALL")]
        force_mass = (probabilities[force_close] * ~closed).sum(axis=1)
        out["splits"][split] = {
            "terrain": summarize(terrain_compatible, probabilities),
            "current_directional_weather": summarize(weather_compatible, probabilities),
            "terrain_and_current_directional_weather": summarize(terrain_compatible & weather_compatible, probabilities),
            "same_timestamp_report": {
                "rows": int(same_report.sum()),
                "active_fault_mass_max": float(report_mass.max()) if len(report_mass) else None,
                "finite_probabilities": bool(np.isfinite(probabilities[same_report]).all()),
            },
            "reference_ALL_force_close": {
                "rows": int(force_close.sum()),
                "open_slot_mass_quantiles_0_50_90_100": np.quantile(force_mass, [0, .5, .9, 1]).tolist() if len(force_mass) else None,
                "closed_classes": int(closed.sum()),
            },
        }
    (ROOT / "independent_public_support_audit.json").write_text(json.dumps(out, indent=2) + "\n")
    paragraphs = [
        "# Independent public support audit", "",
        "This audit reads only frozen cal/val features, the fitted model and the independent synthetic prototype bank. It does not open test data, reconstruct worlds or modify the model.", "",
        "For each path, sector center maps to the same eight-point compass direction as the official publication. Terrain support requires the entire deduplicated permanent terrain direction set to equal the opening bulletin's set carried in the query tail. Incompatible posterior mass is the sum of probabilities of paths violating that condition.", "",
        "The reviewed score operator uses C = transparency × sky_quality / (seeing × q0), B = mean(O × C × H), and Q = mean(O × C × E × directional attenuation × H), followed by weight × min(1, flux × duration × Q / (f0 × T0)) × program multiplier. Band and science use their distinct official integration meshes; only factor is capped.", "",
    ]
    for split, result in out["splits"].items():
        r = result["terrain"]
        weather = result["current_directional_weather"]
        both = result["terrain_and_current_directional_weather"]
        report = result["same_timestamp_report"]
        force = result["reference_ALL_force_close"]
        paragraphs.extend([
            f"{split}: {r['zero_matching_classes']}/{r['rows']} queries ({100*r['zero_matching_fraction']:.2f}%) have no terrain-compatible class. Incompatible terrain mass quantiles at 0/50/90/99/100%: {r['incompatible_mass_quantiles_0_50_90_99_100']}.", "",
            f"Current non-ALL weather/rocket notice sets: {weather['zero_matching_classes']}/{weather['rows']} queries have no matching class; joint terrain/current-directional support: {both['zero_matching_classes']}/{both['rows']} have no matching class.", "",
            f"Same-timestamp report: {report['rows']} queries, maximum unrepaired current-fault probability {report['active_fault_mass_max']}; finite probabilities {report['finite_probabilities']}.", "",
            f"Reference ALL rain/storm closure: {force['rows']} queries; open-slot posterior mass quantiles at 0/50/90/100%: {force['open_slot_mass_quantiles_0_50_90_100']}.", "",
        ])
    paragraphs.extend([
        "The classifier has an exact healthy mask after a same-timestamp true or false report. It has no equivalent public-notice support filter. With an empty compatible dictionary, adding a hard mask alone would leave zero probability mass. These results qualify the output as an empirical physical-path classifier with incomplete conditional support, not a posterior satisfying all public evidence.", "",
        "The non-ALL notice equality assumes the slot-aligned official event generation used by this experiment. The ALL rain/storm closure check depends on the frozen reference force_close settings and is not a universal rule for arbitrary task cards. The bank does not retain ALL weather-event descriptors, so other current ALL weather notices cannot be audited by event-set equality.", "",
        "Source review found no actual future truth entering PublicHistory or common candidate assignment. Future host paths are used for labels/projection/realized value, while prototype quadrature is grouped by each path's own event boundaries. The five-slot operator already has 1743 official checks with maximum error 8.881784197001252e-16; this numerical gate does not establish conditional-support correctness. Repair divides only repaired fault multipliers and preserves quake/jitter, but immediate-post-report rows are excluded from the evaluation regret subset (evaluate.py:79).", "",
        "A small candidate-geometry limitation remains: field 0 retains source assignments without filtering known zero-offset nominal misses (evaluate.py:19). The frozen cache has 2 such target misses among 13404 L1 candidates and 2 among 14900 L2 candidates. Predicted path scores assume those assignments hit; actual offset is applied only to realized value, as declared. Reviewed sources match SOURCE_LOCK; its documented operator amendment explains the initial SAMPLING_LOCK hash difference.", "",
        "Reproduction: run `independent_public_support_audit.py` with NumPy from this directory. Exact input/source/model/bank hashes and all statistics are in `independent_public_support_audit.json`. No test results enter either artifact.", "",
    ])
    (ROOT / "independent_public_support_audit.md").write_text("\n".join(paragraphs))
    print(json.dumps(out["splits"], indent=2))


if __name__ == "__main__":
    run()
