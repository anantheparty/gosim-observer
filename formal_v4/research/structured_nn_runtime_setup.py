"""Prepare an isolated Windows CUDA training runtime on the owned GPU host."""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import venv


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("Run with the Windows Python interpreter on the GPU host")
    root = pathlib.Path(args.root).resolve()
    python = root / "Scripts" / "python.exe"
    marker = root / "GOSIM_STRUCTURED_TRAINING_ENV.json"
    if root.exists() and not marker.exists():
        raise SystemExit("Refusing to modify an unmarked existing environment")
    if not root.exists():
        venv.EnvBuilder(with_pip=True).create(root)
        marker.write_text(json.dumps({"purpose": "isolated structured GOSIM student training", "torch": "2.7.1+cu128"}, indent=2))
    subprocess.run([
        str(python), "-m", "pip", "install", "torch==2.7.1",
        "--index-url", "https://download.pytorch.org/whl/cu128",
    ], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "numpy==2.2.6"], check=True)
    freeze = subprocess.check_output([str(python), "-m", "pip", "freeze"], text=True)
    (root / "requirements.freeze.txt").write_text(freeze, encoding="utf-8")
    print(json.dumps({"status": "installed", "environment": str(root), "python": str(python)}), flush=True)


if __name__ == "__main__":
    main()
