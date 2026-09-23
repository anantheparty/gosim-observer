#!/usr/bin/env python3
"""Build the self-contained observer package from versioned agent source."""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
FILES = (
    "model_policy.py",
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
        (target / "minimal_agent.py").write_text(
            "from model_policy import run\n"
            "\n"
            "if __name__ == '__main__':\n"
            "    run()\n",
            encoding="utf-8",
        )
        subprocess.run(
            [sys.executable, str(ROOT / "pack_agent.py"), "--agent", str(target),
             "--out", str(ROOT / "observer-agent.zip"), "--no-env"],
            check=True,
        )


if __name__ == "__main__":
    main()
