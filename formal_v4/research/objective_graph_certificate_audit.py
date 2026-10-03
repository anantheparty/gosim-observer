#!/usr/bin/env python3
"""Observational raw-factor/certificate audit of existing strong traces.

The raw factor is local scorer truth.  Public score/program alone generates the
unconditional certificate.  This measures ambiguity, not causal saved time.
"""
import collections
import csv
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "results/objective_graph_20261004"
MULT = {"DARK": 1.2, "BRIGHT": 1.12, "BACKUP": 1.06}


def audit(card):
    trace = BASE / "results/geometry_native_20261003/protocol_phase_control" / card
    catalog = BASE / "upstream/gosim-observer-examples/local-cards" / card / "public/targets.csv"
    targets = {r["target_id"]: r for r in csv.DictReader(catalog.open())}
    decisions = {int(r["observe_index"]): r for r in csv.DictReader((trace/"decisions.csv").open())
                 if r["action"] == "observe"}
    histories = collections.defaultdict(list)
    for hit in csv.DictReader((trace/"observations.csv").open()):
        if hit["valid"] == "true":
            histories[hit["target_id"]].append(hit)
    counts, details = collections.Counter(), []
    for tid, target in targets.items():
        if target["required"] != "true":
            continue
        max_factor = lower = score = 0.
        first_ambiguous = first_certificate = None
        subsequent = 0
        subsequent_science = 0.
        for hit in histories[tid]:
            rank = int(hit["observe_index"])
            multiplier = MULT[decisions[rank]["program"]]
            old_factor = max_factor
            max_factor = max(max_factor, float(hit["factor"]))
            old_score = score
            score = max(score, float(hit["score"]))
            certificate = max(0., float(hit["score"])-.500001e-6)/float(target["science_weight"])/multiplier
            lower = max(lower, certificate)
            if first_ambiguous is not None and first_certificate is None:
                subsequent += 1
                subsequent_science += max(0., float(hit["score"])-old_score)
            if old_factor < .5 <= max_factor and lower < .5:
                counts["first_truth_completion_without_certificate"] += 1
                first_ambiguous = rank
            if lower >= .5 and first_certificate is None:
                first_certificate = rank
        if max_factor >= .5:
            counts["final_truth_complete"] += 1
        if max_factor >= .5 and lower < .5:
            counts["final_truth_complete_without_certificate"] += 1
        if first_ambiguous is not None:
            counts["ambiguous_then_revisited"] += bool(subsequent)
            counts["ambiguous_subsequent_hits_until_certificate"] += subsequent
            details.append(dict(target=tid, first_ambiguous_rank=first_ambiguous,
                                first_certificate_rank=first_certificate, subsequent_hits=subsequent,
                                subsequent_science_gain=subsequent_science, final_truth_factor=max_factor,
                                final_certificate_lower=lower))
    return dict(card=card, counts=dict(counts), details=details,
                loss_filter="final valid-only; does not reconstruct pre-resync certificate timeline",
                source_sha256={name:hashlib.sha256((trace/name).read_bytes()).hexdigest()
                               for name in ("actions.jsonl", "observations.csv", "decisions.csv", "score_report.json")})


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    records = [audit(card) for card in ("L1", "L2", "L3", "L4")]
    result = dict(hypothesis="program controls raw-factor identifiability through public score upper multiplier",
                  offline_factor_truth=True, observational_not_causal=True, records=records,
                  audit_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT/"program_certificate_audit.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps([dict(card=r["card"], counts=r["counts"]) for r in records], indent=2))
