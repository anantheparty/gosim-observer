# 真实联合对偶 GPU 列定价：α 的四个有限时段

## 状态与可比性

2026-10-03 在自有 RTX PRO 6000 Blackwell 上实际运行。目录名沿用准备阶段的实验标识；上一阶段仅生成了输入，并未运行 GPU。本轮原始排名、同一输入的 margin 修正排名两批均完成了 GPU、CPU 精核及有限整季 master。

这里的整季 master 使用旧 `cloud_cd2_alpha_20261003` incumbent，官方总分 **7094.664204**。CSV 重建保守值 7094.664229682793，舍入差 0.000025682793。当前 α 已验证 Phase 成绩 **7289.494481**，比该旧基线高 194.830277。本轮不是对最新 Phase 排程的重优化，也没有产生新的官方回放成绩。δ 最新 REQ 成绩 **6423.086757**；本实验没有处理 δ。

## 数学模型

固定旧报告及 E 历史、已有时刻节点，在四个起点上搜索 32,768 个有限 pointing、9/5/9/10 个已有 end node、三个 program。使用原有限整季 LP 的真实 science winner、mandatory 和 REQ 对偶价，而非合成测试权重：

```text
target value = max(0, science_upper - rho)
             + nu * [factor_upper >= 0.5]
             + sum eta * [eligible REQ factor reaches its threshold]
reduced profit = sum best target value in each fiber
                 - (pi[end] - pi[start])
```

GPU 同时对有限 pointing/duration/program 求逐 fiber 最大值；每个 fiber 至多一个目标。CPU 随后恢复 assignment、要求原 glass 中严格大于 0.03° margin，并调用官方 FiberGrid 及全曝光最低高度检查。保留最多 60 个候选列，加入整季 master。

整数 master 包含非重叠 DAG 时间流、各目标 science 最大值、不同 mandatory 目标及 REQ quorum。均匀性在取得整数解后按官方公式结算，不在 MIP 目标中；净分不优于 incumbent 时输出 incumbent。乐观 LP 仅是当前有限列集的松弛，没有覆盖所有遗漏列，更不是连续全局问题的上界。

## 原始批次结果

| 项目 | 实测 |
|---|---:|
| 有限列 | 3,244,032 |
| GPU 定价计时合计，含首 case JIT | 0.863910 s |
| 整个 device 阶段，含 NPZ loading/CPU gate | 0.975901 s |
| module import，单独记录 | 1.412577 s |
| 独立 CPU/CUDA 比较列数 | 1,032 |
| 最大绝对误差 | 1.4211e−14 |
| CPU margin + 官方几何精核 | 134.991259 s |
| 官方 assignment/全曝光高度检查 | 7,972 |
| 精核正价不同列 / 保留列 | 597 / 60 |
| 保留列的再次官方几何检查 | 822 |
| 整季 master MIP / 全阶段 | 0.096449 / 4.453874 s |
| MIP status / gap | optimal / 0 |
| 保守净分变化 | 约 0，−9.1e−13 数值误差 |
| 乐观有限 LP 变化 | 0 |
| 选择的新列数 | 0 |

GPU 设备 metadata 明确 `cuda_simulator=false`。这些计时不包括 SSH 传输，不是整季 solver 的加速倍数。此前 151× 是另一项同批次合成定价 benchmark，不是本次高分改善。

### 为何正价列没有改善

`alpha/pricing_semantic_audit.json` 将 60 个候选的语义价格逐条独立重算，最大误差 1.4211e−14。它们每条都包含对基线已经完成的 mandatory 目标的正对偶价，60 次；没有覆盖基线缺失的三个目标。正价可来自最优对偶的退化，不能直接当作新增 mandatory 的 50 分收益。加入全部列再求 LP 后仍同值，整数解也没有采用新列。

这给出了后续模型改进的具体方向：研究最优对偶面上的价格稳定化或选择，压制已完成目标的无效高价，再寻找多个关键时段同时替换的互补列。只增加同样的高价样本没有收益证据。

## Margin 排名修正

原始 GPU 排名使用完整 glass，之后才删去 margin ≤0.03° 的目标，可能遗漏更好的稳健列。同一 kernel 已支持 glass<pitch：保持原 pitch，定价时用 `pricing_glass = original_glass - 0.06°`，数学上等价于每个 fiber cell 向内缩 0.03°。官方精核继续使用原 glass 和严格 `margin>0.03°`。

同四个 NPZ、pointing 和 end node 的修正设备批次已实际运行：定价合计 0.492571 s，device 阶段 0.595477 s，module import 0.391255 s；独立 CPU 比较 978 个列，最大误差 2.8422e−14。kernel 不变。CUDA/CPU 内缩格子边界是闭集，最终精核采用严格开边界；保留 reduced profit 必须 >1e−7，最终结果以精核为准。

修正批次 CPU 精核 130.190190 s，8,085 次官方 assignment/全曝光高度检查，562 个不同正价列，保留 60 个。整季 master 阶段 4.048692 s，其中 MIP 0.088511 s，status optimal、gap 0；保守净分变化约 0、乐观有限 LP 变化 0、新列采用 0。修正了排名中 margin 的建模一致性，本轮仍没有取得分数改善。

`alpha/margin_batch_comparison.json` 进一步比较实际 action：两批最终保留的 60 个 action 全部相同。因此本轮第二批验证了排名修正，但未给整季 master 增加不同的最终列；第一批的退化对偶诊断对这 60 列仍适用。

## 条件与来源

新列的 quality 来自本人合法官方输出推得的窄区间，同 realization 与 reference-domain 几何假设；固定旧 report/E 路径，假设零仪器偏移。program science 使用上下界；不把 Z 当作独立 W/E 或完整 band 分类。结果不能证明正式隐藏实例会遵循同 realization，也不能证明当前全局最优。

`remote_input_hashes.json` 保存 transfer 后所有 NPZ、原始 driver、kernel 和 metadata 的远端 SHA256。GPU JSON 保存实际执行 driver hash、metadata hash、设备与时间；refined JSON 保存 GPU output、dual、profile hash。`artifact_manifest.json` 汇总完成后的输入/输出/source hash。

原始：`alpha/gpu_top.json`、`refined_columns.json`、`master_gate/gate.json`、`master_gate/primal_schedule.json`。修正批次采用 `*_margin` 名称，保留原证据。没有操作比赛浏览器、生产服务或功率限制，没有读隐藏输入，没有新提交。
