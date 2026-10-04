"""Build only this experiment's library; no prior file is modified."""
import platform
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
out = ROOT / ('oracle.dylib' if platform.system() == 'Darwin' else 'oracle.so')
kind = ['-dynamiclib'] if platform.system() == 'Darwin' else ['-shared', '-fPIC']
subprocess.run(['c++', '-O3', '-std=c++17', '-ffp-contract=off', *kind,
                str(ROOT / 'oracle.cpp'), '-o', str(out)], check=True)
print(out)
