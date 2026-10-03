# 求解器的时间预算、确定性与固定工作量方案

## 已有路线实际上如何停止

源码与离线证据位于 `audit.json`；审计脚本是 `research/search_budget_determinism_audit.py`。没有修改production、ZIP或Git index，没有读取truth、创建官方engine或重新评测。

| 层 | 源码 | 时间对算法的影响 |
|---|---|---|
| stable Policy | `policy.py:357–363` | 用snapshot.remaining与经验2200次决策预测缩小planning_budget。它不直接减少anchor或phase数量。 |
| 基础 SpatialPlanner | `spatial_candidates.py:345,358,366` | anchor/fiber循环与两轮refinement中按perf_counter截止；不同机器可访问不同候选。 |
| 当前冻结 CPU Phase | `cpu_phase_candidates.py:180–183` | config的fixed_workload=true把上述budget设为1e9秒，覆盖Policy缩小的budget；Phase自身按候选数量停止，exact最多16。 |
| REQ science price | `request_deadline_common.py:50,64` | price与fixed_value budget为10000秒，完成固定2-anchor family。 |
| REQ pool与DP | `request_deadline_common.py:371` | 新建pool前，如果snapshot.remaining<30则跳过；否则整个pool一次建完，没有内部clock early stop。mask DP也没有时间截止。 |
| Distributed baseline | `request_remote_planner.py:64–67` | 若remote可用，当前choose已耗时间、剩余time、预算模型决定是否remote；health失败的四卡均CPU0remote。 |
| GPU Phase | `gpu_phase_candidates.py:94` | GPU排序后的exact refinement仍有3秒emergency，不是全部工作都固定数量。当前完整线上四卡没有走这里。 |
| 官方执行器 | `v4_workflow.py:253–271` | deadline前请求、response返回后再次检查；deadline后in-flight response不commit。900秒可把同一算法的相同轨迹截在不同位置。 |

**当前固定CPU路线的局部候选搜索并非通常的计时early exit。** 在900秒全局门限内完成的响应，内部耗时不可能达到10000或1e9秒。因此在同一完整输入状态、同一浮点环境下，正常CPU choose访问同一个有限候选集合。不能把所有分数不一致一概归因于每次局部搜索计时不同。

原始stable SpatialPlanner若单独使用常规0.22秒budget，确实会发生这种差异。这与当前fixed CPU Phase必须分开陈述。

## 离线假时钟验证

从冻结Phase ZIP读取原config，确认两个planner源码SHA与本地一致。对公开α、δ第一时刻、相同zero ledger与env，分别将perf_counter每次读取推进0秒或1秒。只在隔离脚本的choose期间替换时钟，输入和数学计算不变。

- 基础SpatialPlanner：两个时钟下实际候选数不同，α与δ的最终动作也不同。
- 当前fixed CPU Phase：α、δ两种时钟的基础候选数量、Phase候选数量、16次exact以及最终动作hash完全相同。

这是两个真实公开状态上的分支门检，不是对所有浮点平台的全称证明。一般论证来自上面的10000/1e9大于官方900秒门限。

## 同source和publicdata仍不足以定义同一道输入

必须分清以下层次：

1. 六个public文件相同，不等于天气、fault、REQ、offset、invalidation等不可见产品相同。scenario YAML hash也不能替代全部产品hash。当前审计不读取这些产品。
2. 完整snapshot还包含wallclock.remaining、当前已公布消息、hits、report结果、resync与已有ledger/calibration/terrain后验。source与catalog相同但snapshot/history不相同，算法选择可以不同。
3. 即便完整数学输入相同，Python/NumPy/BLAS版本、libm、计算顺序也可能使浮点值跨过ceil、glass seam、argmax或比较阈值。已有lexsort二级序号与明确tie规则能减少不稳定性，但不是跨平台逐位保证。set成员仅用于membership的地方不会导致遍历次序变化；不能仅看到set就认定随机。
4. 同一完整输入序列和相同浮点实现下，当前fixed CPU选择可以确定；900秒内收到并commit的前缀长度仍取决于机器速度、网络初始化、engine/I/O、调度。
5. 一旦动作不同，观测覆盖、score ledger、E估计、报告/repair、观察排名触发的resync和后续输入都可改变。完整分数的差异不等于某一步纯数值差异。

## 历史日志能够证明什么

脚本读取已下载的8个Phase/Request正式公开输出，记录package identity、终止原因、accounted/agent wallclock、actions和decision数量、最后simulation时间以及finish summary是否存在。

