# Stabilized public season path search

Independent offline deterministic science experiment. No actor or hidden-world
imports. All old inputs are read only. The report is
`../../research/stabilized_season_path_search_20261004.md`.

Run only after root reviews SOURCE_LOCK and privately backs up these sources:

```
python build_native.py
python run_search.py --output run_L2_night08 --seconds 480
```

The output must be a NEW directory under this experiment. For an absolute cwd,
pass an absolute output path. Build the local native library on the execution
host; a Darwin binary is not a Linux library. NumPy/SciPy must be available in
the existing environment. BLAS and OpenMP are explicitly limited to one thread.
The expected placement is the same repository-relative tree as INPUT_RECEIPT;
no baseline actor package or original native library is imported.

No full-graph scan or large computation has been run before source freeze.
CONTRACTS.json contains only tiny independent mathematical checks.

Results distinguish old chronological gain, old57 globally matched gain, new
prox path gain and later block reconstruction gain. They do not represent a
formal score or stochastic expected value. Empty assigned exposures retain
their original time capacity in complete path validation.
