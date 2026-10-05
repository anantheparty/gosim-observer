#!/usr/bin/env python3
"""mkjobs.py OUT NAME PKG(local|remote path) PARAMS_JSON WORLD... : write a qrun2 job file (appends)."""
import sys, json
out, name, pkg, par = sys.argv[1:5]
worlds = sys.argv[5:]
json.loads(par)
with open(out, 'a') as f:
    for w in worlds:
        f.write(f'{name}\t{w}\t{pkg}\t{par}\n')
