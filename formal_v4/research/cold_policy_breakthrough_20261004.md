# 正式 v4 冷启动机制研究（2026-10-04）

## 读取边界与独立初稿

本节在读取 `ALGORITHM_PORTFOLIO_ZH.md` 之前形成。首先只读官方参赛说明、`v4_runner.py`、`v4_scorer.py`、`v4_fiber_map.py`，以及固定官方生成器 `official_generator_e01939d0/challenge/v4_weather_simulator.py`、`v4_observation_requests.py` 和公开卡 public/config。没有读取 truth 数据、pair_audit 或 teacher labels，也没有启动全季或 GPU 任务。

### 问题抽象

状态分为完全公开的几何/目录/日历、带延迟的最佳成绩账本、隐藏的随机天气和仪器状态。动作是连续指向、每格一个目标、整数时长 60–3600 秒和三种 program。几何命中只在曝光开始判定，最低高度须贯穿整次曝光。无指向耗时或曝光固定开销。

目标函数不是积分曝光：每个目标只保留一次最好的有效贡献；required 与请求以最大单次完成因子是否达到 0.5 判定，多个不足曝光不叠加。普通科学分最高约 0.3–1.2/目标，required 缺失为 50/目标，限时请求和正确 report 通常各 100 分。Jain 均匀度的总权重仅 200。最佳 score 与最大 factor 是不同账本，program 倍率不进入 0.5 门槛。

官方生成器给出可利用的动力学，而不需要恢复随机 seed：seeing/transparency/sky 为有界的夜间 AR(1) 与 slot AR(1)，slot 相关系数 0.88；仪器基线每个开放 slot 独立 jitter 0.9–1.0；背景关闭有持续性；地震效率按夜衰减；故障持续至下一故障或季末，report 成功后即时修复。粗消息精确报告事件与该 slot 相交，却不报告强度和扇区边界。

### 五种机制的独立比较

| 机制 | 可以利用的结构 | 主要代价/失效点 | 初步判断 |
|---|---|---|---|
| 遗传/群体算法 | 联合改变指向、时长、目标序列 | 把全部季节作为染色体，真实未来不可知；每次适应度评估都很重 | 可做低维局部组合，完整季节容易耗尽 900 秒墙钟 |
| 图/流/整数优化 | 目标到未来时间窗边、required 覆盖 | 一次曝光是目标超边；各超边重叠且 program/天气随机，普通最小费用流忽略这些耦合 | 适合提供容量影子价，但必须验证最终总分 |
| 剪枝搜索/DP | 给定有限候选时可精确更新 max 账本 | best-score 使状态维数随目标数增长；两步贪心容易重复挑短曝光 | 适合少量临近到期目标，不宜直接全季穷举 |
| 概率状态估计 | 用命中 score 反推质量；持续故障与短期天气具不同动力学 | 饱和删失、program 隐藏 band、方向事件造成多解 | 最可能以低成本纠正系统性状态错误 |
| 普通 NN | 预测目标未来最终成绩、动作终局价值 | 公共自然轨迹没有反事实终局标签；行为分布与部署分布不同 | 若能先有可靠概率物理状态，再学小残差有价值 |

初选路线：**基于正式生成器动力学的删失观测混合状态过滤，加上精确 report 决策**。它不是再扩大几何候选搜索，而是纠正普通调度器无法区分“天气质量下降”与“仪器效率故障”的状态错误。当前公开完整自然控制成绩中 L3 report 结算为 0，L1/L2/L4 为 +100；所以首先把可得的 100 分故障奖励和后续效率恢复当作可检验的目标。非免费 report 的单次直接收益条件是 `100 p -150(1-p)>0`，即故障后验 `p>0.6`；加入修复后剩余科学收益后门槛还会下降。此处只是候选，不能据此宣称已增加总分。

具体最小实验：在现成自然控制的公开 `(action,last_result,new_messages)` 轨迹上逐步反演每个未饱和目标的共同质量，保留 program 可能倍率造成的分支；按正式 120 秒积分复现已知 lunar/airmass。将持续下降解释成故障或地震的模型与单一 C/E 点估计比较，在每个可能 report 时刻给出后验与所需阈值，并用随后的公开 report 反馈核验。完全不读其终局 target 标签或实际天气真值。只有出现可核验的真实故障时刻证据后，才建议少量单状态 report 接续实验。

## 查重后的路线修订

组合清单表明，双层 Kalman 已降低预测 RMSE 却使强基线全季下降；同槽 C/E 约束投影最终 L2 下降46.773815；花免费report额度的诊断在完整Phase下平均下降92.2901055。原初选的滤波/诊断方向不能仅靠换成粒子数更多的实现重试，本轮停止该初选。

重新选出一个窄但可直接贡献终分的机制：**终末动作前结算未用免费 report，随后执行已冻结末动作**。这一机制利用有限期限控制问题的边界条件：如果后续不会再规划，免费误报额度已经没有未来机会成本。它不是早期免费诊断，且屏蔽新增report对原actor belief的影响，直接排除已有失败中的belief reset轨迹交互。只在公开数据能证明下一动作将结束survey（或finish）、quota允许、连续report未超限、Jain最坏损失小于正确奖励且墙钟余量足够时执行。

### 单调性及Jain上界

`WeatherTruth.band_quality` 不读instrument_efficiency或fault repair；它只积分 transparency、sky、seeing、lunar与airmass。`report_fault`只改fault_repairs并结算奖惩，`score_target_exposure`才把修复后的efficiency乘进去。因此对同一已冻结曝光，修复不会改变actual program band、倍率、命中、时长或observe rank；每目标factor与score非减。required和REQ非减，旧prefix账本不变。Jain可能有负边际，必须另算。

