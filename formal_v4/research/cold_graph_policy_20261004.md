# 冷启动图算法研究（2026-10-04）

## 独立初稿：只读官方模型后形成，尚未查重

本段在阅读 `ALGORITHM_PORTFOLIO_ZH.md` 之前写入。输入只来自官方 `v4_runner.py`、`v4_scorer.py`、`v4_fiber_map.py`、participant guide 和 L1–L4 / practice cards 的公开配置、目录、夜历、公告/预报样例；未读旧策略、旧推导、teacher 标签。

### 真实决策与完整目标

合法动作是连续模拟时间上的 observe / wait / report / finish。observe 可改变起点（由前序动作决定）、alt/az 中心、整数曝光时长 60–3600 秒、16 个 fiber 的 target 指派以及全曝光共享 program。没有 slew 或独立曝光开销。命中只在曝光开始判定，中心随后恒星跟踪；最低高度 30 度须整段满足。gap=0；已知实际中心时每个 target 只属于一个格，因此单次指派是 16 个独立的容量 1 选择，不是一般可达二分匹配。

每次命中产生 `(g,c)`，`g=min(f*T*Q/450,1)`，`c=w*g*m`，m 属于 1 / 1.06 / 1.12 / 1.20。Q 按天气、方向事件、仪器效率、月亮、airmass 积分；program 档位按另一积分 B 逐 target 判定，排除仪器效率和方向事件，故同曝光可有不同档位。目标科学分是有效 c 的最大值，完成状态是有效 g 的最大值，两者可来自不同曝光。

完整结算为 `sum_i max c_i - 50*required_missing - 200*(1-Jain(RA-band completed fractions)) + sum completed-request rewards + report settlement`（常数应从本卡读取）。请求须完整落在发布时间/截止窗口内，至少 minimum_completed 个不同 target 的单次 g 达标；不足曝光不累积。一个曝光可以推进重叠请求。正确 report 当前配置 +100 且修复故障；误报每次正确报告后前 2 次免费，之后 -150。report 不推进模拟时间但耗 wall clock。数据丢失按 observe 序号撤销，时间不退款，科学/完成/请求都重新结算。

L1–L4 分别 7800/8600/8700/8800 target、390/430/435/440 required；practice alpha/beta/gamma/delta 为 10000/9600/9900/9400 target，公开配置一致（delta required 6%）。每卡 wall clock 900 秒；公开消息不给未来天气数值、精确事件边界、未来请求或隐藏指向偏差。

### 图路线 A：固定短期曝光序列中的“科学、门槛双证书”分配

普通二分匹配把每个 target 容量设为 1，边权写成当前 science gain + required threshold reward。但官方两个 max 解耦：一条 science 最大边未必是 g 最大边。一个 target 可合法占用两个曝光的格，分别保留科学证书和完成证书。只考虑普通科学/required/uniformity 的确定性固定曝光序列，可以将任意分配压缩为每 target 至多两个有用指派（max-c 证书，以及若 max-c 未达门槛时另一条达门槛证书）；只有科学 max 或只有门槛时可以压缩为一个。

可检验方案：短 horizon 固定若干 `(start,pointing,duration,program)`，构造机会顶点 o=(exposure,fiber)，target 为另一侧。对普通状态枚举 target 的空集、每个单边、science 边 + threshold 边 bundle；目标函数用真实 max-c 与完成状态，机会容量 1。该组合问题不是普通线性匹配；可用 component 分解后的 exact branch-and-bound / 小型 0–1 MILP，或从容量 1 matching 起做交替路径、双边 bundle 的 augmenting moves。合法改变只涉及当前与未来 fiber 指派；后续把最优首动作执行，反馈后重建图。若边冲突图无跨 target 连接则逐 component 精确求解。

该模型还可推广多请求证书：每 target 仅需保留 max-c 边和每个互不包含请求窗口的达标边；嵌套同门槛窗口由最小窗口的达标证书覆盖。但不能假设全局最多两个边：重叠请求窗口可能不共享合法 exposure。

