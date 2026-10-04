# Independent neural structure reference

This is an independent reference, not the production neural candidate or a fitted model. The producer owns `cold_target_score_distribution` and its child `torch_helper`; that implementation uses padded state/query arrays. This reference uses explicit state IDs to compare identical physical architecture and NumPy semantics without sharing its implementation.

Both models predict one joint195 PMF. The history model has129411 parameters; the current-public-only model has20547. Fixed synthetic16-state/704-query fixtures include empty historical pools and F=0/1/0.5 boundaries. Local CPU Torch2.5.1 vs NumPy2.0.2 logits differ at most1.79e-7, PMF2.33e-9 and soft-label CE9.79e-7. Random initializer weights are explicitly marked unfitted. No GPU fit, validation-world model choice, hidden data or production adoption occurred here.

Mac BLAS floating-flag warnings are preserved in SYNTHETIC_PARITY.json; outputs were finite and matched the independent Torch computation. This result does not substitute for actual trained CUDA/NumPy export or formal Linux runtime gates. The flattened query/state interface can be used for a later independent weight-mapped comparison if necessary.
