# 独立搜索化简：目标退场商只在季末有效

2026-10-04。先独立读官方评分器、runner与几何并形成初稿，才读portfolio、旧剪枝与存活风险研究。初稿保存在 `../results/cold_search_reduction_20261004/independent_draft.md`。

本轮得到一个**条件性、保持终局得分的动态账本商**：回溯失效已结束，且公开几何证明某目标余季不可能再得正factor时，可把其逐目标得分状态归入常数与计数。它保留活目标身份、访问编号、报告状态和完整信息状态。没有修改参赛程序，没有新赛季、提交、GPU或远端任务，也没有实测提分或搜索速度提升。

实际范围较小：四卡最后七夜及最后一夜开始时都没有可退场目标；最后一小时才减少 **33.15%–41.51%** 的动态得分数组。不能把这个比例称为搜索树减少，更不能称为整个actor memory减少。它适合季末beam、B&B与转置表，不能解决主赛季搜索膨胀。

## 1. 独立模型与官方依据

依据是 `upstream/gosim-observer-examples/runner/challenge/v4_runner.py`、`v4_scorer.py`、`v4_fiber_map.py`、`tile_geometry_simulator.py`、`v4_workflow.py` 及participant guide Appendix A。实际运行 `runner/verify_engine.py`，16个文件全部匹配manifest，源提交 `db4bddf3cc67fb5f0036d9fb2cf90b9e2b7e8f4a`。

固定隐藏世界中，物理状态包括当前模拟时间、observe_action_index、有效历史账本、故障修复时间、误报额度、连续report数、消息与请求结算游标、pending wait、loss是否触发。隐藏世界包含天气、事件、固定pointing offset、未来请求和失效计划；正式在线状态还必须包含由已公开反馈得到的联合belief。

访问次数不直接累加科学分，但空命中observe也增加索引，并改变数据丢失触发时的N。wait与report不增加N。报告不耗模拟时间，却改变故障与误报额度。曝光命中集合、零分hit、miss、program对score的不同解释均会改变信息状态。只保留ledger不能形成精确在线Markov状态。

终值为

\[
\sum_i b_i-P\sum_{i\in Required}(1-r_i)-U(1-Jain(o_k/N_k))
 +\sum_q R_q\,1\{\sum_{i\in q}z_{qi}\ge m_q\}+Report.
\]

b_i是有效science score最大值；r_i、u_i分别是独立最高raw factor是否达required与Jain阈值；o_k是band k中u_i=1的数量，N_k为完整目录的band总目标数。z_qi表示是否存在**完整位于请求窗内**且raw factor达该请求阈值的有效曝光。三个阈值须分开，即使本地默认都为.5；它们不累加访问，science最大值对应的factor也不能替代这些完成状态。

本版本 `_data_loss_plan` 只取data_loss首行，`loss_triggered` 永久置真，所以同一已核验runner中至多一次删除。公开Appendix A本身没有保证任意隐藏实例只能删除一次。下文始终要求“无剩余回溯失效”；pre-loss Hard状态不得套用，也不得把参考生成器的单次事件作为额外公开承诺。

## 2. 去重：停止单连续删除窗路线

独立初稿推导了：对每目标science只保留左与右record maxima；每个完成谓词保留最早与最晚witness。中间项被更早和更晚的高值夹住，单个连续删除窗若不含中项就不能同时删除两侧，所以中项不影响删除后的max或完成OR。

查重发现 `survival_hedging_REPORT_ZH.md` 已覆盖score-layer极端witness与未知随机窗口；`cold_pruning_ledger_audit.py` 已实现固定窗口与有限未来N的存活签名。因此它是已有结论，本轮停止，不重复计算或包装为新增算法。

新内容限于下述**跨目标身份的终局得分商**。它与旧方法按同一target及survival signature保留max不同：它允许已经永久失去正分机会的目标不再各自占据搜索节点动态数组。

## 3. 公开几何给出退场证书

令t为决策时间，D为公开max_duration_seconds，公开夜历为[a_j,b_j)。若未来曝光获得正factor，它必须与至少一个正weather slot重叠，其开始时刻s必在

\[
 s\in\bigcup_{b_j>t}[\max(t,a_j-D),b_j).
\]

**夜开始必须向前扩D。** 官方runner允许曝光在daytime gap开始并跨入下一夜；只检查[a_j,b_j)会漏掉合法正分机会。夜尾裁短也允许，本证明没有错误地减去最短60秒曝光长度。