预期遗漏：容量 1 target 把两个 max 错合并，或由 science-best factor 推断 required/uniformity 状态；以上会丢合法收益。首先用官方 scorer 造“较高 science 但 g<0.5、较低 science 但 g>=0.5”两曝光，再比较容量 1 matching 与双证书合法分配。

### 图路线 B：请求兑现的 Hall 可行性与联合覆盖

请求是至少 k 个不同 target 的整块奖励，不应永远均分成单 target 线性 bonus。短 horizon 的机会→target 图可给出某请求达门槛的 matching cardinality；Hall 缺额提供不可兑现证据。对多个重叠请求，将 target→request incidence 加入，完成同一 target 的一次 exposure 可同时覆盖多请求。可枚举小规模 request 子集，求最小机会成本的目标集合与分配，按真实请求奖励选首动作；已有不可兑现请求的线性 bonus 应归零。

请求集合若不相交且每 target 只有一次有效证书，matching 加 request quota 可写成标准 min-cost flow：source→机会 cap1→target cap1→所属 request（或自由 sink）→sink，下界为 request 所需完成数。任意交叠不能简单复制 target：复制会重复使用同一机会。对一般 incidence 用 exact small component / MILP，不能宣称普通 flow 精确。

预期遗漏：逐 target bonus 会追逐截止前 Hall deficit>0 的请求、或把共享 target 多次奖励但没有共同 window 证书。微实验需选择同 cell 竞争或 window 不相交的目标，保证是官方允许但线性 bonus 无法表示的对象。

### 图路线 C：曝光序列本身必须在时间 DAG 中合法

单纯机会匹配会在互相重叠的 exposures 上同时花容量，产生不可执行上界。候选 observe/wait 是时间顶点间的有向弧；选择一条 start→horizon_end 路径后才产生 fiber 机会。短 horizon 对候选曝光长度/pointing/program 做有限枚举或 label-setting，保留真实 target max-c/threshold 状态；边权依赖过去完成状态，不能直接求一次普通 longest path。可用外层 beam / Lagrangian prices + 内层分配，最终必须输出一条时间路径、通过 normalize_action/official scorer 验证；而非只计算松弛季节上界。

证据需求：A/B 若已被旧研究覆盖，改做具体反例或新对象，而非重复宣称。只做合成微实验或公开输入的几何/可行性计算，不发起完整季节、GPU、SSH、平台提交，不改生产包。

## 查重后的结果：联合请求 gate + 完成列签名商

### 已有部分与换对象的理由

`ALGORITHM_PORTFOLIO_ZH.md`、`objective_graph_DESIGN_ZH.md` 已明确记录科学 max 与 raw-factor 证书分离、quota gate、时间 DAG、失效 witness 和跨 fiber 竞争；独立初稿 A/C 不再视为新机制，也没有重复做相同微实验。进一步读 `request_deadline_common.py`、`request_mask_dp.py` 和 `REQUEST_DEADLINE_MODEL_ZH.md` 后确认，单请求完整截止窗口、8-bit OR mask、整块奖励和科学机会成本均已有实现。

新对象是多个**已发布**请求的联合 gate：现有 `RequestDeadlineMixin.choose` 第357行逐 request 求最小成本，第378行分别比较每条 reward 与该成本，第387行从分别接受的方案中取最早者。若同一合法计划完成两条请求，科学机会成本只发生一次；可能每条都不足以独自支付该成本，但二者奖励之和足够。逐请求接受/拒绝会漏掉该计划。这是具体目标模型差异，不是换名的单请求配额匹配。

官方依据如下：

- `v4_scorer.py:462` 的 `request_factors` 为给定窗口遍历所有 valid ledger entries，只检查曝光完整位于窗口；它不把 entry 消耗或划归某个请求。
- `v4_scorer.py:477` 分别计算每个 request 的不同 target 达标数。
- `v4_scorer.py:499` 对同一个 ledger 为全部 requests 求 status，再相加 rewards。因此一个 valid target witness 可以同时给多个包含它的请求计数。
- participant guide 的请求说明明确允许同一曝光推进重叠请求；`v4_config_check.py:178` 验证请求唯一 ID、窗口在 survey 内、target 唯一、quota/threshold/reward 等，没有禁止不同请求窗口交叠或成员共享。

