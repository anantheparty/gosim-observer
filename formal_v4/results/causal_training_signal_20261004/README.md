# Train-only causal signal diagnostic, 2026-10-04

`diagnose_train_only.py` opens only the L1/L2 public initialization and four member types per L1/L2 group from the fit archive. It rejects any other payload name. It does not extract the archive, fit models, call runner, use SSH/GPU, or change actor/teacher/data files.

Run:

```sh
python3 formal_v4/results/causal_training_signal_20261004/diagnose_train_only.py
```

Outputs bind all 130 permitted member reads, archive/source hashes, 32 state rows, 127 branch rows and numerical diagnostics. The science-only program-intervention bound uses public assigned weights and official program multipliers; 22/32 realized program branches violate the fixed-physical-suffix science bound, establishing a downstream effect. This is not a cause attribution, expected-value calibration or policy improvement.

Research conclusions and a bounded, unrun 2×2 current-action/continuation-policy prototype are in `../../research/causal_training_signal_20261004.md`. The sum of oracle single-state interventions is not an achievable additive season gain. Only two natural worlds/policies are covered; L3/L4 payloads and fitted models remain unread.