- Phase四卡均survey_complete；Request α、β为global_wallclock_expired且ignored_in_flight_response=true，finish summary缺失。这足以证明它们的900秒终止及最后response未提交。
- γ、δ可直接读取baseline/REQ build/DP计时。α、β不能由最后分数倒推出REQ/terrain的各自耗时。
- 这两批**package SHA不同**，路线和terrain/request行为不同；它们不是“同源码仅换机器”的受控对照。
- actions.jsonl没有完整decision_request、wallclock.remaining或每步候选数量；decisions.csv也没有这些列。无法从这些档案定位第一处“相同完整状态但时间门限不同”或证明全程候选一致。
- action输出可能触发多条engine decision/wait记录，因此actions行数、decision_requests与committed decision rows不能直接视为同一种计数。
- 不能声称两个survey_complete但不同source/环境的结果差异已经被clock解释。正确的后续证据是完整有序protocol trace，以及每个search阶段输入/候选/输出hash。

## 用操作预算定义一个可重复算法

当前CPU Phase已有固定工作量。继续研究应把**全季**必需与可选工作预算统一，而非只把0.22秒换成另一个数字。

### 1. 定义稳定的计算原子与工作量

记录计数向量 `w=(G,V,H,F,M)`：

- G：实际计算的pointing×target geometry对；
- V：duration×program×valid target估值项；
- H：catalog×实际积分中点，public/terrain可分别计；
- F：fiber内selection数量；
- M：mask DAG转移数量。

相同输入下计数由算法决定，不依赖perf_counter。记录完整原子任务序号、冻结env/ledger version与target order。浮点tie明确用原catalog index、candidate index二级排序，避免“候选先完成谁先赢”。

可推导的当前局部上限：基础最多24 anchor×16 fiber+16 refinement=400次exact，CPU Phase额外16次；每次exact exposure断点最多72、program3、target pool≤N。Phase每轴事件数≤4b+2，b≤24，四seed候选点粗上限 `4×98²=38416`，排名pool≤64、duration≤16。这些是工作量上限，不是900秒运行保证。

REQ start数量由公开calendar、deadline、step确定。每start最多8 anchor，最终不同fixed duration≤8；science price最多9×48次exact。anchor duration校正最多4轮；每anchor需16fiber×2prefer×3program。这给出构建工作量估计，mask DP为 `O((C+E)2^m),m≤8`，不足以解释数百秒的构建瓶颈。

### 2. 全季预算与计算调度

把必须完成的便宜baseline与可选Phase/REQ重建作为任务。任务只能在数学原子边界checkpoint，完成后发布完整候选；REQ列只在对应完整same-duration baseline price计算完成后发布，避免部分price family改变机会成本含义。

由标准2CPU环境标定非负成本系数 `c`，预测时间为 `c·w`；以多个实测卡和p95/p99误差形成保守经验上界，预留初始化、engine/I/O、finish开销。它是工程估计，不是WCET证明。必须记录系数/硬件版本和预测误差，不能把GPU kernel时间当整段服务时间。

全局可选工作预算可以写为：`B_optional = B_total - B_mandatory_remaining - B_reserve`。任务价值可用已知科学增益/REQ reward上限或当前incumbent的可改善上限，按价值/工作量安排，并在job DAG上处理依赖。已完成候选始终保留，额外工作只以原目标更优时更新incumbent；停止点是固定完成任务数/工作单位。

这里的2200次剩余decision预测只是经验数。不能把它当数学上界：report不推进simulation time，until_utc wait也可能短于最短exposure。真正的最坏决策数需要对非推进report、短wait、反馈重建分别证明。若这个上界非常宽，仍需实际runtime reserve模型。

### 3. 可重复与900秒安全的边界

不读取clock、只固定操作数，不能在任意慢或被暂停的CPU上保证900秒：任意一个非零任务都可被调度延迟超过deadline。2CPU约束本身不提供每操作耗时上界。

因此应保留外层hard-clock安全门，放在有界计算chunk的边界。固定操作预算决定正常搜索轨迹；clock只用于停止启动新可选chunk和交还已完成incumbent。chunk需要测量可用平台上的最坏耗时与reserve。相比现在“remaining≥30便一次建完全窗口”的REQ逻辑，这能避免长build耗尽最后时间，但此处尚未实现或评测。

若clock安全门在两台机器触发不同，输出仍可能不同；应明确日志标记 `fixed-work exhaustion` 与 `clock emergency`。目标是正常运行具有可复现的数学工作量，同时在机器波动时保护整季完成，不能声称两者在任意硬件下同时绝对成立。

## 最小后续日志要求

每次decision记录：完整protocol输入hash、ledger/terrain/calibration版本、snapshot remaining、每阶段工作计数、candidate family hash、选中动作hash、累计work、是否clock emergency、cache命中与每chunk耗时。保存stderr或独立artifact，但不增加产品内流程或备注。只在需要受控对照时比较同版本/同完整输入，才能区分source变化、数学反馈、数值平台和runtime截断。