普通 target→request 容量1分配是错误模型；它会把官方可共享 witness 人为独占。反过来，全局 target-completed mask 也不充分：不同 request 的时间窗可能使同一 target 有不同完成状态。

### 可执行算法

候选仍是完整 observe 列 `c=(start,end,pointing,program,assignments)`；每列在同一时间 DAG 中占用整台 telescope 的区间，不能独立选各 fiber 的列。按已公开 active requests 的 union 构列并去重**完整动作**；对每列重新算所有请求的窗口和 raw-factor eligibility，而不是沿用原来某个 request 的局部 mask。每列的科学机会成本只计一次。

基础状态是 occurrence `(request_id,target_id)` 的 bit，而非全局 target bit。列 c 设置 `(q,i)` 当且仅当 i 是该完整动作实际指派的 target、单次 raw factor 达 q 的门槛，且 `[start_c,end_c]` 完整位于 q 的窗口。初始 bit 从 q 的 `completed_target_ids` 获得。OR 确保同一 target 对同一请求只计一次，也允许同一次曝光设置多个请求的 occurrence。终点目标为：

`sum_q reward_q * I(completed distinct target count_q >= quorum_q) - sum_chosen_columns cost_c`。

已完成 gate 的 reward 是常数；部署时应排除已达 quota 的 request，或在计算净增时减去初始 reward。按事件时间等待或选择 observe 列，在 sparse DAG 中保留每个 mask 的最低累计成本；所有 request reward 都在终点一次求和。此处成本必须固定、有限、非负。它精确优化有限列上的联合请求净值，不精确优化完整原题 science/Jain/belief。

执行合法变化是选择联合计划的第一条完整 observe 动作，必要时 wait 到其起点。首列强制 target 应取联合完成集合；不能调用只强制某条请求 target 的旧 decoder。发出前重验命中、全段高度、raw 阈值、夜末、所有请求窗口；反馈/resync/质量变化后重建，再继续滚动。只有当前已发布请求参与，未来未发布请求没有先知值。

### 严格有限列状态商

设当前未完成 occurrence 集合为 O，定义其未来完成列签名：

`sig(o) = {c : column c sets occurrence o}`。

先把初始已完成 occurrence 移入每条请求的固定计数；空签名 occurrence 永远不被本池完成，保留其未完成事实但不占动态 bit。对余下 occurrence 按相同签名分组为 atom a。一 atom 可能含同一 target 的多个 request occurrence，也可能含总是在相同列共同完成的不同 targets。其权重 `n[q,a]` 是该 atom 对请求 q 含有的不同 target 数。请求 count 为 `initial_count[q] + sum_a n[q,a]*z[a]`。

证明：对任意本池合法路径 P，尚未完成 o 的最终值是 `I(P ∩ sig(o) 非空)`。相同签名使这些 bit 在每一条路径上完全相同，故以一个 z[a] 代替后，逐请求 count、gate reward、每列 cost 和时间路径均原样保留。反过来，atom 状态可确定本池路径上每个 occurrence 的状态。因此未压缩与压缩 DP 的最优值及动作选择一致。不同窗口造成不同完成列签名时不能合并；未来反馈改列或新请求加入后必须重建商。

这减少动态 bit 坐标和**密集数组预分配容量**；它不会自然减少已可达 sparse mask 的数量，因为可达状态在商前后对应。实验确实观察到 sparse reachable 数量不变，不能声称搜索树或实测 runtime 加速。

代码只在 `results/cold_graph_policy_20261004/joint_occurrence_dp.py`；未修改任何研究旧实现、bulk 锁源或生产包。

## 官方合成微实验与否证

### 六列请求计划：与现有冻结成本抽象对应的主证据

合成卡使用正式 fiber/score 常数和900秒slot；声明其前360秒为请求域，两支之后共同wait540秒，无 stress、故障或方向事件。两条同时公开的请求均8选6、reward100；共享6个 target，另各有两个零 flux 的候补。六个共享 target 分布在六个不同 field，每个请求需六条60秒曝光。每条 R_i 列只有一个 requested target，官方 factor=.55、science=.198。