对目录目标i，用公开site、RA与Dec计算它在以上区间的最高高度M_i(t)。官方LST线性随时间增长，

\[
\sin alt=A_i+B_i\cos H_i(s),\quad
A_i=\sin\phi\sin\delta_i,\quad B_i=\cos\phi\cos\delta_i\ge0.
\]

每区间最高值只可能在两个端点或其中的上中天H=0 mod 360。若M_i(t)<minimum_altitude，则任意可能正分曝光的起点都违反 `min_altitude_during` 的起点高度约束，不会形成可评分hit。所有未来曝光对它均只有factor=score=0，独立于天气、事件、故障修复、program与pointing offset。

定义退场集合F(t)为获得该证书的目标，活集合A(t)为补集。实现用float64解析端点与上中天，加1e−7度保守留边界；采样核验不能替代区间算术证明，因此本轮是带数值容差的解析证书实现。没有使用隐藏天气或方向事件判退场。

退场是**得分账本退场**，不删除目录或动作能力。某目标仍可能被用作零分hit/miss探针，其反馈可改进pointing与天气belief；这种action不能仅按零即时分删除。

## 4. 保持终局得分的商状态

在无剩余失效条件下，保留每个活目标的b_i、required完成位r_i、Jain完成位u_i；对每个尚未固化的已发布请求，保留活成员完成位z_qi。退场目标只保留：

- B_F=∑_{i∈F}b_i，科学分常数。
- M_F=退场required中尚未达阈值的数量，罚分常数。
- O_Fk=每个RA band的退场已完成数量。
- D_Fq=每个未固化请求的退场已完成成员数。

完整目录的N_k和target ID、band、required与request membership映射作为共享静态数据保留。访问编号n、当前时间、报告与消息状态、belief均保留。原始factor数值若用于后验学习，也由信息模型保留；终局得分子状态只需要相应阈值位。

已有请求在d_q≥m_q后奖励不可再撤回，可以固化R_q；已过期请求的奖励亦可固化。剩余请求如果

\[
 d_q+\#\{i\in A(t)\cap q:z_{qi}=0\}<m_q,
\]

则即使所有可达未完成成员都达标也不能成功，可精确删除其未来奖励目标，最终奖励为0。它仍可能出现在协议中，不能因此修改收到的消息。

**未来新请求不破坏化简。** 未发布请求的issuance>t，而历史曝光start≤end≤t，不能完整位于该新请求窗内；退场目标未来也不可能获得正factor。因此，在官方正完成阈值条件下，其对新请求必为未完成。请求发布后只需读静态成员表，为活成员建位图，并用上式判定是否已经不可能。不得把旧全季完成位用作新请求证书。

**证明。** 对任意未来动作序列，退场b、r、u与已有请求完成位均不变，活目标按原规则逐项更新。因此科学分为B_F+∑_A b_i，required缺失为M_F+活目标缺失，band观测数为O_Fk+活目标完成数，请求完成数为D_Fq+活成员完成数。代入官方全部终值项即得到同值。新请求由前段理由不依赖退场历史，归纳可跨任意未来决策和请求发布时间。

这是**终局得分的商**，没有证明完整协议输出逐字节相同：例如未来零分命中可改变终局diagnostic `targets_observed`。如需要该计数或全部输出复现，另保留相应ID位图。公开的退场请求completed_target_ids可由已有公开历史保留；不能把actor memory或反馈transcript一并删掉。

## 5. 能用的转置合并与支配条件

固定t，静态A(t)与F(t)对所有节点共用。在当前时间、n、故障与报告及消息状态、信息状态完全相同，而且活目标与未固化请求位图相同的节点中，如果O_Fk与D_Fq也相同，退场目标具体哪些ID贡献了分数对未来payoff无关。

把C_F=B_F−P M_F+已固化请求奖励作为终值常数。其余条件相同且C_F(A)≥C_F(B)，则对每一条未来动作序列，A的最终得分至少为B，可删B。不是比较不同目标集合动作的即时总分：它只比较**已证明没有未来正分支撑**的历史部分，并要求未来耦合计数一致。

