#!/usr/bin/env bash
# Run existing event-level exact LNS streams against the public practice case.
# Usage: GOSIM_PYTHON=/path/to/python bash run_rhodes_long_search.sh OUT_DIR HOURS
set -euo pipefail

if (( $# != 2 )); then
    echo "usage: $0 OUT_DIR HOURS" >&2
    exit 2
fi
run_dir=$1
hours=$2
if [[ ! $run_dir = /* || ! $hours =~ ^[0-9]+$ ]] || (( hours < 1 || hours > 24 )); then
    echo "OUT_DIR must be absolute and HOURS must be 1..24" >&2
    exit 2
fi
if [[ -e $run_dir ]]; then
    echo "refusing to overwrite existing run directory: $run_dir" >&2
    exit 2
fi

code_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
python=${GOSIM_PYTHON:-python3}
mkdir -p "$run_dir"
cp "$code_dir/results/practice_best.csv" "$run_dir/seed.csv"
date -u +%Y-%m-%dT%H:%M:%SZ > "$run_dir/started_utc.txt"
sha256sum "$run_dir/seed.csv" > "$run_dir/seed.sha256"
printf '%s\n' "$code_dir" > "$run_dir/code_dir.txt"
printf '%s\n' "$python" > "$run_dir/python.txt"
printf '%s\n' "$hours" > "$run_dir/hours.txt"

launch_worker() {
    local name=$1 seed=$2 skip=$3 size_mode=$4 first_scan=$5
    local out="$run_dir/$name"
    mkdir -p "$out"
    (
        deadline=$(( $(date +%s) + hours * 3600 ))
        input="$run_dir/seed.csv"
        for phase in 1 2; do
            if (( phase == 1 )) && [[ $first_scan != yes ]]; then
                continue
            fi
            remaining=$(( deadline - $(date +%s) ))
            if (( remaining <= 0 )); then
                break
            fi
            phase_dir="$out/phase$phase"
            mkdir -p "$phase_dir"
            rounds=1000000
            if (( phase == 1 )); then
                rounds=1
            fi
            args=(
                "$code_dir/event_subset_batch.py"
                --incumbent "$input"
                --out "$phase_dir"
                --seed "$seed"
                --rounds "$rounds"
                --max-groups 100000000
                --release-witnesses
            )
            if (( phase == 2 )); then
                args+=(--skip-groups "$skip")
            fi
            if [[ $size_mode = ten ]]; then
                args+=(--size-ten)
            fi
            printf '%q ' "$python" -u "${args[@]}" > "$phase_dir/command.txt"
            printf '\n' >> "$phase_dir/command.txt"
            if timeout --signal=TERM --kill-after=120s "${remaining}s" \
                "$python" -u "${args[@]}" > "$phase_dir/worker.log" 2>&1; then
                rc=0
            else
                rc=$?
            fi
            printf '%s\n' "$rc" > "$phase_dir/exit_code.txt"
            date -u +%Y-%m-%dT%H:%M:%SZ > "$phase_dir/finished_utc.txt"
            if (( phase == 1 )); then
                if (( rc != 0 )) || [[ ! -s $phase_dir/best.csv ]]; then
                    break
                fi
                input="$phase_dir/best.csv"
            fi
        done
        date -u +%Y-%m-%dT%H:%M:%SZ > "$out/finished_utc.txt"
    ) > "$out/launcher.log" 2>&1 &
    worker_pids+=("$!")
}

worker_pids=()
launch_worker ten_full_then_random_85001 85001 68 ten yes
launch_worker ten_random_85071 85071 68 ten no
launch_worker mixed_full_then_random_85141 85141 108 mixed yes
launch_worker mixed_random_85211 85211 108 mixed no

for pid in "${worker_pids[@]}"; do
    wait "$pid"
done

"$python" "$code_dir/collect_rhodes_long_search.py" "$run_dir"
date -u +%Y-%m-%dT%H:%M:%SZ > "$run_dir/finished_utc.txt"
