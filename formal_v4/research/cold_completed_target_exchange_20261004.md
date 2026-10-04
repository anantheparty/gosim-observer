# 固定曝光中的 completed/science 与 Jain 计数交换

2026-10-04。已收束；没有部署包、整季新作业、GPU训练、Rhodes1任务或线上提交。

## 结论

固定曝光内，Jain 真实变化可以按各 RA 带的新增完成数求精确最优 assignment。小计数 DP 已实际实现，1,000 个有限实例与独立全部枚举误差 0，与官方 uniformity 结算误差 0；87 个实例严格优于一阶 Jain 选择，913 个同值。

真实最强 `RequestCache + Terrain + faultv1 + exact arithmetic` 来源上的公开微域结果为负：L1/L2 各第8/18/28夜，六个公共重建状态 × 三档冻结质量，共18题，精确 DP 与匹配的一阶选择 **18/18 同值**。名义质量下六个新 strong 动作的 assignments 全部原样。无符合预声明稳定变化条件的候选，停止此机制，不扩大点、不救参、不跑整季。

这只否定这些固定 field/duration/program 的 completed/Jain 交换实例。没有否定晚季科学升级、跨夜排程、普通 NN 或完整题目的可能提升。

## 官方目标与公共信息

先读 `runs/official_generator_e01939d0/challenge/` 的 runner、scorer、workflow、fiber_map 与 catalog/weather generator，再完整查 `ALGORITHM_PORTFOLIO_ZH.md`。源 SHA 在 `INPUT_LOCK.json`。

对有效曝光 e 的命中目标 i，官方 contribution 为 `c_ie = weight_i * min(flux_i * duration_e * q_ie / (f0*t0), 1) * program_multiplier_ie`。科学分是每个目标的历史最高 `c_ie` 之和。raw factor 的历史最高值独立于 science best，决定 required 与 Jain 的 0.5 完成阈值；REQ 还需要完整曝光位于请求窗口内。完整终值为 science、required penalty、Jain penalty、REQ奖励与报告结算之和。

纤维命中在曝光起点一次分类；共同曝光占据真实时间，各 fiber 至多一目标，各目标至多一 fiber。Moon、airmass 和事件方向沿曝光积分。未知 offset、天气、fault 和未来公告不因公共目录而变成已知。回溯 data loss 由 observe rank 决定，因而改变动作数也会改变旧数据存活。

initialize 公开目录、站点、仪器、评分和夜历；snapshot 公开已到时的 bulletin/forecast、REQ、resync、报告结果与上一曝光 `target_id, score`。它不公开真实 raw factor、quality、命中 fiber 或未来天气。本实验只用 L1/L2 的 public 输入和历史反馈的 target_id/score 投影，没有访问 L4 或 L4 sealed 数据，没有 fault 日期训练/触发。

## 去重与这次子题

既有 quality-window 已研究独立 target best-score MDP 和 fiber 秒价格；共同曝光 MILP 已研究真实时间 path 与 science-only target-layer matching；增广指派已研究跨曝光 science witness；其结果不被重跑。本实验研究另一个明确的耦合：**同一个固定曝光内，Jain 是新增完成的 RA 计数函数，不能一般写成逐目标加性奖励。**

它没有重新计算固定列 LP 上界，也没有重新跑 beam、GA、共同曝光 MILP 或 debias。它保留完整 catalog 几何内层和 RequestCache/Terrain/REQ 外层，检验在无 active REQ 的当前强动作上，是否仅需改变 assignments 即能修复 completed/new-target 选择。

## 精确有限化简

固定曝光的起点、duration、pointing、program、offset、贡献 `c_i` 和 raw 完成状态。设历史 science best 为 `b_i`，每目标 science 增量 `a_i=max(0,c_i-b_i)`，required 阈值跨越的奖励为 `p_i`。已完成目标仍可有正的 `a_i`，只是它不再增加 Jain 完成数。

第 k 带总数为 `N_k`，历史已完成数为 `C_k`，本曝光新增数为 `z_k`。去掉空带后，

