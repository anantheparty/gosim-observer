#!/usr/bin/env python3
"""Build the self-contained platform submission from the working agent source."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
FILES = (
    "minimal_agent.py",
    "decision_graph.py",
    "anomaly_detection.py",
    "scoring_preview.py",
    "state.py",
    "protocol.py",
    "my_strategy.py",
    "requirements.txt",
)


def main():
    with tempfile.TemporaryDirectory(prefix="gosim-submit-") as directory:
        target = Path(directory)
        for name in FILES:
            shutil.copy2(ROOT / "agent" / name, target / name)
        subprocess.run(
            [sys.executable, str(ROOT / "pack_agent.py"), "--agent", str(target),
             "--out", str(ROOT / "observer-deterministic.zip"), "--no-env"],
            check=True,
        )


if __name__ == "__main__":
    main()
