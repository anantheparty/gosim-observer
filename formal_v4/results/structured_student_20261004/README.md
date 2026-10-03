# Compact public action-value student

The code is ready for a bounded Torch/NumPy audit and later accepted teacher labels. No training labels were opened, no optimization was run, and no student survey score has been measured. READY and teacher sources were not changed.

The representation was derived from the official `v4_runner.py`, `v4_scorer.py`, and public protocol, then checked against the policy-iteration scaffold. Final science uses maximum valid score; required and Jain completion use independent maximum factor; requests require valid exposures wholly inside their windows. Duration changes exposure rank and the future loss window. Therefore the student predicts full native-continuation return differences, including all five terminal components.

The adapter requires revision-7 public capture metadata: exact `target_ids`/14 source-column order, candidate predictions made before branch feedback, public initialization, public-history actions/feedback, and the raw ledger. It rejects missing/order/hash mismatches. Missing native utility for exact short/long/program actions stays missing. The current proposal at the last history row is not treated as a past executed exposure. Request exposure times use each past action start and its next public feedback time.

| Input/model | Concrete shape on public L1 rank 64 |
|---|---:|
| Target attributes, score/factor uncertainty, full-ledger redundancy/rank bins, active requests | 7800 × 44 |
| Assignment geometry and frozen public physical predictions | up to 16 × 17 per candidate |
| Time/rank/belief, ledger, Jain, requests, current notices, known future forecast nights, persistent terrain | 252 |
| Duration/program/pointing, approximate one-step component utilities, native-utility presence | 17 per candidate |
| Target/assignment encoders | 16 hidden units, 8 latent units each |
| Shared head | 16 hidden units; total return + 5 component outputs |
| Structured parameters | 6598 |
| Flat comparator | 584 pooled inputs → 11 hidden units → 6 outputs; 6507 parameters |

Both encoders use mean/max/sum divided by square-root count pooling. Assignment embeddings join their target embedding through public target indices; IDs themselves are not features. Every ledger row is consumed into target redundancy, score/rank, validity and global rank summaries. Target and ledger permutations preserve values up to floating-point summation error. This compresses history and is not a sufficient statistic for every arbitrary future loss window. Three-sample future-night geometry is approximate. Factor estimates and rounding-adjusted upper proxies remain learning features, not rigorous completion certificates. Published forecasts retain only their disclosed event/direction/night facts.

The `structured_student_train` module refuses an unaccepted dataset. It hashes every accepted capture, feature archive, public initialization and passed full-season pair audit; verifies the card, state prefix, all candidates, exact action pairs, and official total/component deltas. It averages all pairwise Huber comparisons within each group, then weights complete groups equally. Ties and negatives stay in the loss. Scalar and auxiliary components share a raw-score unit scale. Normalizers fit only L1/L2 groups. L3 selects epochs. Training does not open any L4 file. Thirty-two first-batch training groups are below the stated 256-state threshold for broad claims.

Required comparisons are native control, approximate public one-step science/required/Jain/request utility, gain per second, a convex flat pair-ridge predictor, and the similarly sized flat NN (run `--model flat` separately). Reported regret/selection metrics concern teacher branch returns at held-out states; they are not full student season scores. A 95% finite-sample group error quantile is unavailable with only 16 validation groups, and card/world dependence further limits calibration.

`structured_student_runtime.py` imports only NumPy and the public feature adapter. `.npz` export uses no pickle or Torch objects. Export forcibly sets `deployment_calibrated=false`; `choose()` returns the native control for every such artifact. Production activation still needs held-out calibration and complete official season/runtime gates, with a separately reviewed promotion.

Run the public-only bounded audit from `formal_v4` in an existing NumPy environment:

```sh
python -m research.structured_student_audit \
  --initial results/policy_iteration_20261004/L1_initialize_public.json \
  --capture results/policy_iteration_20261004/natural_control/L1/rank_0064/control/public_capture/capture.json \
  --public-features results/policy_iteration_20261004/natural_control/L1/rank_0064/control/public_capture/public_features.npz \
  --out results/structured_student_20261004/public_numpy_audit.json
```

Root may add `--device cuda` in its verified isolated Windows Torch 2.7.1/cu128 environment. This performs one untrained forward/backprop on an output-squared synthetic objective, one export comparison, and the same public permutation checks. There is no optimizer, label read or season launch.

After a complete dataset is accepted, use its hash-locked manifest as shown in `accepted_manifest.example.json`:

```sh
python -m research.structured_student_train --manifest ACCEPTED_MANIFEST.json \
  --out results/structured_student_20261004/structured_fit --device cuda
python -m research.structured_student_train --manifest ACCEPTED_MANIFEST.json \
  --out results/structured_student_20261004/flat_fit --model flat --device cuda
```

These commands are instructions for a future accepted batch; neither was run in this task. Sparse rounded per-target terminal factors are not used as exact threshold auxiliary labels. All-zero/unobserved targets remain present in the public catalogue encoder.
