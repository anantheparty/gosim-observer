# δ 请求配额：最终有效账本、固定 rank 双替换与补偿链

本目录只读取本队官方输出、公开目录/规则及先前条件质量区间；没有读取隐藏天气、事件真值或生成器，没有改生产策略、提交包、服务或 Git index。**下面的新数值都是条件模型账本，尚不是新官方分数。**

## 1. 可靠失败原因：曾经 6/6，后来变成 4/6

当前基准是 `cloud_request_gpu_delta_20261003`，官方总分 **6423.086757**。δ Request、Cache、Verified Portfolio 的 REQ1 证据相同：

- 请求时间为 2026-10-26 00:15 至 2026-10-27 08:30 UTC；8 个目标、单次完成因子门槛 0.5、需要至少 6 个 distinct 目标、奖励 100。
- 在最终失效处理前，已取得 6 个完整窗口内、factor≥0.5 的实际命中：4993、7389、7669、5585、654、7281。
- 5585 的合格观测为 rank159，2026-10-26 07:15:08–07:25:29，factor **0.781887**。
- 7669 的合格观测为 rank166，2026-10-26 07:45:00–07:48:29，factor **0.545239**。
- 之后，2026-11-08 05:16:53 UTC 的 data-loss 事件在 observe_count=603 时失效原 rank **[150,169)**。这两个合格命中都失效。
- 官方在最终有效账本上重新计算请求奖励，即使请求 deadline 已过去，最终也只剩 4 个完成目标，奖励由 100 变为 0。

因此这两次不是几何 miss、factor 不足或曝光越过 deadline，而是**未来 data-loss 对过去请求完成证明的撤销**。有长期后效性。原 DP 如果只检查 deadline 时的完成 mask，就会过早认为配额已经兑现。

其他两个缺目标 3840、6696 没有完整请求窗口内的 assignment；不能从这点推出几何不可见或天气不允许。7281 曾有实际命中但质量/factor 为零，随后 rank215 成功；零质量的命中不能当成几何 miss。7389 窗口外的观测也不能计入本请求。详见 `delta_official_request_forensics.json`。

旧 CD2/Phase δ REQ1 是实际 raw3/final3；Request/Cache/Portfolio δ 才是 raw6/final4。不能笼统声称所有卡所有包的 REQ1 都失败；例如新 Cache α 的两个请求都成功。

## 2. 最小修改的数学模型

固定所有原曝光区间、时长、原 until 等待、报告动作，以及每个 observe rank。每个原时段 j 的列集合 C_j 含原动作和有限的新指向/assignment，要求：

\[
\sum_{c\in C_j}x_c=1,\qquad x_c\in\{0,1\}.
\]

这样 observe 数、完整起止时间序列、未来 trigger count 和 invalidated rank 都保持。仅允许在失效区间外改指向；原失效区间内的动作也逐条保留。

对目标 i，科学分是所有最终有效已选列的 score 最大值，mandatory 完成是所有最终有效列的 factor 最大值≥0.5。REQ 完成则另外要求该列整个曝光在 issued/deadline 内，且 factor≥0.5，同一目标只计一次。用 binary u_i 表示 REQ distinct，binary h 表示配额奖励：

\[
u_i\le\sum_{c:\ c\text{ 为 }i\text{ 的完整窗内有效合格列}}x_c,
\qquad 6h\le\sum_{i\in R}u_i.
\]

科学 max 可用 winner 变量 z_ci≤x_c、同一目标 Σ_c z_ci≤1 精确建模；positive objective 自动选择该目标 score 最大的已选列。mandatory completion 同样用 binary coverage。先优化科学+mandatory+REQ 的有限 MILP，再按最终全局目标 factor 账本精算实际 RA 10° 分带的 Jain 惩罚和固定 report settlement。

本轮最终质量/有效性是列系数的假设；不能把原列被 invalidated 的 score 直接搬到新时段。本轮保持 count/time/rank，使 loss 规则不变，才可继续使用原 final validity。

只优化请求、固定其余资源成本时，8 个目标的 mask DP 只需 256 状态，复杂度 O(列数×256)；科学 max、mandatory witness 的删除/补回把不同目标耦合起来，故本轮使用有限列 MILP。若允许新增/删掉 observe，必须增加 count/rank 和事件历史状态，当前 rank 固定证明立即失效。

## 3. 数据覆盖和候选族

请求窗口内原曝光 123 次；其中失效 rank 19 次，剩余 104 次。

- 旧 δ 条件质量 profile 先对当前 Request δ 独立交叉验证：394 次曝光、5430 行 positive clean q，0 行越过旧区间；13 次处于旧/新 repair 差异区间，648 次缺窄区间支持，均排除。
- 请求窗口内 104 次有效曝光中，76 次满足覆盖和 cell 宽度≤1e-4；28 次无此支持，排除。
- 按原指向仅换单根 fiber，在 104 次有效曝光扫描 4 个最终缺目标，**0 个**候选满足官方 glass、>.03° margin 和整段可见性门检。需改变指向。
- 5585 有 10 个受支持时段、7669 有 29 个；各放入 16 个 fiber 中心，得 **624 列**。3840、6696 在这 76 个固定且受支持时段没有 factor lower≥0.5 的节点。这只是该受限时段族的结果。
- 双替换全枚举：**71,680** 个不同 anchor/不同 rank 配对，**62,208** 对恢复配额；稀疏全局账本精算用时 5.83 s。此前 top20 仅为探索，最终已经去掉此漏检。
- 为补偿删除 witness，另生成 7281/7493 共 **224 列**：7281 为 11 个时段，7493 为 3 个时段。合计 848 新列 +1096 原列 = **1944 列**。
- 最终 MILP **22,802 变量、30,876 约束、65,901 非零元**。所有原时段恰好选一列。自由四替换、保持原 mandatory 四替换、无限替换整个有限池、强制配额且保持原 mandatory 的模型分别求解；均在约 0.1–0.3 s 级完成。

