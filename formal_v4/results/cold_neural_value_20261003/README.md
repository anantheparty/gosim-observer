# Independent delayed-value NN experiment, 2026-10-03

The first traditional NN experiment is reproducible and **does not improve the
current production policy**. It was designed from the public guide/scorer/runner
before reading existing research or policy. Production was read only after the
independent model had been trained and the L3 official comparisons had finished.

## What was trained

`research/cold_neural_value.py` generates randomized full-season continuations
from public local cards. A 14→48→32→2 MLP predicts (1) eventual target completion
and (2) remaining science contribution if that target is deferred. These are
rollout endpoint labels, not a fit of the instantaneous exposure formula.

Inputs: flux, weight, required flag, current factor/best score, remaining public
geometric visibility, future geometric quality, current altitude, nearby unmet
required demand, remaining-capacity pressure, RA-band completion, overall
completion, season fraction left, and nearby unfinished demand. NN inference uses
only these public/state inputs. Future practice truth was never read.

Training split is whole-card L1/L2; L3 is validation; L4 is held out from data and
training. There are 132,096 train and 26,208 validation samples from 19 randomized
episodes. Training takes 0.99s on the local CPU with two PyTorch threads. The 2,354
parameter network exports to a 10KB NumPy model, so deployed inference needs no
PyTorch or LLM. GPU installation was unnecessary.

Validation Brier is 0.0500 overall, 0.0822 on unfinished targets, and 0.0636 on the
343 unfinished required samples. These are probability diagnostics and **are not
GOSIM score improvements**. Training uses static spatial groups rather than exact
fibers, and omits events, stress, request rewards and report decisions. This makes
it a preliminary deferred-value estimator, not a full terminal-score critic.

## Official full-season evaluation

The independent control uses exact gnomonic assignments but fixed 900-second
exposures, a generic weather expectation and no pointing calibration. It is a
deliberately limited baseline and cannot substitute for the production policy.
Each run uses the unmodified official `v4_runner.run_scenario`; all reached
`survey_complete`.

| Card | Greedy | NN discount | NN scarcity bonus |
|---|---:|---:|---:|
| L3 validation | 571.966629 | 545.104828 | 564.393890 |
| L4 heldout | -842.501869 | -1622.084580 | -1991.088041 |

The discount variant reduces immediate required priority by predicted future
completion probability. Its L3 science gain +122.10 and request gain +100 are
outweighed by five additional missing required targets (-250). The bonus variant
retains the original required reward and adds scarcity pressure; it also fails
to improve. The bonus version was selected as the less damaging L3 variant
before inspecting either L4 result. A first L4 discount run had already executed
but was not inspected before this choice; both variants are reported here.

For context, the established CPU production results recorded in the repository
are L1 6096.185388, L2 6534.787015, L3 5633.730701, L4 5869.556485. No production
change, submission ZIP change, Git-index change, or platform evaluation was made.

## Reproduce

```sh
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 formal_v4/research/cold_neural_value.py generate --episodes 8
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 formal_v4/research/cold_neural_value.py train --epochs 24
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 formal_v4/research/cold_neural_value.py evaluate --cards L3 L4 --control discount
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 formal_v4/research/cold_neural_value.py evaluate --cards L3 L4 --control boost
```

The two runs overwrite `official_summary.json` with their own compact summary;
raw `official_{mode}_{control}_{card}/score_report.json` remains authoritative.
Original first-run folders without a control suffix are retained.

## Controlled production integration: rejected

`cold_neural_policy.py` keeps production geometry, feedback beliefs, ledger resync,
program multipliers, duration breakpoints and request quota assignment. Its isolated
subclass changes only the continuation urgency supplied to `_evaluate`, adding
`0.3 * unfinished_required * (1 - predicted_future_completion)`.

| L3 official same-source run | Total | Seconds | Science | Required missing | Requests |
|---|---:|---:|---:|---:|---:|
| Baseline | 5701.591442 | 130.83 | 5753.579627 | 5 | 2/2 |
| Preliminary NN hook | 5544.336893 | 156.17 | 5696.720574 | 5 | 1/2 |

