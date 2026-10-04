# Season pattern controller research

Current decision: retain the existing strongest actor. No actual-state candidate
passed the default finite-model adoption gate. No full season or ZIP submission.

The report is `../../research/season_pattern_controller_20261004.md`.

Local entry: `season_entry.py`, inheriting the original exact-fault actor.
Dependencies: Python3.12, NumPy, SciPy, and the local shared oracle library.
Compile for the current host with `python build_native.py`.
The entry explicitly falls back to the original actor if SciPy/native loading fails.

Research commands:

```
python contracts.py
python run_actual.py --card L1 --night 17 --seconds 35 --solve-seconds 4
python run_time_dp.py --card L2 --night 7 --seconds 60
python run_time_dp.py --card L2 --night 7 --seconds 40 --reuse-graph
python adapter_audit.py
python audit_serialized_controls.py
```

The existing successful local dependency environment is recorded in the results;
no installation was performed. Linux/native and normal formal runtime gates remain.

`FAILED_UNSHARED_INCOMPARABLE_INCUMBENTS` preserves the false +98.26 comparison;
shared concrete continuation paths reverse it and retain B.
`DEFERRED_price_overlay_controller.py` and `season_controller.py` are not imported
by the final entry. All actor inputs are public; no future truth is loaded.
