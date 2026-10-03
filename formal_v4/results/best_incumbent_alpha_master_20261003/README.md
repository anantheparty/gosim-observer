# 最新最好 α：独立有限列 master 与新对偶价格

本模型从自己的最新最好 α 完整输出 `cloud_phase_gpu_alpha_20261003` 重建，官方分数 **7289.494481**。没有调用旧 `card_master`/`capture`，没有覆盖旧结果、修改其他模块的全局函数或改变生产提交策略；仅复用无副作用的建模、结算及 LP dual 函数。没有读取隐藏数据或调用远端服务。

## 结果

- 1184 个原历史 observe 列全部保留；有效记录的 CSV score/factor 原值另存 `score_csv`/`factor_csv`。复算总分 7289.494439126，与官方差 -0.000041874，低于六位舍入界 0.004799501。
- 首先用最新 α 独立输出检验旧窄 quality 区间：**576 次曝光、7959 条公开几何条件下的干净正 quality 方程，0 条区间越界**。1 次与旧/新 repair 差异区间相交的曝光、564 次未获窄区间支持的曝光被排除。公开消息相同没有代替这一步验证。
- 新矩阵在最新 repair **2026-10-30T01:54:35Z** 切分。旧修复 `01:50:01` 到新修复 `01:54:35` 间的整曝光不允许迁移；整个新质量 cell 只要与此间隔相交，也被拒绝迁移。区间只映射到完全被一个旧窄支持 cell 包含的新 cell，保留 462 个窄支持 cell。
- 从原公开条件 coupon 中重新构造 **192 个新列**。所有使用的新列均通过窄支持、方向净空、`.03°` 玻璃 margin、实际官方玻璃分类及整曝光最低高度检查；共 2523 次官方 fiber 检查、2523 次官方整曝光可见性检查。假设实际 pointing offset 为零及公开参考方向事件几何范围，仍是条件模型。
- 共 **1376 列、1266 时间节点**。代理整数模型的最优 gap 为 0，未选入任何新 coupon，科学/required/REQ/Jain 分项没有提高。原 1184 列保底调度完整保留。
- 本次新 pool 的乐观有限 LP（省略非正 Jain 分项）为 **7373.168525333**，比官方历史分数高约 83.674。它只覆盖本次列池和条件质量区间，**不是完整问题的全局上界**。
- fresh dual 的 KKT 最大 stationarity 残差 `1.654e-12`，原始/对偶目标残差 `5.093e-11`，所有现有非基本列的最大 reduced profit `7.11e-15`。未加载旧 master 的对偶价格。

## 对偶定价接口

`pricing_duals.json` 的 `rho`、`required_nu`、`request_eta` 均按 `target_order` 编号，`time_potential` 按 `time_nodes`。价格均来自本次新矩阵的新 LP。新增列的完整曝光起止必须是该 LP 的现有时间节点；不能插值未知节点的势能。

```text
joint_value(target) = max(0, score_upper - rho)
                   + required_nu × [factor_upper >= .5]
                   + Σ request_eta × [target eligible and full exposure inside request window]
reduced_profit = sum(selected distinct target joint values)
               - (potential[end] - potential[start])
```

同一 fiber 只能选一个目标，目标不能重复分配。`potential` 是 SciPy 等式约束的原始 marginal，时间代价的符号已经由现有列与 KKT 检查验证。pricing 的输入不得跨固定 report，质量计算需读取新 repair 划分的 `conditional_profile_new_repair_cells.npz`；浮点有限值与 `support>0` 都必须满足。

## 实际限制

MIP 的代理目标包括科学 max、required、REQ；report 固定为 100，Jain 在每个候选解求出后按实际 completion 重新结算。gap 为零只说明代理整数模型在当前列池最优，不能证明带 Jain 的完整有限问题最优，更不能证明原问题全局最优。

历史 score_lower 是 CSV 原值，有六位舍入误差；上界为 CSV+0.0000005。历史完成阈值没有舍入歧义。保留候选时要求改善超过两倍总误差界，否则保留原最好历史调度。新条件列的 DARK 下界使用 clean geometry、有效 E≤1 推出的 band 条件；无法确认 DARK 时只计 mismatch multiplier=1。实际隐藏偏移、未观察天气和未枚举的连续指向/曝光长度没有被证明覆盖。

所有结果均为研究结算，没有新比赛回放或新官方得分。目录中的 schedule 保留原最好 1184 列及固定 report。

## 文件与复现

- `column_pool.json`：完整新历史+条件 coupon 列池，hash 随 dual 导出。
- `pricing_duals.json`：新实例的可定价真实 LP shadow prices。
- `profile_cross_validation.json`：最新自身 clean q 方程对旧条件区间的独立检验。
- `conditional_profile_new_repair_cells.npz`：重新切分的条件质量区间，unsupported 为 NaN。
- `summary.json`：科学/required/REQ/Jain 结算、保底、MIP、LP、KKT 与来源摘要。
- `retained_schedule.json`：原最好历史调度及固定 report。

```sh
.venv-solver/bin/python formal_v4/research/best_incumbent_alpha_master.py
```

可加 `--historical-only` 为其他独立输出目录生成纯历史列 master；不使用 profile 或 coupon。不要用它覆盖本目录作为新质量数据的来源。