每个相同60秒区间有一条 B_i 控制曝光，16个独立高 flux / weight1.7 target 都饱和且 program DARK，science32.64。每一列冻结科学 regret 是 `32.64-.198=32.442`，六列成本194.652。B_i 与 R_i 的 target IDs 全部互异；固定区间内只在这两个合法动作之间选择的2^6族中，science max 不会产生跨列重复，故该 regret 相加在此微域是实际科学成本。

| 项目 | 科学控制 | 联合六列 |
|---|---:|---:|
| sum_best_scores | 195.840 | 1.188 |
| observation_request_reward | 0 | 200 |
| required_penalty | 0 | 0 |
| uniformity_penalty | 0 | 0 |
| report_settlement | 0 | 0 |
| 官方 total | 195.840 | 201.188 |

两条分开求解时，各自100不足以支付194.652，都返回空计划。联合 DP 选择 R_0,…,R_5，官方分数相对控制 **+5.348**。当前合法首动作从16个 B_0 目标的 field 改为 R_0 的 field、60秒/一根fiber/program DARK；不是单纯计算上界。

完整官方 `run_scenario` 两支均 `survey_complete`，各六个 observe；共同 R witness 对两条请求分别完成6/8并奖励100。所有指派经过官方几何、全段最低高度、program、Q积分和终局完整结算。目录只有一个含目标的 RA band，所以 Jain=1，均匀度罚分为0；required/report 项在该声明合成域为空，stress关闭。这不是对这些真实项的近似。

raw occurrence 共16，其中4个在本池不可达；12个活 occurrence 按共享列签名压为6个 atom，密集状态容量从65536（剔除空签名后4096）降至64。压缩与未压缩 DP 均达到5.348，sparse时间×mask可达状态均127。

这与现有冻结“同 duration 的 science regret 求和”抽象一致，但没有实例化强 native 的候选生成器或运行 `RequestDeadlineMixin`；它不证明该现有程序会在这张合成卡产生完全相同候选/价格，更不证明胜过 native。

### 初始900秒二臂实验：保留但限定解释

最早官方例子让6个共享 target 在同一900秒曝光完成，科学为1.188、请求为200，总201.188；另一支15×60秒控制科学122.4，总122.4，差 **+78.788**。真实两臂 science 成本121.212，各100不足而合计200足够。

该数值只属于声明二臂域。900秒内控制允许多个曝光，而旧 `_SciencePricePlanner.fixed_value` 的同 duration B(t,d) 是**单个曝光**，故121.212不是该旧定价器的字面输出。没有把较大的+78.788当成现有单列实现已被战胜的证据；上述六列实验补齐了这层对象区别。

### 300组官方 ledger 与穷举交叉核验

随机对象含2–3条 request、交叠/不同窗口、共享 targets、重复 witness、部分初始已完成 target、2–9个互相可冲突的有限曝光列。对所有 nonoverlap schedule 穷举，用官方 `BestLedger` / `settle_observation_requests` 求 reward，再减去同一固定非负成本；与 occurrence DAG 原版及签名商版比较。

300组最优值差异均为0；143组动态 atom 数严格少于活 occurrence，实际 sparse reachable 状态减少0。此核验验证请求窗口/gate/OR/初始进度/时间冲突和商正确性；随机列没有官方 fiber 几何，也没有未来 loss、在线反馈或完整 science/Jain 价格。不能将其叫作完整季节最优证明。

额外官方窗口否证：同一 T 在第一个 `[0,100]` 请求中有60秒 g=.6 witness，第二请求为 `[100,200]`。官方只奖励100；window-aware occurrence DP也100，全局 T mask 错误会奖励200。该反例说明同 target 共享与时间窗状态都必须保留。

## 已有真实公开历史准入：没有联合触发点

只读四条已有强 native 控制的 `natural_control/L*/rank_0064/control/messages.jsonl`，只提取 `record_type=observation_request`。没有读取 `terminal_target_labels.json`、bulk archives、teacher 数据或实际卡 truth；没有重跑季节。源路径和 SHA256 在 `public_request_windows.json`，复现脚本为 `public_window_audit.py`。

