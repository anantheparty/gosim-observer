# Public-input candidate action critic experiment

Independent derivation (2026-10-03): the official terminal objective keeps each
target's maximum valid contribution, with required factor thresholds, request
quotas and Jain uniformity. A candidate's immediate gain does not charge the
future exposures displaced by its duration, nor subtract contributions that
later repetitions already recover. An ordinary neural critic can learn this
conditional opportunity cost from actual terminal interventions.

The derivation preceded reading `ALGORITHM_PORTFOLIO_ZH.md`. The portfolio audit
showed that instantaneous candidate utility prediction and behavior-policy target
survival prediction were already tried. This experiment changes the teacher to
whole candidate actions with exact terminal intervention labels. It reuses the
existing verified vector integration and scalar official scorer as engineering.

`dataset.npz` contains 5,568 candidate actions over 174 states. L1 and L2 are
training (3,776 rows), L3 validation (1,792 rows), and L4 is held out from all
training and selection. The 35 input features contain public target attributes,
public geometry, past feedback beliefs, current scores and factor lower bounds,
candidate duration, predicted gain and remaining season visibility. Card names,
target IDs, raw future quality and final validity are excluded. No LLM is used
for labels, inference or the submitted-policy prototype.

The label replaces one source exposure with a public-policy candidate at the
same absolute start, deletes source exposures overlapping its occupied interval,
and preserves later absolute starts and report times. The complete terminal
ledger is then recomputed, including actual action-count-dependent data loss,
required coverage, request windows, program multipliers and Jain uniformity.
Report-overlapping and out-of-night candidates are excluded. Stored `y` is
terminal delta divided by occupied seconds; learning and ranking use raw delta,
`y * duration_seconds`.

This is a fixed continuation teacher. It does not identify the causal effect of
the online controller's later replanning. The sparse positive labels are retained:
L1 has 20 positive alternatives, L2 25 and L3 39; the largest raw improvement is
1.643540. Large negative labels include changing the action-count-dependent loss
window. `label_summary.json` reports their distributions.

`manifest_L1.json`, `manifest_L2.json` and `manifest_L3.json` retain the original
whole-season trace hashes and all state groups. All source trace replays match
the official totals exactly. Three sampled interventions per card match native
full-season scalar replays within 1e-6. L3 includes an intervention reducing the
season from 999 to 998 exposures, and changing the invalidated observation count
from 15 to 14 while matching the scorer.

The deployment prototype freezes one source for baseline and critic. Both
enumerate the same deterministic 24-anchor public candidate pool, preserve exact
geometry and assignments, deduplicate physical actions, and use the same top 32
candidates by the existing rate. The baseline maximizes the existing utility;
the critic ranks predicted raw terminal delta with a fixed zero margin and the
exact baseline action present. The model is a 35→64→1 ordinary ReLU network,
trained for a predeclared 6,000 CUDA steps on the owned PRO6000 by the parent
research task, with L3 within-state terminal regret selecting a checkpoint.
Pure NumPy is used at deployment. All full-season gates use the unmodified
official protocol runner with a 900-second global cap.

Actual CUDA training completed in 4.124721 seconds on an NVIDIA RTX PRO 6000
Blackwell Workstation Edition. The selected checkpoint is step 2,000. L3
conditional mean terminal regret is 10.553632 and the selected actions' mean
terminal delta is -10.517812; the exact baseline action has zero delta and mean
regret 0.035820. This candidate ranking result is negative. The completed full L3 online
replay below confirms rejection. L4 was not used to rescue the failed model.

Completed full deterministic candidate baselines: L3 total 5769.301279 in
260.816 seconds; L4 total 5920.398486 in 287.977 seconds. These are candidate
enumeration effects relative to earlier timed traces, not neural improvements.

Deployment inference was changed from BLAS matmul to the trainer's explicit
NumPy einsum after the Mac implementation raised floating point warnings despite
finite, matching predictions. The final deployment forward error is exactly
zero on all dataset rows. The early interrupted critic replay is retained under
`seasons/critic/L3_interrupted_matmul_warnings`. This inference repair changes no
baseline action. `baseline_source_manifest.json` and the archived pre-repair
source preserve the exact baseline provenance.

The official full L3 online gate is also negative: baseline **5769.301279** →
critic **5441.010433**, a decline of **328.290846**. Science declines by
327.330413 and Jain uniformity by 0.960433. Both complete the whole season;
required missing remains five and request reward remains 200. The model is
rejected. L4 critic was not run, preserving that held-out card after validation
failure. There was no post-failure parameter tuning or deployment.

The conditional teacher and aggregate features do not rank opportunity costs
reliably in this experiment. This result rejects this model and construction;
it does not establish that ordinary neural networks or RL cannot help. A more
informative future experiment would use actual replanning continuation labels
and target-level competition features, while preserving card separation.

All gate outputs are under `seasons/`; the completed paired result and model
hash are recorded in `final_summary.json`. The full frozen project was moved
after gates completed to ignored `runs/hidden_learning_20261003/frozen_project`,
and manifests retain its current path and source hashes. Experimental code is in
`research/hidden_learning_{policy,dataset,agent,gate}.py`. Production files and
the Git index were not edited by this research subtask.
