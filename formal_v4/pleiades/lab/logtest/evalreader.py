#!/usr/bin/env python3
"""Offline streaming evaluation of a GuiderLog-compatible reader; stdlib only.

python work/logtest/evalreader.py
python work/logtest/evalreader.py --reader work/pkgs/c31/guider_log.py:GuiderLog --by-card
python work/logtest/evalreader.py --json work/logtest/variants/eval_c31.json

Reader protocol: factory(utc_offset_hours=...), read(text, issued_epoch),
due()/probes() -> iterable of {t: UTC epoch}, flats -> {(start,end): metadata}.
--reader-kwargs passes additional constructor parameters. Use an adapter with
this protocol for an LLM reader. Evaluation never invokes an API by itself.

Fault matching is one-to-one, inclusive +/-120s by default. Candidate FP counts
unique due/probe times outside both confirmed faults and labelled alternatives.
Alternatives are unresolved, not proven negative. Flat overlap is duration IoU
of merged half-open UTC intervals (also emits duration precision and recall).
streamR is checkpoint-micro recall; streamFP counts unique erroneous candidate
times seen after any block, catching transient mistakes hidden by final state.
Empty prediction precision is N/A; an empty/empty interval comparison is 1.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left
import hashlib
import json
import math
import sys
from pathlib import Path

sys.dont_write_bytecode = True
from variants import HERE, OFFSETS, entries, epoch, load_reader


def times(items):
    result = sorted(float(x["t"] if isinstance(x, dict) else epoch(x)) for x in items)
    if not all(math.isfinite(t) for t in result):
        raise ValueError("Non-finite predicted timestamp")
    return result


def match(predicted, expected, tolerance):
    """Maximum-cardinality matching on ordered points; duplicates incur FP."""
    a, b = sorted(predicted), sorted(expected)
    i = j = 0
    matched, extra, missed = [], [], []
    while i < len(a) and j < len(b):
        if a[i] < b[j] - tolerance:
            extra.append(a[i]); i += 1
        elif a[i] > b[j] + tolerance:
            missed.append(b[j]); j += 1
        else:
            matched.append([a[i], b[j]]); i += 1; j += 1
    return matched, extra + a[i:], missed + b[j:]


def near(t, ordered, tolerance):
    i = bisect_left(ordered, t - tolerance)
    return i < len(ordered) and ordered[i] <= t + tolerance


def outside(predicted, accepted, tolerance):
    ordered = sorted(accepted)
    return sorted(t for t in set(predicted) if not near(t, ordered, tolerance))


def merge(intervals):
    result = []
    for a, b in sorted((epoch(a), epoch(b)) for a, b in intervals):
        if not (math.isfinite(a) and math.isfinite(b) and a < b):
            raise ValueError(f"Invalid interval: {a}, {b}")
        if result and a <= result[-1][1]:
            result[-1][1] = max(b, result[-1][1])
        else:
            result.append([a, b])
    return result


def overlap(predicted, expected):
    a, b = merge(predicted), merge(expected)
    i = j = 0
    intersection = 0.0
    while i < len(a) and j < len(b):
        intersection += max(0.0, min(a[i][1], b[j][1]) - max(a[i][0], b[j][0]))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return {"intersection_seconds": intersection,
            "predicted_seconds": sum(y - x for x, y in a),
            "truth_seconds": sum(y - x for x, y in b)}


def assess(reader, truth, tolerance):
    due, probes = times(reader.due()), times(reader.probes())
    faults, alternatives = times(truth["faults_utc"]), times(truth["alternatives_utc"])
    matched, extra, missed = match(due, faults, tolerance)
    accepted = faults + alternatives
    bad_candidates = outside(due + probes, accepted, tolerance)
    negative = times(truth["rumours_utc"] + truth["cancelled_utc"])
    return {"tp": len(matched), "fp": len(extra), "fn": len(missed),
            "predicted": len(due), "faults": len(faults), "probes": len(probes),
            "bad_probes": len(outside(probes, accepted, tolerance)),
            "candidate_fp": len(bad_candidates),
            "negative_hits": sum(near(t, negative, tolerance) for t in bad_candidates),
            "alternatives_as_due": sum(near(t, alternatives, tolerance) for t in extra),
            "candidate_fp_epoch": bad_candidates, "fault_fp_epoch": extra,
            "fault_fn_epoch": missed, "matched_epoch": matched,
            "flat": overlap(reader.flats, truth["flats_utc"])}


def ratios(result):
    result["recall"] = result["tp"] / result["faults"] if result["faults"] else None
    result["precision"] = result["tp"] / result["predicted"] if result["predicted"] else None
    flat = result["flat"]
    inter, pred, true = (flat[k] for k in ("intersection_seconds", "predicted_seconds", "truth_seconds"))
    flat["iou"] = inter / (pred + true - inter) if pred + true else 1.0
    flat["precision"] = inter / pred if pred else None
    flat["recall"] = inter / true if true else None
    result["stream_recall"] = result["stream_tp"] / result["stream_faults"] if result["stream_faults"] else None
    return result


def evaluate_card(directory, card, factory, kwargs, tolerance):
    truth = json.loads((directory / f"{card}.truth.json").read_text(encoding="utf-8"))
    path = directory / f"{card}.log.txt"
    if hashlib.sha256(path.read_bytes()).hexdigest() != truth["log_sha256"]:
        raise ValueError(f"Log/truth checksum mismatch: {path}")
    blocks = entries(path)
    checkpoints = truth["checkpoints"]
    if len(blocks) != len(checkpoints):
        raise ValueError(f"Checkpoint count mismatch: {path}")
    reader = factory(utc_offset_hours=truth["utc_offset_hours"], **kwargs)
    history, stream_bad = [], set()
    for (issued, text), checkpoint in zip(blocks, checkpoints):
        if issued != checkpoint["issued_utc"]:
            raise ValueError(f"Checkpoint issued timestamp mismatch: {path}")
        reader.read(text, epoch(issued))
        score = assess(reader, checkpoint, tolerance)
        history.append({"issued_utc": issued, **score})
        stream_bad.update(score["candidate_fp_epoch"])
    result = assess(reader, truth, tolerance)
    result.update(card=card, entries=len(blocks), log_sha256=truth["log_sha256"],
                  truth_sha256=hashlib.sha256((directory / f"{card}.truth.json").read_bytes()).hexdigest(),
                  stream_tp=sum(h["tp"] for h in history),
                  stream_faults=sum(h["faults"] for h in history), stream_candidate_fp=len(stream_bad),
                  stream_candidate_fp_epoch=sorted(stream_bad), checkpoints=history,
                  unparsed=len(getattr(reader, "unparsed", [])))
    return ratios(result)


def aggregate(cards):
    keys = ("tp", "fp", "fn", "predicted", "faults", "probes", "bad_probes", "candidate_fp",
            "negative_hits", "alternatives_as_due", "entries", "stream_tp", "stream_faults",
            "stream_candidate_fp", "unparsed")
    result = {k: sum(c[k] for c in cards) for k in keys}
    result["flat"] = {k: sum(c["flat"][k] for c in cards)
                      for k in ("intersection_seconds", "predicted_seconds", "truth_seconds")}
    return ratios(result)


def pct(value):
    return "   N/A" if value is None else f"{100 * value:6.1f}"


def print_row(label, r):
    print(f"{label:23s} {pct(r['recall'])} {pct(r['precision'])} "
          f"{r['tp']:4d}/{r['fn']:<4d}/{r['fp']:<4d} {r['candidate_fp']:6d} "
          f"{r['probes']:4d}/{r['bad_probes']:<4d} {pct(r['flat']['iou'])} "
          f"{pct(r['stream_recall'])} {r['stream_candidate_fp']:7d}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=HERE / "variants")
    parser.add_argument("--reader", default=str(HERE.parent / "pkgs/c31/guider_log.py") + ":GuiderLog")
    parser.add_argument("--reader-kwargs", default="{}")
    parser.add_argument("--variants", nargs="+")
    parser.add_argument("--cards", nargs="+", choices=list(OFFSETS), default=list(OFFSETS))
    parser.add_argument("--tolerance", type=float, default=120.0, help="Inclusive matching tolerance in seconds")
    parser.add_argument("--by-card", action="store_true")
    parser.add_argument("--json", type=Path, help="Optional detailed metrics JSON destination")
    args = parser.parse_args()
    if not math.isfinite(args.tolerance) or args.tolerance < 0:
        parser.error("--tolerance must be finite and non-negative")
    factory = load_reader(args.reader)
    names = args.variants or sorted(p.name for p in args.root.iterdir()
                                   if p.is_dir() and list(p.glob("*.truth.json")))
    if not names:
        parser.error("No variants found; run variants.py first")
    output = {"reader": args.reader, "tolerance_seconds": args.tolerance, "variants": {}}
    print("variant                    R%     P%   TP/FN/FP         candFP probes/bad flatIoU streamR streamFP")
    for name in names:
        cards = [evaluate_card(args.root / name, card, factory, json.loads(args.reader_kwargs), args.tolerance)
                 for card in args.cards]
        summary = aggregate(cards)
        output["variants"][name] = {"summary": summary, "cards": cards}
        print_row(name, summary)
        if args.by_card:
            for card in cards:
                print_row("  " + card["card"], card)
    print("R/P: confirmed starts, ±%gs; candFP excludes unresolved alternatives; flatIoU: duration overlap; streamFP: unique times across checkpoints." % args.tolerance)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