| 卡 | 首请求窗口 UTC | 第二请求窗口 UTC | 交叠 | 共享 target |
|---|---|---|---|---:|
| L1 | 11-03 00:30 → 11-04 08:30 | 12-01 00:45 → 12-02 08:15 | 否 | 0 |
| L2 | 11-10 00:30 → 11-11 08:15 | 12-12 01:00 → 12-13 08:15 | 否 | 0 |
| L3 | 11-17 00:45 → 11-18 08:15 | 12-20 01:00 → 12-21 08:15 | 否 | 0 |
| L4 | 11-24 00:45 → 11-25 08:15 | 12-28 01:15 → 12-29 08:15 | 否 | 0 |

全部日期为2026年；每条均8选6、100分。两条请求相隔数周，根本不会同时处于 active_requests。按只有多条未完成 active 请求才启用联合分支的设计，四卡当前没有新首动作可准入。

## 局限、验证建议与停止结论

新结果是：正式契约允许的联合请求奖励必须联合兑现；现有逐请求接受机制会漏掉声明有限域中的合法正净值计划。窗口 occurrence + 完成列签名商是精确有限列求解器与严格坐标缩减。它不需要 GPU，不是全局松弛上界。

它仍使用固定合法列和冻结非负 science 成本。一般真实路径重复科学 target 时 max-only 会破坏成本相加；Jain 可有负边际；required 与 program/factor 双 max、report/belief 变化、observe rank 与未来 loss 也没有并入此 DP。真实应用必须保留完整主策略账本，并在反馈/损失后重建；不能称其对未知卡全局精确。没有证明公开卡请求模式会代表正式隐藏卡，也没有声称隐藏卡一定含重叠请求。

Hall 缺额最多证明**该有限候选池**不可达 quota；本研究没有覆盖全部连续合法曝光的资源嵌入，因此撤销把候选图不足称为全域“不可能”的表述。

**当前不值得启动 L1–L4 同预算完整验证**：四卡没有联合请求窗口，且稀疏状态数未降低；没有能改变该组 native 决策的公开准入点。可保留为隐藏卡契约兼容的实现构造：只有出现至少两条未完成已发布请求、可共同完成列、联合计划第一动作与控制不同，并且完整账本成本检查通过时，再发起相同2CPU/2GiB/900秒的真实replanning对照。现有源码/生产包未改，未发起全季、SSH、GPU或平台提交。

复现：

```
python3 -B formal_v4/results/cold_graph_policy_20261004/micro_experiment.py
python3 -B formal_v4/results/cold_graph_policy_20261004/public_window_audit.py
```

全部官方合成卡、冻结动作、decisions/observations/messages/score_report、随机摘要及源 hash 均位于 `results/cold_graph_policy_20261004/`。最终综合微实验耗时约0.2秒；没有以此小样本时间推算900秒部署开销。

### 最终源范围补正：共享 target 样例不来自已知正式生成器家族

结束前另核验 `cold_public_rng_20261004.md:105` 指出的官方公开源码 `runs/official_generator_e01939d0/challenge/v4_observation_requests.py`。第199行建立跨请求 `used`，第214行跳过已有成员，第220行将本条 chosen targets 全部加入 used（该固定源码commit见其他报告）。因此这个生成器的 request target 成员全局不重复；其函数输入和第2–7行说明也不读取未来天气。

本报告的两种共享6-target合成场景符合 runner/scorer/公开协议，但**该已知正式生成器家族不会生成它们**。不能把它们称为该生成器隐藏卡上的自然机制实测。多个请求也可以因同一完整 field 覆盖不同 target 而共享 telescope 成本，然而本轮没有对这种不同对象另扩实验；公开L1–L4无交叠窗口已足以停止实际对照。签名商的有限列正确性不依赖生成器；“值得隐藏卡真实验证”的准入仍须首先观察到公开当前状态上的实际联合窗口及不同首动作，不能只凭一般协议允许来启动季节。
