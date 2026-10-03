# PRO6000 action-critic controls

The feature/teacher construction is documented in
`../hidden_learning_20261003/README.md`. Both learners use the same 5,568
public-input candidate rows, with exact fixed-continuation terminal labels.
L1/L2 fit; L3 selects; L4 is not used to rescue a failed model.

## Actual experiments

- Ordinary 35→64→1 ReLU MLP: 6,000 owned-CUDA steps, 4.12 seconds; selected
  checkpoint 2,000. L3 conditional mean terminal regret 10.553632. Full official
  L3 replay drops from 5769.301279 to 5441.010433, so this model is rejected.
  Model, training and native evidence are in the sibling directory.
- GPU boosted trees: three declared depths 2/4/6, 600 rounds each; CUDA device
  asserted from the trained learner configuration. Depth 6 selects on L3 with
  mean terminal regret 6.238878. The actual highest-public-utility candidate
  comparator has regret 4.853964 on the same states. Trees improve on the MLP
  but fail this conditional gate, so no additional full-season or L4 test was
  performed. Training took approximately 4.3 seconds across the three models.

The zero-delta historical trace action, also recorded in `tree_training.json`,
is a teacher comparator, not an available zero-regret inference oracle. Adoption
uses the actual public-policy comparator in `validation_gate.json`.

The sparse positive labels and aggregate features remain the unresolved issue.
Increasing training steps or GPU occupancy does not repair missing target-level
future competition or identify the effect of subsequent replanning.

## Reproduction and deployment representation

- `research/gpu_action_critic_train.py`: Numba CUDA MLP with same-state paired
  Huber terminal-value differences; NumPy inference export.
- `research/gpu_action_tree_train.py`: GPU histogram boosted trees; portable
  JSON arrays with NumPy-only inference. GPU versus exported CPU prediction
  differs by at most 0.0001755 on validation, including the rejected depth 4
  model. The selected depth 6 differs by at most 0.0000916.
- `tree_model.ubj` retains the selected native learner model;
  `tree_model.json` retains its CPU representation.

GPU training used an isolated owned research directory. Tree wheels were
installed into `xgb-site`, leaving the existing service environment untouched.
Actual observed power limit was 600W; other workloads were present, so observed
device power is not attributed to this small training task. No platform
evaluation was consumed.

Library installation and GPU behavior follow the
[official installation guide](https://xgboost.readthedocs.io/en/stable/install.html)
and [GPU documentation](https://xgboost.readthedocs.io/en/stable/gpu/index.html).
The actual installed package was 3.4.1, as recorded by the executed trainer.
