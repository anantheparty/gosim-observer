# 跨夜全季科学 max + required + REQ 有限列主问题

日期：2026-10-03。脚本 `research/season_science_required_master.py`；只读本队已合法下载的第一轮 α/δ 输出、公开目标/夜历/配置、generation 的质量区间。普通 CPU，合计约 5 秒。没有 hidden weather、网络 choose、GPU、策略/服务修改或 Git index 操作。

## 模型与原解保留

保留全部历史观测为固定开始/结束、指向、分配、共同 program 的候选列。历史有效的逐目标科学 score/factor 取自己的 CSV，失效历史贡献为零。新增列从此前每漏掉 required 的最强四个质量区间机会生成 16 种玻璃中心指向，以完整公开目标填充空余光纤。每 fiber 唯一 target，forced anchor 保留，其余选条件科学收益最强目标；整条曝光方向轨迹按参考域保守 clear 过滤，官方球面玻璃几何检查，最少 .03° 玻璃余量。

新增列使用官方 PublicQualityMatrix 分槽中点系数乘 Z 的 lower/upper：raw factor 下界封顶1；共同声明 DARK，只有背景 band 下界已≥.65 的目标计1.2匹配倍率，否则 lower 倍率取1。upper 统一使用1.2，属于乐观 program 松弛。没有把 quality 截到1，没有使用 NNLS 点曲线。

时间节点是所有列开始/结束，观测弧二元、相邻等待弧连续，单位流守恒选望远镜路径。每目标增加 winning simplex 变量：winner≤对应列x、同目标 winner 和≤1。选列x整数时，连续 winner 的最优解恰好只取得已选列的最大 score；这是科学 max 层的等价紧凑表示，**不会按观察次数重复加分**。

required distinct 完成位获得50、扣全部 required 常数；两条 REQ 各自8个 distinct目标位+quorum6/reward100，按曝光 wholly within issued/deadline window 判定，未固定免费 REQ 奖励。均匀度没有放入MIP，但对完整候选的 max raw factor/RA bands 精算。report 动作在原 UTC 保留，settlement 固定。若整数候选在 CSV 误差内不比原解好，则保留整份历史 incumbent，避免无收益删除观测的路径变化。

## 结果

| 项 | α | δ |
|---|---:|---:|
| 原观测列 | 1194 | 1053 |
| 新增完整指向/分配列 | 192 | 64 |
| MIP变量 | 21264 | 15993 |
| 原总分（官方） | 7094.664204 | 4818.222318 |
| CSV重建总分 | 7094.664229683 | 4818.222302899 |
| 保守主问题候选净变化 | 0 | 0 |
| MIP gap/status | 0 / optimal | 0 / optimal |
| 乐观条件有限LP upper（去掉均匀度） | 7178.510737 | 4881.033050 |

科学舍入误差界取每个 target .5e−6，α≤.005、δ≤.0047；总分重建误差分别2.6e−5、−1.5e−5。required数量、两条REQ奖励和实际均匀度均复现。MIP/LP各只需约 .05–.13 秒，其余是公共几何建列与边际分解。最终 `schedule.json` 保留原历史排程及原report时刻。

## 机会成本并非仅丢科学

α最不坏的新单列：V4T008897，10/6 UTC05:45开始3600秒。它替代9条旧观测：科学−48.3816；新增弱required的同时，失去原仅靠这些被替代曝光达标的其他required，required项净−400；均匀度+0.0144，总−448.3672。

δ最不坏的新单列：V4T003563，11/29 UTC06:51:11开始3600秒，替代4条旧观测。科学−32.3296、required项净−200、均匀度−.6535，总−232.9831。

因此之前25目标可覆盖/1250毛收益的子问题没有包含完整机会成本；新模型把丢掉的科学、其他mandatory、REQ窗口的连锁影响一起计入，拒绝了这些替换。**这不证明原方案全局最优**：新列只围绕旧missing构造，未生成补回被挤出mandatory的其他跨夜列。后续对偶pricing应覆盖所有target科学层、所有required和REQ incidence，生成能够共同重排的列，而非只给漏掉目标排序。

## δ失效是按排程索引决定：为什么锁前缀

证据完全来自自己的官方公开 `messages.jsonl`，state_resync UTC `2026-11-08T05:28:34Z`：

```
action_count_at_trigger = 552
action_index_start = 137
action_index_end_exclusive = 154
window_start_fraction = .249401
window_end_fraction = .280523
```

这些比例不是从 reference 或 hidden stress 读取。官方公开 `runner/challenge/v4_runner.py` 的 `publish_due_messages` 在触发后的首决策冻结 observe_index=N，然后 floor(fraction*N) 得到失效 rank 区间。替换早期排程会改变 N/rank，不能继续把旧 valid flag 当新排程的有效性。

本版本为确保相同公开失效结果，**固定原前552条曝光全部选中，禁止所有新列开始在原resync之前**；对应同一触发跨界曝光和原17条失效曝光。δ因此只剩后期64新增列。它是清楚、强限制的条件模型；没声称保留rank即可保证新 fault 检测/report诊断相同。所有report UTC另行固定，旧Z依然条件于相同有效E路径与同一外生天气/fault实现。

## 上界与可审阅结果

- `lower_surrogate_dual_upper_without_uniformity`：保守系数主问题的MIP dual bound；只约束这个 surrogate。
- `conditional_optimistic_finite_LP_upper_without_uniformity`：历史score加CSV上舍入、新增Z upper/factor upper、最高program倍率，全部整数变量放松，并去掉非负均匀度罚分。是**固定列池、参考域、固定报告/有效性情景**的upper。
- `omitted_column_global_bound_available=false`：没有证明遗漏连续起点/指向/时长列的 reduced cost≤0，所以不把有限LP当完整问题upper。
- 原隐藏指向偏差未被恢复；新增候选声明零offset、.03°玻璃余量，只是明确几何条件，不是未知offset的严格证书。
- 输出不是官方 replay，也不是当前线上策略的新实测分数。

每卡目录中 `summary.json` 有模型规模、原/候选全分项、上下界、官方消息证据；`single_column_counterfactuals.json` 有每新增列完整机会成本；`schedule.json` 是可审阅整季动作时间表。新增数据与脚本不含凭据。
