# 用公开 prog_mult 独立识别 program-band 的能力与限度

本审计只读自己的当前最好四卡输出与公开几何/评分规则。没有读 weather/event/stress truth 或生成器，没有使用假定的 W 上界，没有修改策略或 ZIP。W 矩阵与质量反演 Z 矩阵严格分开。

## 完整抽象与标签逻辑

定义公开 900 秒 slot 的未知非负标量：

```text
W_s = transparency_s * sky_quality_s / seeing_s
W_s = 0（该 slot 关闭时）
B(i,e) = sum_s A(i,e,s) * W_s
A = 曝光内官方 <=120 秒 midpoint 的时间权重
    × lunar(i,t) / (q0 × airmass(i,t)^0.6)
```

官方 `WeatherTruth.band_quality` 只使用这个 W，以及目标自身的公开月亮/airmass 几何。**B 不含仪器效率 E、不含方向事件乘数或方向遮挡，也不在 repair 时刻切分积分。** 原质量模型是 `Z=effectiveE*W`，Z 的状态可因成功 report 改变，不能把 Z 拟合值当 B。

每条实际 hit 的 `prog_mult` 来自 declared program 与 actual band 是否相等。即使最终 score/quality 为零或 observation 后来因 data loss 失效，该物理 program 标签仍然存在；失效只改变结算 ledger，没有改写实际当时 program-band 计算。精确规则如下：

| declared | prog_mult | 对 B 的约束 |
|---|---:|---|
| DARK | 1.20 | B ≥ 0.65 |
| DARK | 1.00 | B < 0.65 |
| BRIGHT | 1.12 | 0.40 ≤ B < 0.65 |
| BRIGHT | 1.00 | **B < 0.40 或 B ≥ 0.65** |
| BACKUP | 1.06 | B < 0.40 |
| BACKUP | 1.00 | B ≥ 0.40 |

BRIGHT mismatch 是析取，不能写成 `B<.65` 或某一个连续区间。此审计保存该精确析取，计算凸外松弛时将这些行省略。其他严格上界改为闭上界，另外加 `1e-9` 数值裕量；因此求出的 box 包含原标签可行域，不能把外松弛的一个 feasible point 当真实天气恢复值。

## 计算与验证

所有 A 的系数非负。在 W≥0、不设任何 W cap 的条件下，有限上界行给出

```text
W_j <= (row_upper - sum(k!=j) A_k * lower_k) / A_j
W_j >= (row_lower - sum(k!=j) A_k * upper_k) / A_j
```

未知 upper 保持无穷，不插值或补 AR 值。单调 box 传播后，用独立稀疏 LP 验证凸不等式的联合可行性。γ 传播跑到 300 轮仍未保证收敛；得到的每一轮 box 依然只是安全外区间，不影响其联合 LP 可行性检查。

| 卡 | 原 prog_mult 标签 | 凸约束行 | W slots | 有限 upper cells | 无有限 upper cells |
|---|---:|---:|---:|---:|---:|
| α | 16282 | 15369 | 1252 | 365 | 887 |
| β | 15526 | 14899 | 1198 | 391 | 807 |
| γ | 16073 | 15216 | 1234 | 638 | 596 |
| δ | 15156 | 14011 | 1179 | 260 | 919 |

四卡 LP 都通过可行性检查，最大约束误差 ≤ `4.11e-15`。γ 的 313 条、δ 的 280 条原失效贡献仍提供了 band 标签。没有把 report 修复时刻添加为 W cell。

每卡另做 18 个完全合成的官方 `WeatherTruth.band_quality` 小验证（显式指定 W，E=0.07，目标在公开最低高度以上），覆盖跨 slot 和不同曝光时长；矩阵与官方函数最大误差 ≤ `1.67e-16`。这没有构造或读取真实隐藏天气。

## 对最新 α coupon 上界的结果：无法收紧，并能解释原因

检查最新 α master 的 192 个条件 coupon、2523 条分配目标。所有目标的 B 上界仍无穷，无法排除 DARK，因此固定 DARK program 的科学上界仍是 `1.2 × weight × factor_upper`；此次上界减少量为 **0**。

这不只是传播算法不够强。对每个 cell j，代码验证：

```text
upper_j 为无穷 <=> 所有有限上界标签行对 cell j 的系数都是 0
```

若候选 B 的系数 A_j>0，而 j 不在任何有限上界行中，令 `W -> W + t*unit(j)`：所有有限上界行保持不变，所有下界行仍满足。BRIGHT mismatch 的析取也无法提供有限上界：受此变化影响的行在 t 足够大时满足其 `B>=.65` 分支；未受影响的行保持原先标签。因此从任何实际存在的精确标签可行 W 出发，足够大的 t 仍能得到另一精确标签可行 W，并让候选 B 无界。

2523 个 coupon 目标**全部**包含这样的正系数无界方向，JSON 保存具体 cell index。故即使把 BRIGHT mismatch 全部精确建成混合整数析取，也不能仅凭这些 band 标签排除这些 coupon 的 DARK 可能性。这里讨论的是所有非负 W 的标签模型，不是声称真实天气能任意增大。

更强地，同时增加所有无上界 cell，能够让这 2523 个候选 B **同时**超过 .65，且全部精确历史标签仍可满足。因此对当前 coupon 池，在仅有 band 标签的模型中，共用一个 DARK program 的 fiber 耦合也不能将 1.2 上界继续收紧；这不是逐 fiber 独立取上界造成的假宽松。

已知 q=Z 积分也不能自动消除该自由度：没有公开的正效率下界时，W 增大可对应 E 减小，`Z=E*W` 仍相同。若以后加入官方可保证的 E 正下界、W cap、确切仪器恢复模型或更多上界标签，才可能收紧；这些条件必须单独证明，不能从“相同公开 bulletin”或 repair 成功推出。

## 可复用方向

- 对新列，先用此 W box 计算 B 范围；若 `B_upper < .65`（保留数值安全余量），DARK multiplier upper 可从 1.2 降到 1；对 BRIGHT/BACKUP 同样按可能 band 判断。
- 一个 exposure 所有 fiber 共用 declared program；上界计算可取三个 declared 的联合最优总值，不能给每个 fiber 各自选择不同 program 当可实现得分。
- 当前 α coupon 确实无法收紧，但其他时间节点有 365 个 finite-upper cells，仍可为后续联合列定价提供安全外约束。无需把 W 与 Z 混为一个 latent profile。

## 文件与复现

```sh
.venv-solver/bin/python formal_v4/research/program_band_interval_audit.py
```

每卡 `band_W_outer_intervals.npz` 保存矩阵、closed 外约束、W box、有限上界行支持计数及一个仅用于凸可行性检查的点。`label_metadata.json` 单独保存 omitted exact disjunctions。α 的 `alpha_coupon_band_bounds.json` 保存每目标 B 外界与无界方向。没有新调度、官方分数或全局最优声明。
