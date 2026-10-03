# READY：完整球面空间支持函数及连续单次曝光上限

没有新策略回放、生产提升或新可用价格。

使用覆盖整个球面的 64,800 个闭合 RA/Dec 矩形（各 1°），最远角距由矩形角点给出，最大 cover radius 为 0.707102394°。官方 FiberGrid 的方形玻璃球面外接圆半径为 1.788273578°，每个 cell 查询半径为两者之和加数值余量，即 2.495376071°。

曝光开始时的实际中心是命令加 offset，转换成固定 RA/Dec 后恒星跟踪。初始 hit targets 整次曝光都保持在这一初始球面 cap 内。整球 cover 包括这个实际中心，无需再加 offset 半径；证明没有假设目标在曝光中仍落入瞬时 command 玻璃。

每个 cell 的所有可能 target 构成超集，其最大的 16 个非负 `ν_i r_i,k` 之和包住每个真实初始指向。对所有 cell 取最大，再乘 slot 时长积分，给出拉格朗日支持上界。关闭/可见性边界与质量上限继承完整资源图。没有使用旧曝光列；无 target 的 cell 支持为零，故可跳过。

6 种非负 ν 的数值试验未改善原上界，最佳仍是零 ν。按 science slope 的 ν 会使空间支持小于无 field 的 top16，但完整上界仍很松；按全季 maxrate 归一化的 ν 几乎没有空间收紧。没有优化目标价格，也不能据此声称真正最优价格为零。

同一轮另收紧了单次最大完成因子。本站点 slot 都是 900 秒、最大曝光 3600 秒。逐 target 的乐观质量 upper 是非负阶梯函数；3600 秒 moving integral 在 slot 边界间线性，且 shifted boundary 也是 slot 边界，所以其最大值是同一夜任意连续四个 slot upper dose 的最大和。短曝光在放宽后的夜间区间内延长不会减少积分。使用这个上限替代“瞬时最大率 ×3600”。

| 卡 | 原全边图总上界 | 仅空间 ν 候选后的上界 | 连续四 slot 单次上限后的上界 | 收紧量 |
|---|---:|---:|---:|---:|
| L1 | 8688.186251 | 8688.186251 | 8671.259552 | 16.926699 |
| L2 | 9516.714933 | 9516.714933 | 9502.027614 | 14.687319 |

收紧来自单次曝光时间积分，并非这批空间价格。以上仍是带本地真值天气条件的乐观上界，包含 request/report 奖励上限与零 Jain 扣分；不能作为平台 alpha–delta 或未来天气保证。

验证：每卡 10,005 个球面点（包含极点/RA 接缝）均在 cover radius 内；每卡 4,096 个任意整数起点和 1–3600 秒窗口没有超过四 slot 上限，包含 4092/4092 个非边界起点及 3449/3469 个跨 slot 窗口。数值采用 outward padding 和最终至少 1 分余量，不是严格区间算术证书。详细数学证明在 `L1_proof.json`、`L2_proof.json`。

复现：

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv-solver/bin/python formal_v4/research/cold_probabilistic_spatial_support.py L1 L2
python3 formal_v4/research/cold_probabilistic_verify_spatial.py
```

构造 support 需要 SciPy cKDTree；若旧大 NPZ 不在本地，脚本可用完整资源图源代码重建边。当前只在最终生成证明后修正了文字，以明确曝光开始 actual center 与 sidereal tracking；数值算法和结果未改变。summary 同时保留 executed source hash 和修正文案后的 source hash。

可 stage 新路径：

- `formal_v4/research/cold_probabilistic_spatial_support.py`
- `formal_v4/research/cold_probabilistic_verify_spatial.py`
- `formal_v4/results/cold_probabilistic_model_20261003/spatial_support/`

旧概率/资源图 READY 文件未修改。
