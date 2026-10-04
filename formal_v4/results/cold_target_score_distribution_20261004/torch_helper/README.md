# Cold target score distribution helper

仅普通 PyTorch + NumPy；模块导入不会训练。固定 3 bands × 65 knots，F 为 [0,1] physical factor，knots = 0, 1/64, ..., 1。无独立均值或 hinge head。

## 接口

`JointScoreDistributionModel(context_mode="fullhistory" | "current-public-only")`

`forward(ht, hn, hm, cn, cm, q) -> float32 logits [B,Q,195]`

输入均为 float32：ht `[B,8,16,24]`、hn `[B,8,129]`、hm `[B,8,16]`、cn `[B,129]`、cm `[B,16]`、q `[B,Q,51]`。正式数据 Q=320，测试支持其他 Q。token index 23 > 0 代表存在；缺席 token 均值与最大值都为零。`current-public-only` 不读取前三项，允许传 None，完整读取 cn/cm。

`logits_to_joint_pmf(logits, temperature=1.0) -> [B,Q,3,65]`，temperature 必须正且有限。195 logits 的索引为 `band * 65 + knot`，softmax 在完整195维进行。

`pmf_statistics(pmf, hinge_threshold=0.0)` 的 `mu_b` 和 `joint_first_moment_by_band` 都严格等于 `E[F·1{band=b}]`。`conditional_mean_b=mu_b/P(b)`。`hinge_by_band=E[max(F-threshold,0)·1{band=b}]`；`hinge` 为 band 求和。零 band 概率的条件统计为零。

`masked_soft_cross_entropy(logits, F, band, mask, state_balanced=False)`：仅真实 band，相邻两个 knots 线性软标签；默认在整个 batch 的有效 queries 上取 mean。`state_balanced=True` 时先求每个 state 的有效 query 均值，再平均非空 states。有效 F 必须 [0,1]，band 为 0/1/2；被 mask 的占位标签可 NaN/-1。全空 mask 返回可微零。caller 提供每 world 等数量 states；state 平衡使有效 Q 数量不会改变各 world 的样本权重。

`model.export_npz(path)`；`NumpyJointScoreDistributionModel(path)` 提供相同 forward、joint_pmf 和 NumPy statistics，无需 Torch。

## 训练 helper

`train_model(dataset, output_dir, context_mode="fullhistory", config=TrainConfig(), checkpoint=None)` 返回 `(model, epoch_records)`，不选择 checkpoint。dataset 必须包含 `ht/hn/hm/cn/cm/q/F/b/mask`（也接受 band 作为 b 别名）。未来 point/best/effective 数组不会进入 forward。

默认 12 epochs、AdamW lr=0.001、wd=0.0001、grad clip=5、seed=949200、batch=8 states、device=cpu、preload_device=True。训练固定使用 `state_balanced=True`，每 epoch 在 CPU 均匀 shuffle 所有 states，各 state 出现一次。caller 可显式选 cuda；预载会先将完整 public tensors 和 labels 放至 device，CPU permutation generator 保持不变，每个 batch 只将 indices 转至 GPU 后取数据。CLI `--no-preload-device` 可关闭预载。每 epoch 保存 `epoch_XX.pt`、`epoch_XX.npz` 和一条 `training_log.jsonl`；保存完整 optimizer 状态，已有 log 时拒绝覆盖。record 包含非空 states 数和 `epoch_elapsed_seconds`，soft CE 按 state 加权记录；每 epoch 简洁 print 并 flush。

可选 `checkpoint(model, epoch)` callback 在 inference_mode 下执行，返回 cal/val metrics 写入 log；选模和 temperature calibration 由 caller 执行。epoch 从 1 开始。CLI 的 `load_world_arrays` 只读取 caller 显式提供的 NPZ，要求每 world 相同 states 数目，以维持 world 总样本数均衡。

## 公开随机 fixture

`python check_public_random_fixture.py` 执行 CPU Torch/NumPy logits、三个 temperature 的 PMF、PMF 导出统计、空历史/缺席 token 屏蔽、current-only history invariance、相邻 knot 和 mask loss 检查；不等有效 Q 的 state 平衡检查另有手算结果。固定 seed=949200，Q=320。仅未训练随机初始化，无 optimizer update。默认结果写 `public_fixture_results.json`，临时 exports 在此目录内创建后删除。若缺少 Torch，明确输出 skipped，不安装依赖。
