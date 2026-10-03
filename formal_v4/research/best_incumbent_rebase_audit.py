"""Reconstruct selected legal cloud ledgers and describe safe finite-master rebase.

Reads only published target/scoring config and our downloaded outputs. It never
loads scenario engines, weather truth, stress plans, remote APIs, or credentials.
This is a settlement audit of four historical runs, not a new combined replay.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

EPS = Decimal("0.0000005")
SELECTION = {"alpha": "phase", "beta": "phase", "gamma": "phase", "delta": "request"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def weather_records(messages):
    return {canonical((m["record_type"], m["issued_at_utc"], m.get("slot_id"),
                       m.get("coverage_start_utc"), m.get("coverage_end_utc"))): m
            for m in messages if m["record_type"] in ("bulletin", "forecast")}


def repairs(messages):
    return [m["issued_at_utc"] for m in messages
            if m["record_type"] == "report_result" and m.get("correct") and m.get("repaired")]


def audit(root, card, selection):
    directory = root / "formal_v4/results" / f"cloud_{selection}_gpu_{card}_20261003"
    public = root / "formal_v4/practice_cards" / card / card
    target_path = public / "public/targets.csv"
    config_path = public / "config/v4_score_config.json"
    targets = rows(target_path)
    config = json.loads(config_path.read_text())
    observations = rows(directory / "observations.csv")
    decisions = rows(directory / "decisions.csv")
    messages = records(directory / "messages.jsonl")
    actions = records(directory / "actions.jsonl")
    official = json.loads((directory / "score_report.json").read_text())
    workflow = json.loads((directory / "workflow_result.json").read_text())
    observe = {int(d["observe_index"]): d for d in decisions if d["action"] == "observe"}
    observe_actions = [a for a in actions if a["action"] == "observe"]
    assert sorted(observe) == list(range(len(observe_actions)))
    valid = [r for r in observations if r["valid"] == "true"]
    invalid = [r for r in observations if r["valid"] != "true"]
    by_target = defaultdict(list)
    for row in valid:
        by_target[row["target_id"]].append(row)
    max_scores = {tid: max(Decimal(r["score"]) for r in rs) for tid, rs in by_target.items()}
    max_factors = {tid: max(Decimal(r["factor"]) for r in rs) for tid, rs in by_target.items()}
    science = sum(max_scores.values(), Decimal(0))
    score_bound = EPS * len(max_scores)
    factor_threshold = Decimal(str(config["required"]["observed_factor_threshold"]))
    required_ids = [t["target_id"] for t in targets if t["required"].lower() == "true"]
    missing = [tid for tid in required_ids if max_factors.get(tid, Decimal(0)) < factor_threshold]
    ambiguous_threshold = [tid for tid, factor in max_factors.items()
                           if factor - EPS < factor_threshold <= factor + EPS]
    assert not ambiguous_threshold, "CSV factor rounding leaves completion ambiguous"
    required_penalty = -len(missing) * float(config["required"]["penalty_per_missing"])
    requests = [m for m in messages if m["record_type"] == "observation_request"]
    request_results = []
    for request in requests:
        eligible = defaultdict(list)
        threshold = Decimal(str(request["completion_factor_threshold"]))
        for row in valid:
            d = observe[int(row["observe_index"])]
            if request["issued_at_utc"] <= d["start_utc"] and d["end_utc"] <= request["deadline_utc"]:
                eligible[row["target_id"]].append(row)
        factors = {tid: max(Decimal(r["factor"]) for r in rs) for tid, rs in eligible.items()}
        ambiguous = [tid for tid in request["target_ids"] if tid in factors
                     and factors[tid] - EPS < threshold <= factors[tid] + EPS]
        assert not ambiguous, "CSV factor rounding leaves request completion ambiguous"
        completed = [tid for tid in request["target_ids"] if factors.get(tid, Decimal(0)) >= threshold]
        reward = float(request["completion_reward"]) if len(completed) >= request["minimum_completed"] else 0.
        expected = next(r for r in official["observation_requests"] if r["request_id"] == request["request_id"])
        assert completed == expected["completed_target_ids"] and reward == expected["reward"]
        request_results.append({**request, "completed_target_ids": completed, "completed_count": len(completed),
                                "reward": reward, "witness_observe_indices": {
                                    tid: [int(r["observe_index"]) for r in eligible[tid]
                                          if Decimal(r["factor"]) >= threshold] for tid in completed}})
    width = float(config["uniformity"]["ra_band_width_deg"])
    uniform_threshold = Decimal(str(config["uniformity"]["observed_factor_threshold"]))
    band_total, band_observed = Counter(), Counter()
    for target in targets:
        band = int(float(target["ra_deg"]) // width)
        band_total[band] += 1
        band_observed[band] += max_factors.get(target["target_id"], Decimal(0)) >= uniform_threshold
    bands = {f"ra_{b*width:.0f}_{(b+1)*width:.0f}": {"targets": n, "completed": band_observed[b],
             "ratio": band_observed[b]/n} for b, n in sorted(band_total.items())}
    ratios = [b["ratio"] for b in bands.values()]
    squares = sum(r*r for r in ratios)
    jain = sum(ratios)**2/(len(ratios)*squares) if squares else 0.
    uniform_penalty = -float(config["uniformity"]["weight"]) * (1-jain)
    for name, value in bands.items():
        assert abs(value["ratio"] - official["uniformity_bands"][name]) <= float(EPS) + 1e-12
    report_decisions = [d for d in decisions if d["action"] == "report"]
    report_results = [m for m in messages if m["record_type"] == "report_result"]
    assert [d["start_utc"] for d in report_decisions] == [m["issued_at_utc"] for m in report_results]
    report_settlement = sum(float(m["score_delta"]) for m in report_results)
    assert report_settlement == official["components"]["report_settlement"]
    request_reward = sum(r["reward"] for r in request_results)
    reconstructed = float(science) + required_penalty + uniform_penalty + report_settlement + request_reward
    total_bound = float(score_bound + EPS) + 1e-9
    assert abs(reconstructed - official["total"]) <= total_bound
    assert abs(float(science) - official["components"]["sum_best_scores"]) <= float(score_bound + EPS) + 1e-9
    assert len(missing) == official["counts"]["required_missing"]
    assert len(invalid) == official["counts"]["invalidated_observations"]
    assert len(max_scores) == official["counts"]["targets_observed"]
    assert abs(uniform_penalty - official["components"]["uniformity_penalty"]) <= float(EPS) + 1e-9
    for row in observations:
        d = observe[int(row["observe_index"])]
        assert row["valid"] == d["valid"] and row["invalidated_by"] == d["invalidated_by"]
    losses = []
    for message in messages:
        if message["record_type"] != "state_resync":
            continue
        window = message["invalidated_window"]
        n, a, b = (window[k] for k in ("action_count_at_trigger", "action_index_start", "action_index_end_exclusive"))
        event = message["trigger_event_id"]
        raw_indices = sorted({int(r["observe_index"]) for r in observations if r["invalidated_by"] == event})
        assert all(a <= j < b for j in raw_indices)
        assert max(observe[j]["end_utc"] for j in range(n)) <= message["issued_at_utc"]
        losses.append({"issued_at_utc": message["issued_at_utc"], "trigger_event_id": event,
                      "invalidated_window": window, "invalidated_hit_rows": sum(r["invalidated_by"] == event for r in invalid),
                      "rank_range_half_open": [a, b], "old_prefix_observe_count_to_fix": n,
                      "prefix_end_utc": observe[n-1]["end_utc"],
                      "original_invalidated_action_intervals": [
                          {"observe_index": j, "start_utc": observe[j]["start_utc"], "end_utc": observe[j]["end_utc"]}
                          for j in range(a,b)]})
    fixed_prefix = max((loss["old_prefix_observe_count_to_fix"] for loss in losses), default=0)
    suffix_begin = max((loss["issued_at_utc"] for loss in losses), default=min(d["start_utc"] for d in decisions))
    prefix_decisions = [d for d in decisions if losses and d["end_utc"] <= suffix_begin]
    fixed_reports = [d["start_utc"] for d in report_decisions]
    schedule_end = max(d["end_utc"] for d in decisions)
    cuts = sorted({suffix_begin, schedule_end, *[t for t in fixed_reports if suffix_begin <= t <= schedule_end]})
    exchange_regions = [{"start_utc": a, "end_utc": b,
                         "old_observe_columns": sum(j >= fixed_prefix and d["start_utc"] >= a and d["end_utc"] <= b
                                                    for j,d in observe.items())}
                        for a,b in zip(cuts, cuts[1:]) if a < b]
    comparisons = []
    weather = weather_records(messages)
    for historical in sorted((root/"formal_v4/results").glob(f"cloud*_{card}_20261003")):
        if historical == directory or not (historical/"messages.jsonl").exists():
            continue
        old = records(historical/"messages.jsonl")
        old_weather = weather_records(old)
        common = weather.keys() & old_weather.keys()
        mismatch = [key for key in sorted(common) if weather[key] != old_weather[key]]
        comparisons.append({"run": str(historical.relative_to(root)), "shared_weather_record_keys": len(common),
                            "shared_weather_records_different": len(mismatch), "different_record_keys": mismatch[:20],
                            "weather_record_set_equal": weather == old_weather,
                            "only_selected_weather_keys": len(weather.keys()-old_weather.keys()),
                            "only_other_weather_keys": len(old_weather.keys()-weather.keys()),
                            "repair_times_equal": repairs(messages) == repairs(old),
                            "selected_repair_times_utc": repairs(messages), "other_repair_times_utc": repairs(old),
                            "interpretation": "Equal bulletins/forecasts are public-message consistency evidence, not proof of equal hidden weather truth or repaired efficiency."})
    by_class = defaultdict(Decimal)
    classes = {t["target_id"]:t["target_class"] for t in targets}
    for tid, value in max_scores.items():
        by_class[classes[tid]] += value
    ledger = []
    for target in targets:
        tid = target["target_id"]
        score, factor = max_scores.get(tid,Decimal(0)), max_factors.get(tid,Decimal(0))
        rs = by_target[tid]
        ledger.append({"target_id": tid, "best_score_csv": float(score), "max_factor_csv": float(factor),
                       "required": tid in required_ids, "completion_witness_observe_indices": [int(r["observe_index"]) for r in rs if Decimal(r["factor"]) >= factor_threshold],
                       "science_winner_observe_indices_csv": [int(r["observe_index"]) for r in rs if Decimal(r["score"]) == score]})
    result = {"card":card, "selected_run":str(directory.relative_to(root)), "scope":"selected historical run settlement and state rebase audit; no new official replay",
              "hidden_inputs_read":False, "global_optimality_claimed":False, "official_total":official["total"],
              "reconstructed_total_csv":reconstructed, "difference_from_official":reconstructed-official["total"],
              "CSV_science_rounding_error_bound":float(score_bound), "total_error_bound_including_official_rounding":total_bound,
              "CSV_factor_threshold_ambiguous_targets":ambiguous_threshold,
              "components":{"sum_best_scores_csv":float(science), "required_penalty":required_penalty,
                            "uniformity_penalty":uniform_penalty,"report_settlement":report_settlement,"observation_request_reward":request_reward},
              "by_class_csv":{k:float(v) for k,v in by_class.items()}, "required_target_count":len(required_ids),
              "required_missing_ids":missing, "requests":request_results, "uniformity_bands":bands,"Jain_index":jain,
              "counts":{"observe_actions":len(observe),"observation_rows":len(observations),"valid_rows":len(valid),
                        "invalidated_rows":len(invalid),"targets_with_valid_ledger_entry":len(max_scores)},
              "report_results":report_results,"fixed_report_times_utc":fixed_reports,"successful_repair_times_utc":repairs(messages),
              "data_loss_state":losses,"safe_fixed_original_prefix_observe_columns":fixed_prefix,
              "fixed_original_decision_prefix_count":len(prefix_decisions),
              "fixed_original_decision_prefix_sha256":hashlib.sha256(canonical(prefix_decisions).encode()).hexdigest() if losses else None,
              "rebase_constraints":[
                  "Retain the selected run's historical columns and their six-decimal rounding intervals; do not copy old-master columns as new-instance coefficients.",
                  "Preserve every original report timestamp and report action order, including the false-report allowance counter and successful repair history.",
                  "For data-loss cards preserve the complete original decision/action/time prefix through the delivered resync, including waits and reports; fixing only observe variables also requires excluding inserted decision boundaries that could deliver the event earlier.",
                  "Keep every pre-resync observation's rank and actual start/end times; allow new observations only after the delivered resync when using its original invalidated rank set.",
                  "No new exposure may straddle a fixed report instant. Target quality cells must be repartitioned at the selected repair times.",
                  "Science winner, largest factor, required coverage, and per-request distinct coverage are separate variables; only valid complete-window exposures contribute to REQ.",
                  "Recompute Jain uniformity from all per-band completion counts, rather than treating the old penalty as a fixed constant.",
                  "A changed pre-resync count/order must recompute the rank-based invalidation state; old invalidated score flags cannot be reused.",
                  "Equal public weather messages do not identify hidden weather truth, pointing offset, or the efficiency state of a different repair history."
              ],
              "conditional_exchange_regions_after_fixed_prefix":exchange_regions,
              "weather_public_message_comparisons":comparisons,
              "wallclock_seconds":workflow["accounted_wallclock_seconds"],"termination":official["termination"],
              "provenance":{"inputs":{str(path.relative_to(root)):sha(path) for path in [target_path,config_path,*[directory/n for n in ("observations.csv","decisions.csv","messages.jsonl","actions.jsonl","score_report.json","workflow_result.json")]]},
                            "official_output_hashes_match":all(sha(directory/f"{n}.{'jsonl' if n=='messages' else 'csv'}") == official["sha256"][n] for n in ("decisions","observations","messages"))}}
    assert result["provenance"]["official_output_hashes_match"]
    return result, ledger


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output or root/"formal_v4/results/best_incumbent_rebase_20261003"
    output.mkdir(parents=True,exist_ok=True)
    summaries = []
    for card, selection in SELECTION.items():
        result, ledger = audit(root,card,selection)
        (output/f"{card}.json").write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n")
        (output/f"{card}_target_ledger.json").write_text(json.dumps(ledger,separators=(",",":"))+"\n")
        summaries.append({"card":card,"official_total":result["official_total"],"reconstructed_total_csv":result["reconstructed_total_csv"],
                          "error_bound":result["total_error_bound_including_official_rounding"],"fixed_prefix":result["safe_fixed_original_prefix_observe_columns"]})
    summary={"cards":summaries,"historical_selected_mean":sum(r["official_total"] for r in summaries)/4,
             "combined_portfolio_official_replay_performed":False,"source_sha256":sha(Path(__file__)),"hidden_inputs_read":False}
    (output/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(summary,ensure_ascii=False))


if __name__ == "__main__":
    main()