公开score与声明program给出raw factor下界 `max(0,score−0.500001e−6)/(weight×max(M_declared,mismatch))` 和上界 `min(1,(score+0.500001e−6)/(weight×min(M_declared,mismatch)))`。对已公开loss窗口撤销相应rank，得到每个RA band完成比例区间 `l≤r≤u`。最终未有完成证书的assigned targets最多增加比例向量δ。令K为band数、U为uniformity权重、`q_min=Σl²`、`s_max=Σ(u+δ)`，由

`dPenalty/dr_k = 2U·s·(s r_k−q)/(K q²)`

可得沿非负增量路径的保守损失界

`H ≤ Σ_k 2U s_max² (u_k+δ_k) δ_k/(K q_min²)`。

若q_min为0，observe gate拒绝。wait/finish的δ为0，H=0。只有 `H≤correct_reward` 且尚有免费误报额度时才有条件弱支配；这不是对新增曝光、重规划或墙钟耗尽的无条件保证。

### 读取truth之前固定的实际点

自然控制L1/L2/L4末动作分别为19/16/2秒wait，其已有正确report会使末次report大概率false，但仍可免费。L3末动作是2026-12-22 07:59:58 UTC、rank992、902秒observe，直接到公开survey_end，13个assignments，之前没有report。先用公共字段计算得到L3 `H≤0.7021997616960498`，因此若correct，净增至少99.29780023830395；若false且保留原末动作，分差0。

该单一L3点、一次report、原末动作和触发规则在 `results/cold_policy_breakthrough_20261004/PRE_TRUTH_PLAN.md` 固定并记录SHA256后才访问truth。root随后授权只在evaluator读取完全公开local-card L3 truth；actor选择、日期和目标未据truth调整。没有读取bulk/pair_audit/terminal_target_labels，也没有启动全季或GPU。

### 实际官方末动作结算

官方scorer复算原末曝光，13个hit及六位CSV score/factor全部吻合（最大score误差≤0.500001e−6）。新增report实际correct，直接奖励100；再发同一原动作，所有actual program bands与倍率完全相同。

| 分项 | 末动作替换的变化 |
|---|---:|
| 科学best总分 | +4.375264122786 |
| required罚分 | 0 |
| Jain项 | +0.028629116623 |
| report结算 | +100 |
| 请求奖励 | 0 |
| 净终局账本变化 | **+104.403893239409** |

原完整自然控制报告为6004.504542。使用已有六位CSV前缀账本恢复的baseline为6004.504561696，差1.97e−5；条件替换后的估计完整账本为6108.908435239。**这不是新策略完整赛季分数**，因为仅重算最后动作、没有从初始化运行协议。

另用原官方runner函数的独立内存副本恢复同一末状态，只替换初始化observe_index=992、loss_triggered=True（原公开loss已处理）、survey_start及已有prefix ledger；report/observe/结算代码不改，磁盘官方源码不改。control仅执行原末observe，candidate执行report+原末observe，两份官方末状态packet分别为1/2个decision，report前后now和rank完全相同，账本净差 **104.403893**。no-fault对照的免费误报奖惩为0。恢复方式与全部源码hash在 `official_runner_packet_check.json` 中，机械失败也保留。

### 最值得进行的下一项实验

完成一个通用、默认可关闭的terminal wrapper后，先从初始化完整重放同源READY的L3，并验证关闭时全部原动作逐字重现；开启时除最后插入的一次report与其结果外，原observe/wait时刻、rank、pointing、program、assignments全部相同，官方完整终分应提高约104.403893。随后四卡同预算确认false分支与墙钟影响，才考虑未见卡部署。这里没有理由进行早期report扫时刻或扩大搜索次数；价值来自终末边界及冻结后续动作。

本轮仅获得真实公开L3的单末动作正证据。通用触发率、完整协议额外处理时间、多个故障配置和正式未知卡收益仍待root决定的完整回放。

## 可执行候选准备

经root授权，通用wrapper已写在自有结果目录 `terminal_report_agent.py`，默认关闭，可由 `TERMINAL_REPORT_ENABLE=1` 开启。它复用现有native READY，不改生产或student源码；terminal判断来自本次initialize的日历与survey_end，quota和连续report数来自实际已发送动作与公开结果，完成证书仅来自公开score及resync窗口。末动作冻结后，次轮直接回发，原actor pending/C/E均不更新。

16项合成守卫与完整JSONL检查通过，包含关闭分支行动/调用数一致、报告反馈不会重置信念、跨夜/日间拒绝、Jain无证拒绝、quota/cap/wallclock、resync、rank或now异常终止、只插入一次以及非硬编码日期。初版仅有合成入口检查，尚未从真实公开initialize运行native。

Root首次完整尝试随后在0.399秒initialize失败，decision为0：初版错误地把targets当成list，实际官方契约为columns/rows的dict。旧源码、旧hash/锁与旧22文件包全部封存为FAILED_IMPLEMENTATION；原失败目录保持独立。模型/触发参数和pre-truth计划均未改，仅修复catalog字段索引；serve与原native agent.main一致，无需增加ACK。

修复后用固定L3公开initialize（8,700行正式目录）及既有natural-control前三行public_history作最小集成：READY、enabled0、enabled1三个实际入口各处理三次decision和前两次原公开反馈，JSONL响应逐字相同，并全部同原捕获动作。守卫正确读取rank0/1的14/13个hit；自定义完整summary仍符合protocol。该局部检查使用Darwin/NumPy2.0.2，公开history中省略的其余snapshot字段从公开消息/六位score及官方契约恢复，wallclock三分支同设900秒；它不是新环境反馈、Linux全季parity或新score证据。20个原READY文件仍逐字未改，当前wrapper/package/harness已重新锁源，root将另开新目录执行intervention。
