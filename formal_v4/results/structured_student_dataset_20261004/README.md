# Portable causal teacher dataset and fixed GPU comparison

Status: tooling prepared. The synthetic portability fixture passes; no actual teacher label file was opened, no actual dataset was accepted, no optimization step was run, and no new season was launched by this work.

`research/policy_iteration_dataset.py` is run beside the **original, terminal** Rhodes1 batch. It requires `bulk_summary.json`, the complete predeclared group inventory, the root-reviewed bulk source lock, unchanged participant and evaluator sources, every frozen public initialization/prefix/canonical READY input, the complete v2 source/continuation/action/availability gates and every original episode archive/member hash. It copies the original control public capture bytes; it does not use the post-run prettyprinted capture. It verifies raw terminal files only as opaque archive bytes and obtains returns exclusively from `pair_audit.json`.

All predeclared groups appear in partition outcome inventories. Failed groups, absent candidates, negative/tied labels and control-only groups are retained explicitly. A failed group is excluded from fitting by an identified integrity/continuation failure, never by its return. A verified control-only group remains a candidate availability record and is not given a pairwise loss. The output is always `accepted=false`.

## Build after the complete batch is terminal

Copy the dataset tool and the five reviewed student modules into the corresponding Rhodes1 `research/` directory first. Use the existing NumPy dependency path; no Torch installation is needed for dataset preparation.

```sh
cd /tmp/geometry_native_20261003
PYTHONPATH=/tmp/geometry_native_20261003:/tmp/geometry_native_20261003/.deps python3 -m research.policy_iteration_dataset \
  --out /tmp/geometry_native_20261003/results/policy_iteration_20261004 \
  --participant /tmp/geometry_native_20261003/results/policy_iteration_20261004/participant \
  --kit /tmp/geometry_native_20261003/upstream/gosim-observer-examples \
  --destination /tmp/geometry_native_20261003/results/structured_student_dataset_20261004/portable \
  --reviewed-lock-sha256 2e539ee19e06e3a87d0ffb261b223b64be9af9faafe9cc7033effc9cb84f43e3
```

The `--participant` path is the actual frozen source directory confirmed by root. The destination must not already exist. Source-lock JSON bytes and original absolute paths are preserved as provenance; validation occurs on Rhodes1 beside those original inputs before relocation. The generated `bundle_index.json` reports the fit/validation candidate coverage and the SHA/size of each portable archive. It does not publish L4 outcomes or returns.

Outputs:

- `fit_validation.tar.gz`: L1/L2 fitting states and L3 validation states only, with exact public inputs, availability, v2 audits and archive verification receipts.
- `sealed_test.tar.gz`: separate L4 state/outcome records. Preserve and hash-lock it locally; do not transport or unpack it into the fitting workspace.
- `candidate_manifest.json` within each partition remains unaccepted. Root must review whole-state coverage, exclusions, source locks, original input hashes and archive receipts before creating a **separate** `accepted_manifest.json` in the fit/validation directory.

The separate accepted manifest keeps the candidate's exact `groups` list and contains `accepted=true`, a specific acceptance note, and `accepted_candidate_manifest_sha256` equal to the original candidate manifest's SHA. Record the new accepted manifest's SHA. The tool and runner never set acceptance automatically.

## Fixed initial GPU comparison

Predeclaration: train each model once, seed `20261004`, at most 200 epochs, patience 30, AdamW learning rate `0.001`, weight decay `0.01`, one CPU thread. Compare DeepSets **6598** parameters with matched flat NN **6507** parameters, the same flat pairwise ridge baseline, native control, and public immediate-utility baselines. Both neural fits use the exact same whole L1/L2 states and L3 validation states. Training normalization is fitted on L1/L2 only.

Checkpoint and model selection use **L3 mean candidate teacher regret first, raw advantage MAE only as a tie-break**, according to the root's prelabel decision-objective amendment. This is finite single-state, one-realized-world evaluation; correlated states within a card do not establish hidden-card generalization. Model comparison does not represent an implemented whole-season policy gain. `deployment_calibrated=false` remains mandatory in every report/export.

The runner requires a reviewed five-module source lock and its SHA, accepted manifest and its SHA, unchanged portable file hashes, actual Torch `2.7.1+cu128` / NumPy `2.2.6`, and the owned Blackwell GPU. The runner refuses a preexisting output directory and cannot fall back to CPU. It does not open L4 labels because no L4 records or bundle exist in its fit workspace.

Prepare a new GPU workspace containing `research/` with the five locked modules, `comparison_source_lock.json`, `run_gpu_comparison.py`, and extracted `fit_validation/` only. Then run with the isolated Windows interpreter, using Windows absolute arguments:

```sh
ssh elevatia-wsl /mnt/c/Users/hedge/gosim-structured-nn-20261004/Scripts/python.exe \
  C:/Users/hedge/gosim-structured-student-fit-20261004/run_gpu_comparison.py \
  --project C:/Users/hedge/gosim-structured-student-fit-20261004 \
  --bundle C:/Users/hedge/gosim-structured-student-fit-20261004/fit_validation \
  --manifest C:/Users/hedge/gosim-structured-student-fit-20261004/fit_validation/accepted_manifest.json \
  --manifest-sha256 ROOT_REVIEWED_ACCEPTED_MANIFEST_SHA256 \
  --source-lock C:/Users/hedge/gosim-structured-student-fit-20261004/comparison_source_lock.json \
  --source-lock-sha256 ROOT_REVIEWED_COMPARISON_SOURCE_LOCK_SHA256 \
  --out C:/Users/hedge/gosim-structured-student-fit-20261004/fit_output
```

The two placeholder SHAs above must be replaced with reviewed real file hashes. This command has **not been invoked**. No assertion of trained weights or GPU training performance is made.

## Verification performed

`portable_bundle_fixture.py` creates four fabricated card groups in a temporary directory. Its end-to-end result checks portable relocation of original capture bytes, unchanged `accepted=false`, no automatic fitting admission, retention of positive/negative/tied/control-only/absent/failure records, separate L4 packaging, and opaque terminal bytes that deliberately are not valid score JSON. It reuses public synthetic input construction; it does not rerun the old 13 defect fixtures or touch real teacher outputs.

```sh
cd /Users/kamico/work/GOSIM/OBSERVER/formal_v4
PYTHONPATH=/Users/kamico/work/GOSIM/OBSERVER/formal_v4 \
  /Users/kamico/work/GOSIM/OBSERVER/.venv-solver/bin/python \
  results/structured_student_dataset_20261004/portable_bundle_fixture.py
```
