# 因果信息价值路线：先验与设计记录（2026-10-04）

本文先读取官方文档与评分器后推导路线，随后才读取 `ALGORITHM_PORTFOLIO_ZH.md` 去重。只写本文与 `results/cold_information_value_20261004/`。

## 1. 仅从官方规则得到的问题

官方来源为 `upstream/gosim-observer-examples/docs/participant-guide.zh.md`、`runner/challenge/v4_workflow.py`、`v4_runner.py`、`v4_scorer.py`。模型是部分可观测有限时域控制：公开目录、几何、评分常数与粗公告；隐藏天气乘子、关闭、固定地形边界、仪器故障及 Hard mode 固定指向偏差。动作是曝光（60–3600 整秒、指向、逐光纤目标、program）、等待、零模拟时间举报或结束。曝光的命中集合和逐目标本次得分在下一请求公开；未命中与命中零分可严格区分。

终值是每目标有效曝光最高分之和，减 required 未过 0.5 完成门槛的逐目标罚分、Jain 均匀罚分，再加请求奖励与举报奖惩。曝光完成因子为 `min(f*t*q/(f0*t0),1)`，不累加多次曝光，因此一次短探针并不会等比例推进一次长曝光的完成状态。隐藏状态的估计必须以调度后果衡量。

## 2. 尚未读研究组合时提出的路线

选择“固定地形边界的决策定向主动探测”：开场公告只给方位八分区，而地形遮挡在整个周期存在。普通曝光已经给出几何命中和零/正得分；在站点可观测的假设下，零分指示该目标的全曝光路径被地形或其它关闭覆盖。短曝光在当前 slot 内、同一光纤视场同时包含地形候选边界两侧目标，可提供共同天气状态下的对照。若有正分命中目标作为对照，同次曝光其它命中目标零分不能归因于全场天气或仪器乘子；这是空间支持约束，不需数值天气回归。

状态 `s_t=(time, valid score ledger, required/request progress, bulletins, posterior b_t)`；隐变量 `theta=(azimuth sector bounds, altitude cap)` 加当前全场可观测指示 `C_t`、当前其它 directional closures。信念只由此前收到的公开消息和曝光反馈更新。把固定地形候选粒子 `theta_j` 经当前同场零/正结果的似然筛选；跨 60 秒路径的 score>0 意味着路径至少有一段未被覆盖，score=0 的负证据需对全场关闭/临时事件边缘作混合模型，不能直接当成地形真值。

有限 horizon 的目标：

`Q(b,a)=E[r(s,a,theta)] + E_y[V(s', Bayes(b,a,y))]`。

对比强制保持先验的 `Q_no_update(b,a)=E[r]+V(s',b)`，两者的后续决策差异才是信息价值；并不采用 posterior RMSE 或 entropy 作为奖励。近似为当前合法候选首动作 + 后续 1–3 次调度的粒子场景树，再把 terminal required 机会损失压成可见窗口的 deadline value。探针的未来价值应由“地形受影响且未来可择另一可见窗口的 required / 请求目标”驱动，而非对所有天区统一加探索项。

明确可检验差异：存在两种地形候选，给当前生产动作类似的期望得分，但会分别遮挡后续两个 deadline 群。若一次 60 秒对照曝光区分两候选，策略先探测再按结果换未来群；不更新 posterior 的策略对两个结果采取相同后续动作。若后验区分不会改变后续动作，任何探针都应被拒绝。

下一步先读已有研究去重；若已有路线覆盖此机制且已经否定，则停止或指出具体不同处。

## 3. 去重结论与实际的新内容

随后读了 `ALGORITHM_PORTFOLIO_ZH.md`，并追读 `terrain_policy.py`、`terrain_version_space.py` 和 `results/terrain_cpu_phase_L1_20261003/README.md`。已有 terrain 策略用公开正分被动排除“必然覆盖整条轨迹”的候选盒；`observe_zero()` 明确忽略全部零分，并把剩余先验盒的平均 clear fraction 直接交给即时 planner。它在 L1/L4 的完整季节对照为 −5.511046/−15.227743，未晋升。

本路线没有重复这项被动地图改动。新增机制是：对符合官方单采样结构的**同次曝光正分与零分对照**，用正分 anchor 的公开分数给未遮挡零分目标推导严格正下界，从而接受被动地图未使用的 blocked 正证据；然后按后验导致的后续动作差异评估一条合法短曝光的价值。它也不使用 Kalman/RMSE，不改变 C/E 估计，不重跑松上界、免费 report 或 program 证书路线。

现有生产 `policy.py` 会把 mixed feedback 的零分目标加入 1200 秒 `blocked_spots`，因此“看到零分后短暂回避附近方向”并非新机制。新内容必须保留为可识别的**整个周期固定地形支持约束**与主动信息价值，不应把已有临时回避改名。

