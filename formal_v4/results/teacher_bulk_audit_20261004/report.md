# Independent teacher and bulk audit — 2026-10-04

No remaining launch-blocking defect was found in the frozen sources listed below. This is a source and public-trace audit, not acceptance of any future bulk labels or a student performance claim.

## Frozen inputs checked

| Artifact | SHA-256 |
|---|---|
| Teacher source lock, revision 7 | `eda4463d30fe79b7706b323d1024726fc0a379314f4497c47c7ec0005ecacd72` |
| Teacher actor | `895185793aa3945ebdbb6b7353fc2e925425f853a87d6548c59275e9340f48b5` |
| Bulk source lock | `2e539ee19e06e3a87d0ffb261b223b64be9af9faafe9cc7033effc9cb84f43e3` |
| Bulk plan | `5244f89f119db3f1d6ab0a4257dd64209de401a1162739708c2eccdee54286b8` |
| Bulk launcher | `74de5541cf1d0ea3e811d7d4e3ce760549ebfb344bb078838277d5e729f8fca9` |
| Bulk auditor | `268479d33e103b3cd30050757f969f575dd4c47221ed5f3a240b1bb7db4c0ca8` |
| Guarded learner | `039bedbfb43125abfdd917d3bb390356f0e813c18b21642589b017247e9e318e` |

The local launcher/auditor/harness/original-auditor files, plan, original source lock, four canonical natural gate/action/score/public-trace/initialize sidecars, and all 64 prefix files match their declared hashes. There are 64 distinct `(card, rank)` groups, with 32 train, 16 validation and 16 test groups, and at most 320 episodes. No absent calendar stratum is declared.

## Official semantics and continuation

The official upstream initialization, participant guide, runner and scorer were read before the research code. Public inputs contain the catalog, geometry, calendar and scoring configuration; numeric weather truth, unreleased requests/events and hidden offsets are excluded. Delivered observation feedback contains rounded scores and hit sets, without raw factor. Final science uses maximum valid score, required/Jain completion uses an independent maximum valid factor, and requests require exposures wholly inside their issuance/deadline window. Data loss invalidates observe ranks and can revise request rewards.

The actor consumes actual runner feedback through the original policy during the accelerated prefix. It substitutes past planner actions/predictions strictly below the selected observe rank. At the cut, it computes fresh candidates, commits the exact intervention into pending feedback state, and resumes natural native planning. The frozen participant has no RNG to restore. Skipped geometry summaries affect reporting only. Natural-control public traces show maximum planning call times below 1.43 seconds, versus the planner's 30-second cutoff.

Independent checks reproduced every public-derived observe start against the official observe-only `decisions.csv` rank/start columns: L1 981, L2 1107, L3 993, L4 928, with zero mismatches. Every planned cut matches its canonical observe row, snapshot hash and preceding action hash. Every prefix is exactly the canonical rows with `rank < cut`.

## Concrete defects found and corrected by the owning agents

- The original pair audit looked for a natural control at the same selected rank. Non-64 ranks had no such canonical reference. The bulk audit always uses the validated same-card natural rank-64 control and locks its artifacts.
- Candidate directories alone could omit a scheduled branch, and NPZ equality omitted belief/history/prediction fields in capture JSON. The bulk audit now checks the full frozen distinct inventory, complete capture state, group identity, actual submitted prefix and cut action, and full natural control stream.
- The first availability guard watched score/workflow/label files, although the official runner writes terminal CSV/message files earlier. The final guard checks all seven terminal markers before and after freezing, then proves their modification times are later than the recorded freeze time.
- Final provenance initially checked only the lock JSON. The final code checks referenced source, plan, canonical input and prefix hashes at startup, each audit and completion.
- Audit exceptions could bypass archives, and an existing archive could be reused without comparing current raw files. Failures now retain explicit error records and archive fallback; reuse requires exact current member names and hashes. Archive failure invalidates the group labels.
- The learner could silently collapse duplicate label cases, accept duplicate candidate aliases or send a control-only group to an empty pair loss. The guarded learner rejects duplicates and conflicting baselines, requires the v2 inventory contract, binds availability to original capture bytes/features/state/actions, preserves control-only records as untrainable, and guards the pair loss. The owner's synthetic 13-case rejection suite passed; no real labels were used in that suite.

## Dataset acceptance conditions

Accept only complete whole-state groups after the frozen v2 audit passes every gate, including source/input hashes, canonical READY control, full declared available inventory, identical pre-feedback state, submitted cut actions, preterminal timing and verified archives. Failed or missing branches invalidate the whole group; preserve the failure and absent-candidate records without replacement or sign filtering.

The accepted manifest must hash-lock the original `control/public_capture/capture.json`, public NPZ, public initialization, v2 pair audit and availability file. Its capture path must not point to the pretty-printed copy, whose bytes differ from the frozen availability hash. Require `archive_complete=true`, a finite shared baseline total, exactly one control, every distinct available alternative exactly once, and consistent official total/component deltas. Control-only inventories remain recorded and are excluded from fitting.

Keep L1/L2 for fitting, L3 for validation and L4 unopened by training. The 32 training groups support a small learner plumbing batch; labels are returns from one realized future world, and correlated action pairs do not increase the independent state count. Exports retain `deployment_calibrated=false` and select native control.

Use official terminal totals/components as labels. CSV factors are rounded to six decimals: a true factor of `0.4999996` can appear as `0.500000`, so CSV-derived threshold flags are not exact. The current student excludes those target auxiliary labels; any later threshold use must account for the rounding interval.

The six-hour resource limit stops new job starts. Active drivers retain their 990-second timeout, followed by up to 60 seconds of owned cleanup and host archive overhead. It is not a hard six-hour completion bound.

No actor, harness or READY file was edited by this audit. No episode, training run, future-label selection or archive extraction was performed. Only this report was written.
