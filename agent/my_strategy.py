"""Deterministic online scheduler for the GOSIM observer challenge.

The official preview supplies legal actions and their immediate values. This
module adds the marginal coverage reward and discounts terminal penalties
while there is still time to finish the corresponding obligation. It uses
only published snapshots, elementary arithmetic, and run-local memory.
"""

from datetime import datetime


def _seconds(timestamp):
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def _evenness(counts, regions):
    total = sum(counts.values())
    squares = sum(count * count for count in counts.values())
    return total * total / (regions * squares) if squares else 0.0


def _bonus(program, score_config):
    return float(score_config.get("program_bonus", {}).get(program, 0.0))


def _update_memory(snapshot, memory, score_config):
    tile_region = memory.setdefault("tile_region", {})
    for tile in snapshot.get("candidate_tiles", ()):
        tile_region[tile["tile_id"]] = tile["region_id"]

    # Feedback belongs to the previous exposure. Repeats bank only the best.
    feedback = snapshot.get("tile_last_finished")
    pending = memory.get("pending")
    if feedback and pending and feedback.get("tile_id") == pending["tile_id"]:
        key = (feedback["tile_id"], feedback.get("score"))
        if key != memory.get("last_feedback"):
            memory["last_feedback"] = key
            tile_id = feedback["tile_id"]
            realized = float(feedback.get("score") or 0.0)
            best = memory.setdefault("best_scores", {})
            previous = best.get(tile_id, 0.0)
            if realized > previous:
                memory["base_science"] = memory.get("base_science", 0.0) + (
                    realized - previous
                ) / (1.0 + _bonus(pending["program"], score_config))
                best[tile_id] = realized
    memory["pending"] = None


def _urgency_factor(candidate, raw_tile, now):
    """Discount a future penalty while its deadline is several nights away."""
    penalty = float(candidate.get("terminal_penalty_avoidance") or 0.0)
    if penalty <= 0.0 or raw_tile is None or now is None:
        return 1.0
    deadline = _seconds(raw_tile.get("available_until_utc"))
    if deadline is None:
        return 1.0
    remaining_days = max(0.0, (deadline - now) / 86400.0)
    return min(1.0, 4.0 / max(0.25, remaining_days))


def choose_action(candidates, snapshot, memory):
    """Choose the feasible observation with greatest adjusted gain per second."""
    if not candidates:
        return None

    score_config = snapshot.get("score_config") or {}
    _update_memory(snapshot, memory, score_config)
    raw = {tile["tile_id"]: tile for tile in snapshot.get("candidate_tiles", ())}
    completed = set(snapshot.get("progress", {}).get("completed_tile_ids", ()))
    counts = {region: 0 for region in snapshot.get("progress", {}).get("flexible_completed_by_region", {})}
    for tile_id in completed:
        region = memory["tile_region"].get(tile_id)
        if region is not None:
            counts[region] = counts.get(region, 0) + 1
    regions = max(1, len(counts) or 8)
    evenness = _evenness(counts, regions)
    weight = float(score_config.get("coverage_bonus_weight") or 0.0)
    if weight <= 0.0:
        return candidates[0]
    base_science = float(memory.get("base_science") or 0.0)
    now = _seconds(snapshot.get("cursor", {}).get("timestamp_utc"))

    best = candidates[0]
    best_rate = float("-inf")
    for candidate in candidates:
        tile_id = candidate["tile_id"]
        science = float(candidate.get("estimated_science_score") or 0.0)
        base = science / (1.0 + _bonus(candidate["program"], score_config))
        penalty = float(candidate.get("terminal_penalty_avoidance") or 0.0)
        penalty *= _urgency_factor(candidate, raw.get(tile_id), now)
        request = float(candidate.get("request_policy_value") or 0.0)

        if tile_id in completed:
            next_evenness = evenness
        else:
            region = candidate["region_id"]
            counts[region] = counts.get(region, 0) + 1
            next_evenness = _evenness(counts, regions)
            counts[region] -= 1
        coverage = weight * (base * next_evenness + base_science * (next_evenness - evenness))
        seconds = max(1.0, float(candidate["nominal_exptime_seconds"]))
        rate = (science + penalty + request + coverage) / seconds
        if rate > best_rate:
            best_rate, best = rate, candidate

    memory["pending"] = {"tile_id": best["tile_id"], "program": best["program"]}
    best["reason"] = ""
    return best