`J(C) = (sum_k C_k/N_k)^2 / (K * sum_k (C_k/N_k)^2)`；全零时 J=0。

固定曝光 assignment 子题的真实目标为

`max sum_i (a_i+p_i) x_i + U*[J(C+z)-J(C)]`，

每 fiber 的 `sum_i x_i <= 1`，每 target 只属于一个起点分类后的 fiber，`z_k=sum_i x_i * 1{i新完成且在k带}`。

同一 fiber 内，同一“无新完成”或“在 k 带新增一完成”签名的目标，只需保留 `(a_i+p_i)` 最大的一个：替换保持 fiber、所有 z、Jain 项不变，science/required 项不降。这是固定子题内的支配，不是对任意未来排程的支配。丢弃低贡献目标可能丢掉其未来信息或备份 witness，故不能跨完整问题使用。

按 fiber 依次做 DP，状态是活跃 RA 带的新增完成数向量。每次选择 idle 或该 fiber 一个签名代表，更新计数与加性 gain；末尾才计算精确 `U ΔJ` 并选最大终值。归纳可证明每个计数状态保存其最大加性 gain；再枚举所有末状态给出固定子题最优。两个活跃带时最多 `(16+1)^2=289` 个矩形状态，实际总新增数≤16更少。本 prototype 对超过两个新完成带明确不准入，synthetic checker 可以解除这一运行限制做有限全枚举。

完整题目仍涉及连续 field/start/duration、共同时间约束、max-score层覆盖、REQ gate、隐藏天气 belief、反馈、rank/loss；这个小 DP 没有将 NP 全题化为多项式，也没有原题最优证书。

## 严格反例

两带均10目标、历史完成数均5、U=200。此处 Jain=1，一阶梯度两带都为0。

一个 fiber 上，“已完成目标 science 升级”gain=.05，与“新完成 band0 目标”science gain=.06 竞争。加性梯度选新目标，完整有限目标值为 −1.5793442623；精确选择旧目标得到 .05，差 **+1.6293442623**。这是完成带已均衡时，新完成目标真实 Jain 边际可以为负的反例。

两 fiber 上：第0 fiber 旧升级gain1/新band0gain1.2；第1 fiber 旧升级gain1/新band1gain.9。梯度独立选择新band0+旧升级，完整值 .5606557377；精确选择两个新目标使比例仍均衡，完整值2.1，差 **+1.5393442623**。它展示跨 fiber 的完成互补：单独新完成均有负 Jain 边际，一对平衡完成可以抵消该损失。

这些是已知 contribution/完成 flag 的合法有限结算构造，不是生成器真实卡的收益。在 `AUDIT_RESULT.json` 有全部数字；1,000随机例的每一个 exact/brute objective 检查均通过，四个更大反例保存在 `checks.json`。

## 公共实验与范围

控制 ZIP 是 `results/cold_sparse_science_runtime_20261004/observer_sparse_exact_fault_20261004.zip`，SHA `5b00e6a33cbacc167cdf9255531c5209b0ab36cab7c52ce13d395942e672cf29`。38个成员复制到自有 `strong_package/`，最终逐字等于 ZIP。没有改原27source、原参数、Terrain、报告、REQ deadline DP/cache 或精确算术。

公共历史来自已完成 `sparse_fault_actual_20261004/seasons/fault_fast/L1|L2/`。ingress 只保留 observation 的 `target_id, score` 以及其 observe index 作为时间归属，丢弃真实 factor、quality、prog_mult、fiber_id、valid、invalidated_by。失效只由公开 resync 处理。未来 feedback 和公告从不传给当前 state。历史报告的零模拟时间会产生同时间戳，必须按 report/action 顺序匹配，不能仅用 timestamp 提前送结果。

重建 Policy 的 pending、公开校准、Terrain、C/E 和 score ledger 后，重新调用当前强 planner 得到 incumbent。缺完整 wallclock 和历史内部 prediction，所以称 **公共重建状态**，不声称原历史逐动作 parity。试验的第一动作不用于继续喂旧反馈；采样器继续重建历史时安装的是原公开 action，绝不安装实验 action。它没有伪装成反事实闭环续局。