The difference is **-157.254549**: science -56.859053, request -100, and uniformity
-0.395495. Both reached `survey_complete`; the hook is rejected. No strength sweep
was performed. The startup import failure is retained separately and excluded
from comparison. The frozen executable copy is under ignored
`runs/cold_neural_value_20261003/production_frozen`; only its Git revision and
per-file SHA256 manifest are retained in this results directory. This is the
baseline for this experiment; the README's historical scores used another run.

## Actual strong-trajectory teacher: completed

`cold_neural_trajectory_teacher.py` reads six complete **public local** L1--L3
trajectories and records 550,741 target states plus 2,883 global states. L1/L2
training has 306,988 samples; whole-card L3 validation has 243,753. L4 is unused.
The 18→64→48→2 network has 4,434 parameters and was actually trained for 30 epochs
in 5.48 CPU seconds after data generation. It jointly predicts terminal completion
and **signed remaining science**, including negative changes after data loss.
Request membership/deadline and recent score-derived quality are additional
public inputs. This model has not been inserted into production or score-tested.

The global label is actual final total minus prefix settlement reconstructed from
the valid ledger at that moment, including required, Jain, issued completed
requests and reports. Future final validity never alters input history early:
resync is applied only after its published time. Current completion input uses the
conservative `score/(weight*1.2)` bound. Raw factors and final validity are used
only for labels. All six final required counts match their official reports.

`cold_neural_teacher_audit.py` independently settles 30 prefixes through official
`BestLedger`, `required_penalty`, `uniformity_penalty` and request settlement.
Maximum error is **0.0006524**, within the 0.02 CSV/float precision tolerance.
These samples identify continuation under their recorded behavior policy; they
do not identify the causal value of skipping or selecting an alternative action.
Multiple states within a card/trajectory are correlated.

```sh
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 python3 formal_v4/research/cold_neural_trajectory_teacher.py all --epochs 30
python3 formal_v4/research/cold_neural_teacher_audit.py
```

## Real same-state counterfactual continuations: completed

`cold_neural_counterfactual.py` starts from the same frozen production source,
enumerates its full candidate pool deterministically, replaces one exposure by
an equal-duration wait, clears pending observation bookkeeping, and completes
the original policy for the remaining season. It records public snapshots, state
arrays, action-prefix SHA256 hashes, full official outputs and endpoint deltas.

All three L1 runs completed in 125--128s. The budget was two simultaneous CPU
processes, each capped at 900s (1800s maximum driver wall time). No GPU or LLM is
used. The control exactly reproduces historical L1 6096.185388. Both intervention
prefix hashes match their control hash and simulated time before the changed action.

| Full L1 continuation | Final total | Change from control | Science change |
|---|---:|---:|---:|
| Control | 6096.185388 | — | — |
| Skip exposure 100 | 6100.970154 | +4.784766 | +4.967996 |
| Skip exposure 700 | 6139.432366 | +43.246978 | +43.311454 |

Required, report and request components are unchanged. This is direct evidence
that immediate gain can differ from full future science opportunity value. It is
only two local causal labels: **neither result is an NN improvement, a generalized
policy, or an optimality certificate**. Candidate enumeration is deterministic
rather than the production time cutoff, so the intervention's meaning is tied to
that explicitly recorded controller. Labels live in `counterfactual_labels.json`;
raw output and captured state arrays remain under ignored `runs/`.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv-solver/bin/python formal_v4/research/cold_neural_counterfactual.py --card L1
```

The next data expansion can collect stratified same-state continuations over
science-only, required and request actions, with matched prefixes and whole-card
validation. Oracle plan repairs from `cold_global_search` are useful auxiliary
teachers but must retain their `local-truth conditional-plan-repair` label; they
are distinct from restoring the same participant policy and continuing it.
