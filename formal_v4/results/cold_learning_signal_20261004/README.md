# Cold learning signal, 2026-10-04

This folder contains a representation counterexample, not a trained model or a season improvement.

Run from repository root:

```sh
python3 formal_v4/results/cold_learning_signal_20261004/request_topology_probe.py
```

The script calls the current real public feature builder and official action, geometry, exposure-score and terminal-settlement functions. It does not call run_scenario, open teacher/bulk labels, train, or access remote resources. Public request topologies ab/cd and ad/bc produce exactly equal existing model inputs, while candidate ranking reverses by 100 points. A supplementary per-request member join and local threshold preserves the missing information.

The source hashes in probe_report.json cover all five unchanged structured_student modules, official dependencies, public score/fiber config, and this probe script. synthetic_inputs.json and the NPZ files retain the fixture and both old/new feature representations. The research report is ../../research/cold_learning_signal_20261004.md.

Construction failures retained:

- Initial rank0 fixture with active requests and empty ledger: build_public_features line232 created a float empty array then applied `& ledger_valid`, raising TypeError. This also exposed an empty-ledger edge case in the existing adapter; no production source was changed. The final fixture uses a genuine legal 900-second closed-slot prefix and public zero-score feedback, followed by the two compared open-slot exposures.
- After all collision/legality/settlement checks passed, the first report serialization failed because a comparison returned np.bool_. The probe now converts checks to Python bool. No model or scoring code was changed.

There was no parameter search, no measured model fit, and no bulk active-request coverage statistic. Existing model comparisons and sources remain intact.
