#!/usr/bin/env bash
# Restore the GPU's factory power limit only after the exhaustive K20 scan
# has completed successfully. Intended for the elevatia-wsl host.
set -euo pipefail

scan_session=gosim_gpu_k20_all_20260926
status_windows='C:/Users/hedge/gosim-observer-gpu-20260926/runs/gpu_k20_pairs/status.json'
windows_python=/mnt/c/Users/hedge/gosim-gpu-venv-20260926/Scripts/python.exe
nvidia_smi=/mnt/c/Windows/System32/nvidia-smi.exe

while tmux has-session -t "$scan_session" 2>/dev/null; do
    sleep 30
done

"$windows_python" -c '
import json, sys
with open(sys.argv[1], encoding="utf-8") as source:
    status = json.load(source)
if not (status.get("status") == "complete"
        and status.get("candidate_count") == 1035
        and status.get("completed_count") == 1035
        and status.get("failed_count") == 0):
    raise SystemExit("K20 scan did not complete cleanly; power limit unchanged")
print("K20 scan complete: 1035/1035, 0 failures", flush=True)
' "$status_windows"

gpu_name=$("$nvidia_smi" --query-gpu=name --format=csv,noheader | tr -d '\r')
if [[ "$gpu_name" != 'NVIDIA RTX PRO 6000 Blackwell Workstation Edition' ]]; then
    echo "Unexpected GPU $gpu_name; power limit unchanged" >&2
    exit 1
fi
default_limit=$("$nvidia_smi" --query-gpu=power.default_limit --format=csv,noheader,nounits | tr -d '\r ')
if [[ "$default_limit" != '600.00' ]]; then
    echo "Unexpected default limit $default_limit W; power limit unchanged" >&2
    exit 1
fi

"$nvidia_smi" -i 0 -pl 600
"$nvidia_smi" --query-gpu=name,power.limit,power.default_limit,power.max_limit,temperature.gpu --format=csv,noheader
