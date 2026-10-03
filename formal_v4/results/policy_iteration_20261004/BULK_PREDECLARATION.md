# 64 public state groups: review candidate, not launched

The frozen revision 7 actor, harness, READY participant, and five official sources remain unchanged. New bulk code only selects public cuts, schedules exact available cases, audits complete outcomes, and archives them.

## Declared coverage

For each card, use the 16 midpoints `(2i+1)/32` of the public initialization season calendar span. Select the first reached natural observe state at or after each threshold, using only public actions and timestamps. Deduplicate identical ranks and record any missing stratum, with no replacement. Inferred public timestamps have been checked against the official public action/start/rank columns for every canonical natural observe action.

All 64 planned ranks are distinct within card. There are no absent calendar strata.

| Card | Split | Declared ranks |
|---|---|---|
| L1 | train | 106, 187, 287, 419, 545, 626, 656, 711, 760, 792, 825, 849, 872, 897, 926, 964 |
| L2 | train | 104, 188, 232, 344, 425, 510, 587, 656, 714, 759, 805, 878, 922, 965, 1008, 1072 |
| L3 | validation | 122, 206, 265, 403, 528, 616, 690, 734, 782, 822, 845, 871, 893, 918, 942, 972 |
| L4 | test | 108, 188, 221, 339, 479, 545, 591, 642, 666, 699, 739, 770, 807, 830, 857, 895 |

This supersedes the initial equal-observe-rank proposal. Calendar sampling represents late nights with few observations; it deliberately avoids searching for known profitable teacher cases. The current teacher states remain states reached by READY, so distribution shift under a learned policy requires later real-season evaluation.

## Case availability and outcome gates

At each state, run accelerated control first. A host observer reads only the participant's current public capture and freezes the exact distinct action inventory before any terminal score/workflow/target-label file exists. Candidate families are control, distinct evaluated field, shorter duration, longer duration, and next public program, with no actor changes. Missing or duplicate candidates are explicitly recorded. If public availability cannot be frozen in time, retain the failed group and run no alternatives.

Only an exact full-season READY score, action sequence, and component control gate permits all frozen available alternatives to be scheduled. No case is selected by terminal reward sign. Every alternative replaces one current action and replans every subsequent action naturally, using the original native policy. Forced input tape contains only ranks strictly before the cut; waits at the cut are generated naturally. Same-card canonical rank 64 natural action sequences are used at every arbitrary-rank control audit.

Audits bind complete public capture (including ledger, C/E, requests, priors, predictions, and history), features, exact submitted prefix/current action, source lock, available inventory, and official complete score/REQ/Jain/rank invalidations. Every started case and failure is archived with member hashes; each blob is below 90 MiB. Control-only states are retained with `trainable=false`. Whole-group failures remain visible and cannot enter training.

## Label and student limits

Upper bounds are 64 state groups, 320 episodes, and 256 baseline-relative scalar labels. L1/L2 provide only 32 training state groups, not 256 independent training states. Labels are one realized future-world Monte Carlo continuation per state. They do not establish exact expected conditional value or complex graph-network generalization. Use this batch for a small structured or pairwise model and label-quality/coverage analysis.

All action features come from reached public messages, public feedback ledgers, and predictable geometry. Initialization/catalog are shared once per card; one group capture/NPZ is shared across its actions. Card ID is provenance/split metadata. Native utility is recorded only for exactly evaluated assignments; unavailable utility remains null.

Public score-derived factor upper features and terminal CSV threshold auxiliary labels are approximate at six-decimal precision. Auxiliary threshold labels remain unused. Any later auxiliary threshold use must mask factors within `0.5 +/- 0.5e-6`. Sparse zeros and failures must be retained.

## Measured computation budget

Natural full controls: L1 442.043 s, L2 535.680 s, L3 454.772 s, L4 434.554 s; all reproduce READY exactly. L1 accelerated rank 64 control: 403.747 s. L1 accelerated late rank 858 control: 79.597 s, also exact. These fit roughly 29.382 seconds fixed replay/capture plus 400.492 seconds times the remaining observe fraction. Apply each card's measured natural-walltime scaling to its exact predeclared ranks.

The plan predicts 59,788 worker wall-seconds for the 320-episode upper bound: 2.08 hours at eight workers. A 1.5x continuation allowance plus 20 minutes of scheduling/archive overhead gives 3.45 hours. Each worker is one actual 2-CPU, 2-GiB Docker episode; the estimate is not divided by its CPU quota. Jobs use physical cores 0–15, eight pairs, leaving physical 16–23 and all SMT free. No GPU is needed for teacher generation. Peak participant allowance is 16 GiB total; reserve 8 GiB disk for raw cases, archives, and public prefixes. The early pilot uses 3.5–4.4 MiB raw per case; the late control uses 11.5 MiB because its full public history/ledger is larger. A 12 MiB per-case raw allowance plus compressed archives and prefixes remains below this reserve.

Stop starting new episodes at six hours. Already running drivers retain their 990-second timeout, followed by up to 60 seconds of owned container cleanup and host archive overhead. Preserve all unfinished/failed scheduling records. The bulk requires root review of `bulk_source_lock.json` and its explicit SHA argument; it has not been launched.