预声明夜索引7/17/27/37，各取该夜开始一小时后的首个 observe，排除 active REQ；局部卡不存在第38夜，因此两点记录 unavailable，未补点。六个有效状态共18个子题，质量缩放固定 .9/1/1.1；它们是冻结 conditional Q 灵敏度，未校准成概率。pointing、duration 和 program 固定为新强 incumbent，仅重新比较同 field 的全部可分类目标。

科学贡献采用原冻结起点 Q 模型。新完成 flags 使用原 duration_safety 的 robust factor；历史 completion 用公开 score 导出的 factor_lower。**它们不等于已知真实完成状态**，因此公共 DP 只对这个完成 surrogate 精确，不能称官方真实终值的精确优化。全目录存在189–378个公开完成歧义，局部有0–4个。本实验没有靠隐藏 true factor消除它们。

为隔离 Jain 曲率，除了原 weighted/urgency/progress-scale strong assignment，还独立比较同一 options/gain 的纯一阶 Jain selector。精确 DP 在18题都与后者同值。不同假设下相对原固定 nominal assignments 的局部差不能归因于曲率。

| 状态 | .9 / 1 / 1.1 对原固定assignment的有限值差 | 精确对matched-linear |
|---|---:|---:|
| L1 第8夜 | 0 / 0 / 0 | 全tie |
| L1 第18夜 | .044304200 / 0 / .020136721 | 全tie |
| L1 第28夜 | 0 / 0 / 0 | 全tie |
| L2 第8夜 | .128735997 / 0 / 0 | 全tie |
| L2 第18夜 | 0 / 0 / 0 | 全tie |
| L2 第28夜 | 0 / 0 / 0 | 全tie |

名义质量六次 assignments 全部不变；三档稳定同一非强 assignment 的 gate 0/6，三档严格曲率改善 gate 0/6。即使局部条件值非负，也没有终局 replan 标签或整季得分证据。

实际 active bands 为0–2，DP peak states 为1–107。248个最终 candidate assignments 和18个完整 action合同经官方 FiberGrid/全曝光 min-alt 检查通过，使用的是公开校准 estimate，未读真实 offset。最终 public 微实验总18.965秒（Mac unrestricted），每状态含一次完整强 choose约.081–.099秒；它不是Linux2CPU预算证明。全部原始 state/scale结果、tie与不可用状态保存在 `public_summary.json` 和各状态 JSON。

还在每个状态枚举“总新增≤16”的计数向量超集，单独量化 Jain 线性化误差，最大绝对值 .579383002。这个超集没有 time/field/science 目标，不是分数上界；实际 assignment选择依然全部tie。错误在数学上存在，并不代表当前物理备选足以利用。

## 工程失败与归档

三次失败完整保留：`FAILED_01_NIGHT_INDEX.log`（把不存在第38夜当有效index）、`FAILED_02_FACADE_DEEPCOPY.log`（原 RemotePlanner facade 的 __getattr__ 导致 deepcopy递归）、`FAILED_03_REPORT_SAME_TIME.log`（timestamp-only报告结果投递）。修正仅处理输入/生命周期，未改变状态选择或加点。

完整修正前一次成功运行的 classifier 对远处背向天空做 gnomonic投影产生 NaN cast warning，也保留在 `PRE_AUDIT_WITH_CLASSIFIER_WARNINGS.log`。最终用保守球冠先排掉背向天空后，所有有限数值和结论不变。原 package成员没有改；新增代码仅在自有结果目录。

`jain_assignment.py` 是可复用固定子题原型，`check_operator.py` 是独立枚举/官方结算门检，`public_states.py` 是公开反馈投影/重建，`run_public.py` 是预声明实验，`audit_public.py` 是官方几何/计数与ZIP字节审查。`FINAL_RECEIPT.json` 和 `ARTIFACT_MANIFEST.json` 保存源、输入、产物SHA。root指示本机制完整保留后收束；没有增点、参数扫描或整季准入。