## 4. 零分证据的严格条件

以下推导直接对应官方 `v4_scorer.py:score_target_exposure` 与 `v4_runner.py:last_result`，而非假定没有 instrument notice 就代表仪器正常。

1. 自己发起的实际曝光 `0 < d <= 120` 秒，完全落在由 initialize 夜历、900 秒网格推导出的一个公开 slot 内。
2. 发起时已经收到的最新 bulletin 必须是该 slot 的公告；其 notices 中没有非 terrain 条目。这依赖当前 V4 契约会公告该 slot 的方向关闭/质量事件。固定 terrain 在整个周期生效，没有曝光内 start/end cuts。
3. 只使用 `last_result.hits` 中的目标；未出现在 hits 的目标可能是错误纤维或高度不合格，不能当成遮挡零分。
4. 当前官方实现每个 hit 在这个曝光中只有同一个积分时刻 `t=start+d/2`。所有目标共享 slot 的 seeing、transparency、sky_quality、instrument_efficiency 和该时刻的 `_apply_fault`。纤维模型只有命中几何，没有单根纤维或目标专属仪器效率故障。
5. 同次曝光至少一个正分 hit 作为 anchor；其它目标若因共同背景关闭或共同仪器效率为零而零分，anchor 也必须为零。不能把来自不同曝光、不同 slot、不同积分片的 anchor 混用。

定义公共几何系数

`a_i = f_i*d*L_i(t) / (f0*t0*X_i(t)^airmass_exponent)`，

共同隐藏质量 `K = efficiency*transparency*sky_quality / (seeing*q0)`，以及是否未被固定地形覆盖 `I_i`。在这些条件下

`C_i = m_i*w_i*min(K*a_i*I_i,1)`。

未知 program 匹配乘子满足公开 `m_min <= m_i <= m_max`，本四卡 `m_min=1`、`m_max=1.2`。设收到 anchor 六位分数 `S_a`，舍入误差 `eps=0.5e-6`。即使 anchor 饱和，也有

`K >= K_min = max(0,S_a-eps)/(m_max*w_a*a_a)`。

因此，假设零分 hit `z` 未被遮挡，则其 score 严格下界为

`LB_z = m_min*w_z*min(K_min*a_z,1)`。

只有 `LB_z > eps` 时，收到六位 score=0 才与“未遮挡”矛盾。这同时处理未知 program 判档、亮度、饱和以及舍入；亮度或权重太小导致下界不足的目标会被拒绝。由于 `m_min>0`，program 不匹配不能制造严格零分；因子饱和同样不会制造零分。

这不是对未来扩展版本的无条件证明。若后续协议新增单纤维效率故障、未公告方向关闭，或者出现多个积分片，必须让该资格检查失效或重建模型。允许 current slot 中其它全场共同零机制，但它们会被同场正分 anchor 排除。Hard mode 的指向偏差只影响 hits 集合；只用已公布实际 hit 后不需要 actor 读取偏差。

## 5. 实际执行的微审计