隐藏世界情景模型中要逐情景保存该状态及相关性；支配须在相同情景与相同联合belief下逐情景成立。期望C较高、当前science较高、当前Jain相同都不足以删另一个信息状态。正式POMDP的完整belief相等若无法证明，就只压缩每情景的账本数据，不合并belief或删搜索节点。本轮没有证明现有生产belief representation是精确充分统计量。

Jain不能只留当前标量。两个合法比例向量(.5,.25)、(.25,.5)当前Jain同为.9；同样给第二band增加.25后，Jain分别为1.0和.8。因此O_Fk必须逐band保留。请求成员数、required完成位及同一隐藏参数的相关性也不能换成无关联的边际概率。

## 6. 实际计算与数量

完整脚本与数据在 `../results/cold_search_reduction_20261004/`。`audit.py` 导入未修改官方BestLedger、required、uniformity与request scorer，读已有READY native四卡记录，不运行agent。读取的六位factor列仅为离线bookkeeping teacher；不把舍入数据审计称为未舍入runner重放。

19个实际曝光决策边界与1个仅作结算检查的终点，每点100个任意活目标后续更新，共**2000组**；新增factor含0、.49、.5、.51、1，验证独立完成位与Jain效应。终点的100组为空更新。任意活目标更新是合法未来动作的代数超集。每点同时核验原记录后续没有退场目标的正factor项，并比较前缀与最终官方全部payoff分项。该检查使用六位CSV，不能替代未舍入重放。最大总值差 **2.1464e−10**，来自求和顺序；正factor退场违例0。额外官方高度采样没有超过解析上界（最大约5.69e−14度）。总审计78.987秒，是验证成本，未测搜索提速。

下面是**字面固定剩余时间**的公开几何数量，避免把“向后找下一个实际决策”当作恰好剩余1小时。动态数组为每目标float64 best和两个uint8完成位，另加三个8字节常数及int32 band计数；静态目录、历史、belief与allocator开销均排除。实际前缀审计直接用NumPy `.nbytes` 计量同一结构。

| 卡 | 目标数 | 最后一夜开始可退场 | 剩余1小时退场 | 原动态字节 | 商状态动态字节 | 字节减少 |
|---|---:|---:|---:|---:|---:|---:|
| L1 | 7800 | 0 | 3245 | 78000 | 45622 | 41.51% |
| L2 | 8600 | 0 | 2858 | 86000 | 57492 | 33.15% |
| L3 | 8700 | 0 | 3224 | 87000 | 54832 | 36.97% |
| L4 | 8800 | 0 | 3320 | 88000 | 54876 | 37.64% |

L1与L2的“无未来loss”在本轮是已知本地场景条件；正式在线需公开普通卡约定或其他有效依据。L3与L4所测点都在已有state_resync之后，使用已核验单次runner条件。L3请求的15分钟“下一个实际observe边界”不存在，原脚本回落到survey_end导致100%退场；结果标成 `terminal_no_search_state` 并**排除存储收益主张**。字面15分钟的L3退场数是3359，不是8700。

另一个小型有限账本族：8个退场目标、两RA带、一个quota请求、相同live状态与observe_index=8；256个历史账本压成**57个终值等价类**（减少77.734375%）。每个历史穷举两个活目标的16种后续，**4096次官方结算误差0**。这是合成代数族，未枚举合法物理排程，不是实际beam搜索树减少率。

一个报告反例修正单独记录在summary中：首版示例用了1.5的RA比例，超出合法[0,1]域；改为上面的.5/.25+.25后仍得到同当前Jain、异续局Jain。几何与账本主审计代码未改变，不重跑78秒验证；已执行源保留为 `audit_executed.py` 及原SHA。

## 7. 本轮停止与交付

这是新的条件性账本化简，实际只有季末明显缩小。没有当前合法动作排序反转，没有真实搜索node数或速度证据，也没有全季提分。停止追加宽搜索、远端作业与赛季测试。若后续确实实现季末完整field与时长搜索，可以直接使用该商做节点内存布局与满足严格条件的转置表；pre-loss和信息状态不明时保持原历史。

复现：

```sh
.venv-solver/bin/python formal_v4/results/cold_search_reduction_20261004/audit.py
.venv-solver/bin/python formal_v4/results/cold_search_reduction_20261004/toy_quotient.py
```

数值为 `summary.json`、`fixed_times.json`、`toy_quotient.json`；初稿、已执行源与最终源均保留。没有改动其他代理文件或生产代码。