## 4. 可执行双替换

最佳仍只改以下两个原 observe：

| rank | UTC 区间 | 时长 | anchor | anchor factor lower | 最小 glass margin |
|---|---|---:|---|---:|---:|
| 217 | 2026-10-27 07:04:19–07:07:51 | 212 s | 7669 | 0.553013000 | 0.050226° |
| 221 | 2026-10-27 07:44:35–07:50:57 | 382 s | 5585 | 0.511071670 | 0.057151° |

完整动作在 **`delta_compensated_conditional_actions.jsonl`**；SHA256 为 `27a5cf5ca96e6df2d8f952a01d5eff941915b04535a8239e1592927418b79258`。它与 `delta_rank_preserving_conditional_actions.jsonl` 一致。

原协议 actions 是 **1275 条**：1096 observe、178 原 until_utc wait、1 report。`decisions.csv` 的 **1856 行**是展开执行记录，不能混称 actions。本导出复制原1275条协议动作，仅改2条observe的pointing/assignments；178个until等待对象和report对象逐条相同、全部observe时长相同。没有把展开等待改成duration等待。原 ranks[150,169) 逐条相同。证明门检见 `delta_final_plan_gates.json`。

条件结算：

| 分项 | 原账本 | 双替换 | 变化 |
|---|---:|---:|---:|
| 科学 max | 6523.825773 | 6519.917164 | −3.908609 |
| mandatory 缺数 | 6 | 7 | −50 分，丢 7493 |
| REQ1 | 4/6，0 分 | 6/6，100 分 | +100 |
| Jain 惩罚 | 0.739024 | 1.613939 | −0.874914 |
| REQ2/report | 100/100 | 100/100 | 0 |
| 总分 | 6423.086749 | **6468.303226** | **+45.216477** |

原官方 6423.086757 与 CSV 重建差 −0.00000824。9400 个公开目标的科学 CSV 六位四舍五入总误差保守界为 ±0.0047；本轮变化远大于此误差。

为什么最便宜的 5585 替换没有胜出：rank215 只损失约5.62分，却删掉了 7281 唯一窗内成功 witness，因此另加7669也只有5/6。rank221方案保住7281，却删7493的唯一mandatory witness。这是明确的补偿链，不能只叠加独立列 reduced cost。

## 5. 有证明的范围及剩余障碍

全624列双替换族没有保持原mandatory缺数的合格配对。加入224条7281/7493补偿列后，1944列整个有限池的 proxy MILP 仍最优选择同一双替换；强制 REQ1 成功并保留原558个已完成 mandatory 的整个有限池模型 **infeasible**。这证明有限候选池内无法兑现这条补偿链，**不证明物理上不可补偿**。

整个有限池在固定 lower 系数下，“科学+mandatory+REQ、忽略 Jain”的最优账本值为 **6469.917164**，最优 dual gap=0；实际选出的条件 Jain账本为6468.303226。此上界只针对该有限列池、固定 lower 系数和固定时间/rank模型，**不是原问题、真实天气或隐藏状态的理论上界**。Jain没有直接进入MILP，所以也没有声称有限池真实Jain目标已经证明最优。

候选限制还包括：仅原受支持时段、16个anchor fiber中心、单一背景fiber效用选择、zero pointing offset、>.03° margin、整段可见及 reference directional-clear 门检。旧profile与自己的新观测一致并不证明未知未来天气相同；DARK score lower 还采用显式 E≤1 条件。全17个新assignment重新通过官方zero-offset玻璃/整段可见性与clear门检。未知方向遮挡、天气、offset及repair模型仍必须由官方回放最终验证。本任务没有提交。

要改善此局部模型，需新增受支持时段/不同pointing与assignment的恢复列（尤其7281和7493），或在更大时间块重新安排，同时建模计数/rank触发，而不是再扫同一列参数。更大的总分差主要来自科学覆盖，本次100分quota仅提供一个可解释、可执行的增益方向。

## 6. 文件和复现

- `delta_official_request_forensics.json`：5个本队δ官方输出的请求raw/final有效账本及input SHA。
- `delta_profile_cross_validation.json` / `delta_same_pointing_scan.json`：旧profile独立门检及0同指向候选。
- `delta_one_for_one_columns.json` / `delta_compensation_columns.json`：848条条件新列。
- `delta_all_pairs_exact_ledger.json`：全配对结算、完整变化target ledger。
- `delta_fixed_rank_compensation_master.json`：四种有限MILP结果和可执行最佳动作。
- `delta_final_plan_gates.json`：原action/等待/rank/count、17条geometry门检、误差和source SHA。

代码在 `formal_v4/research/request_quota_failure_audit.py`、`request_rank_fixed_exchange.py`、`request_rank_fixed_master.py`。使用已有 `.venv-solver/bin/python`：

```sh
.venv-solver/bin/python formal_v4/research/request_quota_failure_audit.py
.venv-solver/bin/python formal_v4/research/request_rank_fixed_exchange.py
.venv-solver/bin/python formal_v4/research/request_quota_failure_audit.py --anchors V4T007281 V4T007493 --stem delta_compensation
.venv-solver/bin/python formal_v4/research/request_rank_fixed_master.py
```

有限family全枚举与MILP都很小；没有“超过900秒不可计算”的证据。未扩大到连续全物理指向、所有曝光起止/时长的全局搜索，因而没有那个全集的可验证枚举计数。