代码为 `results/cold_information_value_20261004/probe.py`。重现命令：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 formal_v4/results/cold_information_value_20261004/probe.py
```

代码将强 native 历史 CSV 投影为 actor 原本会收到的 `(target_id, score)`、自身 start/end/duration、observe index，使用公开目录、夜历、评分与**已发布的当前** bulletin。CSV 中的 `factor/quality/prog_mult/fiber_id` 均不用于证书。先保存 public certificates 并记 SHA256，之后才由独立 `audit_truth()` 打开隐藏 terrain CSV 核对。离线审查读取 truth，不代表 actor 可读 truth。

| 卡 | 既有 observe | 单 slot、≤120秒且无临时公告曝光 | 正分约束 | 新 blocked 证书 | terrain 真值反例 |
|---|---:|---:|---:|---:|---:|
| L1 | 981 | 106 | 1451 | 0 | 0 |
| L2 | 1107 | 100 | 1336 | 0 | 0 |
| L3 | 993 | 108 | 1455 | 6 | 0 |
| L4 | 928 | 71 | 926 | 7 | 0 |

13 个 blocked 证书全部吻合本卡真实固定地形；5168 个正分约束也没有错误排除真实遮挡。L3 全部来自 rank254：六个零分 hit 的高度 48.042–49.108 度，方位 61.462–63.717 度；同场正分 hit 在 49.387–50.521 度附近。L4 全部来自 rank3：七个零分 hit 的高度 30.603–32.509 度，方位 122.881–123.366 度；同场正分 hit 在 123.860–125.093 度附近。L2 有 24 个资格曝光中的零分 hit，但没有同场正分 anchor，全部拒绝；这是必要的混杂过滤，不把零分总数视为可识别证据。

这些是**既有轨迹的公开反馈资格与支持约束审计**。没有修改实际 actor、没有生成新的实际卡曝光、没有完整重新规划，也没有证明增加证书会提高实际赛季得分。

## 6. 实际执行的官方评分器存在性实验

`synthetic_public.json` 在创建隐藏世界前冻结公共目录/规则/消息。两世界对 actor 完全同公开公告：S 方向固定地形；显式实验先验只有 `height_cap=40.0` 与 `42.2` 两候选，各概率 0.5，方位区间均为 150–210 度。不能把这个两点先验当成官方公开分布。

公开目录有一个在 41.4 度的 faint required 目标 A、同一合法 fiber field 内 42.5 度的 bright anchor，以及另一个安全方向 faint science 目标 B。最后只有一个 900 秒 slot。actor 首先做 60 秒有效科学曝光，实际同时指派 A 与 anchor；其后仅按收到的 A score>0/score=0 选择 A 或 B 的 840 秒曝光。两隐藏世界的后续 assignments 真正不同。官方纤维分类、整个曝光高度、逐路径积分、lunar、program band、best-only ledger、required 与 Jain 结算函数均参与计算；Jain 权重显式设为 0，未加入请求、data loss、动态天气或 report。

| 声明的有限策略 | 两世界等概率期望终分 |
|---|---:|
| 900秒 A 单次 commitment | −23.278167445 |
| 900秒 B 单次 commitment | −36.920556359 |
| 同60秒 A+anchor 探针，后续始终 A | −23.380987039 |
| 同60秒 A+anchor 探针，按反馈选择后续 A/B | **−17.273318847** |

相同首动作、只允许反馈改变续局，期望增益 **+6.107668192**；相对声明的两种900秒单次 commitment 中较好者，净增 **+6.004848599**。不更新后验的探针本身反而损失 0.102819593，说明正增益来自后续动作切换，而非短曝光自动有利。

这不是对所有合法策略的穷举，也不是强生产 actor 控制。其它曝光切分、field、未来消息和全季竞争未搜索，因此只证明“官方物理/计分机制中存在有正决策信息价值的观测”。不得称为实际 L1–L4 提分或已经可部署获益。

探索版先使用明亮 A/B，得到了 +12 的续局切换差；随后降低它们的 flux，使短探针不完成 required、后续840秒不自动完成所有 science，以排除过于容易的饱和场景。最终保留的是上表 faint 实验，源码与 MANIFEST 已锁定；探索数值没有用于选实际卡动作。

## 7. 冻结的下一实验：可证伪，不在本轮执行

先做**真实公开状态的行动准入**，无需启动整季：使用冻结 READY actor 的原生 kernel 与源、公开历史、原 C/E、原 report、原 ledger 和固定工作量；L4 仅取首个合格 mixed exposure 后 rank4 状态，L3 仅取首个合格 mixed exposure 后 rank255 状态，不另选点。检查两个固定地形后验是否改变后续完整物理动作。只用公开目录/几何及上述证书构造后验；隐藏 truth 只在候选冻结之后由 evaluator 裁决。

后验 value 应用两个或更多声明场景，把预测反馈相同的世界分到同组，并对每个反馈组选择**条件期望**最高的公共后续动作：

`V_info(a) = sum_y P(y|a) * max_c E[terminal_increment(a,c) | y]`，

`V_frozen(a) = max_c E[terminal_increment(a,c)]`。

不能先对每个隐藏世界分别取 `max_c` 再求均值；那会给 actor 未获得的信息。终局增量必须同时结算 science max、required、REQ quota、Jain 和 observe rank 的失效风险，当前探针的时间成本必须包含在两个分支中。首次候选只取冻结 parent 的合法曝光 field 与 60 秒完整指派，不通过加大搜索池救结果。若 slot 剩余不足60秒、没有同场可靠 anchor、后验不改变任何完整动作，或 `V_info−V_frozen` 不覆盖当前机会损失，则不发探针。

预声明的否证：两个状态均没有合法动作切换，便停止这个候选集上的主动信息路线；若出现动作切换但公开控制不能逐动作重现冻结前缀，先判实验无效。仅有合法切换且前缀门检通过后，才值得做同源、同预算、同公共前缀的**真实重规划到季末**教师；L3/L4 的后验不应按真实边界选参，最早 qualifying point 固定且负结果完整保留。完整赛季若均值不正或新增 required/REQ 损失，则拒绝部署。

本轮到此停止：实际执行约 0.28 秒 CPU 微审计和官方合成存在性实验；未执行上述 action-gate、完整 season replanning、NN/GPU 训练、SSH 长作业、生产代码改动或网站提交。`MANIFEST.json` 保存 own probe/官方源码、历史输入与 actor-public 证据哈希。
