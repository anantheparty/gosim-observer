"""Check CUDA availability and basic numerical execution, without survey training."""
from __future__ import annotations

import argparse
import json
import pathlib
import platform
import time

import numpy as np
import torch


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    torch.set_num_threads(2)
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is unavailable")
    expected = "NVIDIA RTX PRO 6000 Blackwell Workstation Edition"
    assert torch.cuda.get_device_name(0) == expected
    a = np.arange(256, dtype=np.float64).reshape(16, 16) / 256
    b = np.sin(np.arange(256, dtype=np.float64)).reshape(16, 16)
    start = time.perf_counter()
    x = torch.tensor(a, device="cuda", requires_grad=True)
    y = torch.tensor(b, device="cuda")
    product = x @ y
    product.square().mean().backward()
    torch.cuda.synchronize()
    error = float(np.max(np.abs(product.detach().cpu().numpy() - a @ b)))
    assert error < 1e-10
    assert bool(torch.isfinite(x.grad).all())
    prop = torch.cuda.get_device_properties(0)
    report = {
        "status": "CUDA_RUNTIME_READY_NO_SURVEY_MODEL_TRAINED",
        "python": platform.python_version(), "torch": torch.__version__,
        "numpy": np.__version__, "cuda": torch.version.cuda,
        "device": prop.name, "capability": [prop.major, prop.minor],
        "compiled_arches": torch.cuda.get_arch_list(),
        "device_memory_bytes": prop.total_memory,
        "numeric_max_absolute_error": error,
        "backward_finite": True, "seconds_with_initialization": time.perf_counter()-start,
    }
    pathlib.Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
