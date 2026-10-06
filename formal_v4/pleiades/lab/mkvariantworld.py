#!/usr/bin/env python3
"""Build an offline guider-fault world from a generated log variant (stdlib only).

Usage: mkvariantworld.py BASE_WORLD VARIANT_DIR CARD DST
Example:
  python work/mkvariantworld.py work/worlds/FA1 \
      work/logtest/variants/mixed A1 work/worlds/V_mixed_A1

Requires the V4GF-aware engine used by mkguider.py for the dynamic x0.3 first
hour / x0.005 thereafter fault behavior. This script only creates data files;
it neither imports a reader/model nor runs a simulation. DST must not exist.
Confirmed faults outside the base world's season are omitted; all log blocks
are retained verbatim, including body whitespace. Unresolved alternatives do
not become events. The season ends at the last slot's actual end, not +1 hour.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys

sys.dont_write_bytecode = True
OFFSETS = {"A1": -4.0, "B1": 2.0, "C1": -10.0, "D1": -9.0}
HEADER = re.compile(r"^#### issued ([^\r\n]+)\r?\n", re.M)


def epoch(value):
    d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError(f"Expected an explicit time zone: {value}")
    return d.timestamp()


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        if not reader.fieldnames or any(None in row for row in rows):
            raise ValueError(f"Malformed CSV: {path}")
        return reader.fieldnames, rows


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def log_blocks(path):
    text = path.read_bytes().decode("utf-8")
    headers = list(HEADER.finditer(text))
    if not headers or text[:headers[0].start()].strip():
        raise ValueError(f"No valid issued blocks: {path}")
    blocks = []
    for i, header in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        issued, body = header.group(1).strip(), text[header.end():end]
        epoch(issued)
        if not body.strip():
            raise ValueError(f"Empty log block: {issued}")
        blocks.append((issued, body))
    if any(epoch(a[0]) > epoch(b[0]) for a, b in zip(blocks, blocks[1:])):
        raise ValueError("Log blocks are not in issued-time order")
    return blocks


def merge_windows(windows):
    result = []
    for start, end in sorted((epoch(a), epoch(b)) for a, b in windows):
        if start >= end:
            raise ValueError("Flat-window end must follow start")
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result


def build(base, variant_dir, card, dst):
    base, variant_dir, dst = base.resolve(), variant_dir.resolve(), dst.absolute()
    if dst.exists() or dst.is_symlink():
        raise ValueError(f"Destination already exists; use a new DST: {dst}")
    if base == dst.resolve() or base in dst.resolve().parents:
        raise ValueError("DST must be outside BASE_WORLD")
    scenario = json.loads((base / "config/v4_scenario.json").read_text(encoding="utf-8"))
    off = float(scenario["site"].get("utc_offset_hours", 0))
    truth_path, log_path = (variant_dir / f"{card}.{suffix}" for suffix in ("truth.json", "log.txt"))
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    if truth["card"] != card or off != OFFSETS[card] or off != float(truth["utc_offset_hours"]):
        raise ValueError(f"Card/UTC-offset mismatch: base={off}, truth={truth.get('utc_offset_hours')}, card={card}")
    if truth.get("log_sha256") and sha(log_path) != truth["log_sha256"]:
        raise ValueError("Variant log/truth SHA-256 mismatch")
    logs = log_blocks(log_path)
    if truth.get("entry_count", len(logs)) != len(logs):
        raise ValueError("Variant log/truth block-count mismatch")
    if "checkpoints" in truth and [c["issued_utc"] for c in truth["checkpoints"]] != [t for t, _ in logs]:
        raise ValueError("Variant issued times do not match truth checkpoints")

    event_fields, events = read_csv(base / "truth/v4_events.csv")
    weather_fields, weather = read_csv(base / "truth/v4_weather_truth.csv")
    _, slots = read_csv(base / "truth/v4_slots.csv")
    if not weather or not slots:
        raise ValueError("Base world needs weather and slot rows")
    season_start = min(epoch(r["timestamp_utc"]) for r in slots)
    season_end = max(epoch(r["timestamp_utc"]) + float(r["duration_seconds"]) for r in slots)
    required = {"event_id", "event_type", "actual_start_utc", "actual_end_utc", "scope_type", "severity",
                "force_close", "zero_score", "seeing_multiplier", "transparency_multiplier",
                "sky_quality_multiplier", "instrument_efficiency_multiplier"}
    if not required.issubset(event_fields):
        raise ValueError(f"Missing event columns: {required - set(event_fields)}")

    old_faults = [e for e in events if e["event_type"] == "instrument_fault"]
    restored_slots = set()
    weather_times = [epoch(r["timestamp_utc"]) for r in weather]
    for fault in old_faults:
        multiplier = float(fault["instrument_efficiency_multiplier"])
        if not math.isfinite(multiplier) or multiplier <= 0:
            raise ValueError(f"Cannot undo baked fault multiplier: {fault['event_id']}")
        start, end = epoch(fault["actual_start_utc"]), epoch(fault["actual_end_utc"])
        for row, t in zip(weather, weather_times):
            if row["is_observable"] == "true" and row["instrument_efficiency"] and start <= t < end:
                row["instrument_efficiency"] = f"{min(1.0, float(row['instrument_efficiency']) / multiplier):.6f}"
                restored_slots.add(row["slot_id"])
    events = [e for e in events if e["event_type"] != "instrument_fault"]
    all_faults = sorted({epoch(t) for t in truth["faults_utc"]})
    faults = [t for t in all_faults if season_start <= t < season_end]
    existing_ids = {e["event_id"] for e in events}
    for i, start in enumerate(faults):
        row = dict.fromkeys(event_fields, "")
        row.update(event_id=f"V4GF{i + 1:04d}", event_type="instrument_fault", actual_start_utc=utc(start),
                   actual_end_utc=utc(faults[i + 1] if i + 1 < len(faults) else season_end), scope_type="ALL",
                   severity="1.000000", force_close="false", zero_score="false", seeing_multiplier="1.000000",
                   transparency_multiplier="1.000000", sky_quality_multiplier="1.000000",
                   instrument_efficiency_multiplier="0.300000")
        if row["event_id"] in existing_ids:
            raise ValueError(f"Event ID collision: {row['event_id']}")
        events.append(row)

    windows = merge_windows(truth["flats_utc"])
    starts = [a for a, _ in windows]
    flat_slots = []
    for row, t in zip(weather, weather_times):
        index = bisect_right(starts, t) - 1
        if (row["is_observable"] == "true" and row["instrument_efficiency"]
                and index >= 0 and t < windows[index][1]):
            row["instrument_efficiency"] = f"{float(row['instrument_efficiency']) * 0.005:.6f}"
            flat_slots.append(row["slot_id"])

    requests_path = base / "truth/v4_observation_requests.jsonl"
    requests = [json.loads(line) for line in requests_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not requests or not requests[0].get("target_ids"):
        raise ValueError("Base world needs a request template with at least one target")
    template = requests[0]
    request_ids = {r["request_id"] for r in requests}
    for i, (issued, body) in enumerate(logs):
        row = dict(template)
        row.update(request_id=f"V4LG{i + 1:04d}", issued_at_utc=issued, deadline_utc=utc(epoch(issued) + 86400),
                   target_ids=template["target_ids"][:1], minimum_completed=1, completion_reward=0.0, reason=body)
        if row["request_id"] in request_ids:
            raise ValueError(f"Request ID collision: {row['request_id']}; use an unmodified F-card base")
        requests.append(row)
    requests.sort(key=lambda row: epoch(row["issued_at_utc"]))
    report = {
        "schema_version": 1, "base_world": str(base), "variant_dir": str(variant_dir), "card": card,
        "utc_offset_hours": off, "log_sha256": sha(log_path), "truth_sha256": sha(truth_path),
        "season_start_utc": utc(season_start), "season_end_utc": utc(season_end),
        "removed_instrument_faults": len(old_faults), "restored_weather_slots": len(restored_slots),
        "fault_events": len(faults), "omitted_faults_outside_season": [utc(t) for t in all_faults if t not in faults],
        "alternatives_not_materialized": len(truth["alternatives_utc"]),
        "flat_windows": len(truth["flats_utc"]), "flat_weather_slots": len(flat_slots),
        "flat_slot_ids": flat_slots, "log_requests": len(logs), "total_requests": len(requests),
        "event_columns": event_fields, "request_fields": sorted(template),
        "requires_engine": "V4GF-aware engine_g (same dynamic fault convention as mkguider.py)",
    }

    # All input checks and transformations complete before creating the destination.
    shutil.copytree(base, dst)
    write_csv(dst / "truth/v4_events.csv", event_fields, events)
    write_csv(dst / "truth/v4_weather_truth.csv", weather_fields, weather)
    with (dst / "truth/v4_observation_requests.jsonl").open("w", encoding="utf-8") as fh:
        for row in requests:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    (dst / "variant_world.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{dst}: UTC{off:+g}; removed {len(old_faults)} old faults; {len(faults)} V4GF faults; "
          f"{len(flat_slots)} flat slots; {len(logs)} log requests; {len(all_faults) - len(faults)} faults outside season")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("BASE_WORLD", type=Path)
    parser.add_argument("VARIANT_DIR", type=Path)
    parser.add_argument("CARD", choices=OFFSETS)
    parser.add_argument("DST", type=Path)
    args = parser.parse_args()
    try:
        build(args.BASE_WORLD, args.VARIANT_DIR, args.CARD, args.DST)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"mkvariantworld: {exc}\n")


if __name__ == "__main__":
    main()
