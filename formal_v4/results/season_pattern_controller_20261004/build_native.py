"""Compile the small shared-incidence oracle for the current host only."""
from pathlib import Path
import platform,subprocess
root=Path(__file__).resolve().parent
darwin=platform.system()=='Darwin';output=root/('shared_oracle.dylib' if darwin else 'shared_oracle.so')
flags=['-dynamiclib'] if darwin else ['-shared','-fPIC']
subprocess.run(['c++','-O3','-std=c++17','-ffp-contract=off',*flags,str(root/'shared_oracle.cpp'),'-o',str(output)],check=True)
print(output)
