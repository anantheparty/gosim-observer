# 公开反馈下的并发分组进化：新机制、实际微跑与停止条件

2026-10-04 07:58 JST。先独立读正式 runner/scorer/fiber 与固定官方生成器，再读 portfolio 查重。只写本文件和 `results/cold_closed_loop_evolution_20261004/`；没有 SSH、GPU、整季、网上提交、READY/actor/固定教师学生修改。没有读取任何 L1–L4 truth、L3 教师标签或 sealed L4 标签。L1–L4 与 alpha–delta 的目录、日历、仪器和公开 score config 已检查，原型只使用 L1/L2 公开目录和日历。

## 当前判断

新机制是**进化当前未完成目标的并发等价关系**，而不是进化预排时刻或选择旧动作列。一个分组表示：“该组的活成员应由同一合法曝光同时覆盖，且占不同 fiber。”每次决策都从当前公开几何重建连续 pointing，执行一个动作，按实际公开 score/hit/request/resync 更新债务，再删除或重新分组残余成员。个体没有 exposure time、绝对日期、program、duration 或既成动作序列基因。

已实现小原型，并实际运行了 16 条 24 分钟人工天气微巡天，均用正式 `v4_runner.run_scenario` 执行。第一版 8 条全部 GA/单轨打平，已归档并判为分组语义不足；并发约束修正版 8 条取得很小且不稳定的差异。**本轮停止扩算，不推荐部署或现在开完整季节。**现有证据说明结构能够改变合法动作与反馈后的行为，尚不说明它能提高真实卡分数。

## 从正式题目得到的模型

公开历史记为 `h_t`：initialize 的目录/site/night calendar/评分，以及截至 `now_utc` 已发布的 bulletin、forecast、request、last_result、resync 和自己的动作历史。状态应包含自己的原始曝光账本、observe rank、各目标 best score、factor 可行区间、按请求时间窗区分的 witness、仪器/天气/方向事件/offset 的 belief。`running_total` 只有科学 max 累计，不能替代终局 ledger。

正式目标是条件随机控制：

`J(pi | h_t) = E[official_total(pi, latent_future) | h_t]`。

若采用风险目标，应预声明为 `mean(total) - lambda * CVaR_alpha(loss)`；没有证明这个 lambda 比零更好。输入完整未来 truth 的排程优化，只是静态条件 oracle，不能作为正式未知卡 actor。条件分布不等于单次 L1/L2 实际未来，官方生成器源码给的是分布结构，不能直接恢复当前 latent world。

正式源码的几个不可丢失的细节：

- fiber 命中只在曝光开始判一次；实际中心为命令加未知 offset，随后恒星跟踪。高度整段必须合格。16 个玻璃格、gap=0，合计视野 6.4 平方度；同格只能选一个目标。
- science 为各目标最大 surviving **score**，required/Jain 使用独立最大 **factor**。不同 witness 可以分别承担 science 和 completion，曝光不可累加。
- 公布 request 的 `k-of-n` 奖励只有达到完整 quota 才给；有效曝光必须从 issue 到 deadline 整段包含。先前观测不能自动完成新请求。
- band 按逐目标天气、airmass、Moon 的积分计算，不含 instrument efficiency 或方向乘子；同场目标可能属于不同 band。
- `last_result.hits` 返回 target_id/score，未给 fiber/factor。declared program 的 multiplier 只有 1 或该 program 的匹配乘数；不能直接把 `score / weight` 当 factor。
- data loss 按 observe rank 回滚原始记录，时间不退；任何改 duration/observe count 的策略都可能改变 loss 窗口，不能固定父代后缀或失效 rank。

固定官方生成器 e01939d0 支持这一信息结构：天气有夜/slot 相关的连续分量和开闭马尔可夫过程；天气事件、rocket、terrain、quake、fault、stress 和 request 使用独立命名流。bulletin 只发布 coarse kinds/directions；forecast 只发布覆盖期内的夜级类别/方向，fault 与 quake 不被 forecast。原型的人工常量 efficiency world 没有覆盖这些机制。

## 查重与转向

最初考虑任务承诺/放弃/恢复的条件语法。portfolio 和 `evolutionary_policy_REPORT_ZH.md` 已实现四谓词三算子的结构进化，所以停止这个想法。本机制的基因是运行时目标之间的并发关系，没有谓词树。

| 已有结构 | 本轮不同处 |
|---|---|
| 绝对时间排程 GA、夜块交叉和 truth fitness | 搜索反馈状态中的目标并发关系；每个虚拟后继也按自己的反馈更新，不重放固定 tape |
| 三种任务包的条件语法 | 不选择 native/REQ/required 叶算子；改组内谁必须共同占用不同 fiber |
| 固定强时序的跨曝光 assignment 流/增广路径 | 时长、field 和后续决策都重新构造；不保留固定曝光序列 |
| 全目标加权边界 sweep | 可以作为物理解码器；其几何最优或候选覆盖不能替代条件终局 fitness |

“闭环”和“使用终局 fitness”本身不是新发现。新增的、可直接执行的结构变量是**哪一些尚未完成的目标应同时获得一次 witness**。

## 可实施的完整机制

### 运行时结构与反馈更新

每个目标生成当前公开需求 token：剩余 science 增量、required 的 0.5 证书债务、已公布 request 的 window/threshold/quota 债务。同一目标在同一可用时间窗的多个债务可合并为带 tags 的 token；跨时间窗保留区分，不能无条件合并。目标 ID 仅用于当前运行时 join，不是跨卡学到的基因常量。

取至多 32 个活 token：先取当前已有请求和几何支持将消失的 required，再用公开剩余 science/附近 co-observability 补齐。精英个体 `P` 是这些 token 的 partition。分组上限 16，组成员的当前方位相距过大、无法在剩余连续夜段同时高于 altitude 时，标为不可解组；这个判定只用于构造，不作整题不可行证明。

按六位 score 舍入 `eps=0.5e-6`，一次非负 score `s`、weight `w`、declared 匹配乘数 `m` 给出：

`factor in [max(0,(s-eps)/(w*m)), min(1,(s+eps)/w)]`。

这是只用公开 score 的保守区间。raw ledger 按有效曝光独立保存这些区间，required 仅由下界>=0.5 作证书；request 的 `completed_target_ids` 是额外公开证据。resync 到来后按公开失效 action-index window 删除对应有效记录，重建 best/区间/请求成员残余，再让种群重新连接失去 witness 的 token。不能以 best-score 的 resync 列表恢复未知 raw factor。

一个组在反馈后可分裂：已证实 completion 的 token 去掉该 tag；剩余 science 还可保留；已过 deadline 的 request tag 删除；重新变得欠债的 token 重新插入。种群基因只保留仍活的成员，重新 canonicalize。实际执行一次动作后再求解；**从不把 rollouts 的未来 score 当真实状态**。

### 解码与进化

对每个当前组 `B`，用当前 RA/Dec→alt/az、fiber 网格和 offset belief 构造连续中心。可从目标对应 fiber 的逆中心、组质心、boundary sweep 或公开几何局部修正开始。候选不是从旧季节 pool 索引来的列；center 随时间、group 和 feedback 改变。

一个 decoded group action 只有当所有活成员在当前 nominal/指定 offset hypothesis 下落在**不同 fiber 的 glass**，且整段高度合格，才能代表该组。mandatory 成员先占对应 fiber，再填 opportunistic 目标。offset 有不确定性时使用 posterior hit probability 或 robust glass margin；未知 offset 不能被称为已精确求解。duration/program 仍应由同源强精算器给出，包含短曝光、夜末裁剪和 request deadline，不只使用原型三时长。

变异交换两个目标的组、拆一个目标、合并两个组。交叉复制父代中的完整组，再从另一个父代所有组删除这些成员，余下组保留；因此后代仍是合法 partition。精英和 diversity 用目标对的 co-membership bit vector，避免只按 group label 名称度量。所有 labels canonicalize，消除无意义的组名置换；不能据此删除不同目标身份的个体。

fitness 每个 genome 从**同一个实际公开历史**开始，使用共同随机数的 belief worlds。每个 world 的虚拟环境产生自己的公开 score/hit/new message；政策只消费这个反馈重新删除/修复残余、改变估计、重建 field。样本选择需与当前公告、forecast、score区间相容，并包含 closure、direction、fault 的合理未公告概率。不能用已知实际未来天气替代这些 world，也不能用父代未执行的实际未来 hit 构造后代。

先做 2–3 个当前夜段的 contingent rollout，截断时用冻结 native 的 continuation model 或公开机会资源价评估剩余季节；它是近似尾值。准入后的真实 teacher 必须从相同完整公共前缀各自继续 native/replan 到季末，才能得到真正的官方终局差。小域 surrogate 胜出不够。

### 哪些部分精确，哪些有条件

| 部分 | 可称精确的范围 | 不能扩展的说法 |
|---|---|---|
| partition canonicalization/crossover | 相同目标成员上的等价关系与合法 partition | 不证明两个不同 partition 全反馈下等价 |
| 任意活成员删除后 canonicalization | 保留残余目标对的 co-membership | 失去 witness 后如何重组仍需搜索 |
| 玻璃分类、altitude、动作校验 | official 几何；给定实际 offset 后 | actor 不知道实际 offset 时仅能条件求解 |
| 逐 fiber 最佳 assignment | 固定 field/duration/quality 与冻结可加目标增量时 | quota、Jain、多窗口/witness 不能无条件逐格贪心精确 |
| score 舍入 factor 区间 | 所有合法 program 匹配/不匹配乘数 | 不等于 raw factor 标签或后验概率 |
| 官方终局结算 | 真正执行后的 surviving raw ledger | midpoint surrogate 或尾值没有全局最优/上界保证 |
| conditional mean/CVaR | 给定一个正确条件分布与充分采样 | 当前人工双 world 远未证明分布正确 |

## 本轮实际原型与失败记录

`results/cold_closed_loop_evolution_20261004/probe.py` 已实现 partition 的变异/交叉/精英、公开质量反馈更新、分组几何构造、mandatory 不同 fiber、真实反馈后的再次进化。每个决策 32 个 unique structure fitness；每个 fitness 两个随公开 quality estimate 缩放的人工未来 efficiency levels、最多四个动作的虚拟反馈 continuation。候选时长仅 180/360/720 秒、program 固定 DARK；model 使用 midpoint lunar/airmass，没有官方120秒积分精度。24分钟、28个 L1/L2 公开邻近目标，不是完整卡。

正式 runner 人工环境的 seeing=.8/transparency=.9/sky=.9，efficiency 分别 1.0 与 .4。actor 获得的 public dict 只有 targets/site/fiber/score；efficiency 由 harness 写入独立人工 scenario，未传给 actor。高/低 world 的第一次决策完全相同，180秒真实返回 score 后 partition 与 action 分叉。每条最后 ledger 均由正式 runner/scorer 结算，required/Jain 计入。没有 request、stress、fault、offset、方向事件或背景 closure。

第一版把组只用于中心提案，但允许全目标任选 assignment，削弱了结构语义。8条正式微跑的 GA/单轨终分全部 tie，**19.699380 秒**；已保留 `revision1/`，不能当群体机制成功。随后才改为真正 mandatory concurrency 约束，不扩大候选预算。NumPy 的小矩阵 BLAS 发出数值告警，改成显式三维乘积求和；官方几何核对通过。

修正版实际用时 **23.044987 秒**：

| 公开目录 / 人工 world | 群体终分 | 单轨终分 | 群体差 |
|---|---:|---:|---:|
| L1 / high | 16.954800 | 16.823807 | +0.130993 |
| L1 / low | 8.614181 | 8.824867 | −0.210686 |
| L2 / high | 14.775857 | 14.711411 | +0.064446 |
| L2 / low | −42.952608 | −43.027408 | +0.074800 |

均差 **+0.01488825**，三正一负；L2 low 两种方法都多缺一个 required，处罚 −50。总分非常小，因为这是仅28目标人工微域；不能与真实 L1/L2 或平台分数相比。它也不能说明 native 会输：原型没有与强 native 比较。

`audit.py` 实际 **4.671274 秒**、**19/19 checks passed**：两卡两方法 latent 初始动作/partition 相同，反馈后两者改变；选中 mandatory 组全部由官方 `assigned_hits` 验证；instrumentation 未改首动作；2800 次向量分类与 official `classify_target` 零差；2000随机partition的任意反馈删除后 co-membership 零差。

同为32个结构评价并不等于相同物理工作。首决策 GPU 可批量核的 center×target entries：L1 GA **2,866,360**，单轨 **2,886,100**；L2 GA **2,771,748**，单轨 **2,760,576**。还存在不同 decode_calls、短后缀和Python overhead。所以上表不宣称公平硬墙钟下的 GA 优势。原型的 science-debt 1e−5 pruning 只是近似 tolerance；生产版要保留它的明确误差预算，不能说是饱和证明。原型尚未实现 request/resync，全卡上不能直接使用。

## PRO6000 的具体作用与成本

适合 GPU 的不是把官方 Python runner 搬过去，而是把**许多个体的 belief-world 解码与反馈 rollout**改成驻留 tensor：

1. `[genome, world, center, target]` 的 gnomonic dot/projection、glass 分类和 altitude/lunar 预计算。复用同一个已公开 current geometry tensor，组中心通过 segmented mean/scatter 构造。
2. 16格的 masked/segmented max，mandatory cell occupancy 的 one-hot count 检测，重复 fiber 冲突掩码；带有限 request masks 的小表可以并行。
3. sampled-world 的 score/最大 score/因子区间/coverage count update、残余 token mask 与质量过滤；每一步按自身反馈重算，不能把所有world固定动作序列广播。
4. population×world 的终值 reduction、paired advantage、mean/CVaR，再只回传少量精英和真正首动作。

例如64个体×16world×32center×64target约209万 entries，一组float32约8MiB；depth4 的多数组仍可控制在数百MiB。实际 ragged 时间和group中心不能直接忽略，要padding/mask，或者按相同current time/duration分桶。小N和少个体时kernel启动/H2D成本可能超过收益；需在CPU/GPU各同100批测总耗时，包含采样、解码、同步和D2H，而不是只报投影kernel。

离线在PRO6000做这些并行search/公共proposal学习有可实施任务，但正式actor仍受2CPU/2GiB/900秒约束。若部署环境没有该GPU，需只部署CPU限预算结构求解或从独立world数据蒸馏proposal；不能依赖参赛时远程GPU。官方workflow与实际反馈/hidden执行继续Rhodes1受限CPU；GPU surrogate 必须经官方终局复核。本轮没有执行GPU或报告GPU加速比。

## 下一步准入预算与失败标准

**当前不启动整季。**先补与强 native 相同公共状态、same decoder、真实 public history 的短域准入，才有理由花CPU/GPU。该准入最多8个 L1/L2 状态：各卡按预先等分的四个夜历时点取第一个有至少8个活token、且存在两个以上可行并发组的公开前缀；若不存在记录 absent，不根据实际未来挑点。固化状态、RNG、实际前缀和阈值后，比较 frozen/native、单轨 partition、群体 partition，各给相同3百万center×target entries和1秒额外墙钟上限，以先到者停止，保留 incumbent。native原动作必须一直可返回；违反墙钟或当前动作无改善立即退回。每季最多12个公开触发，不每步重算百万元素。

即使全部短域 surrogate 赢，也只是准入信号。若输出相同、结构仅改变label/hash、或非tie候选在原有公开模型的paired risk gain没有正值，停止，不扩大population或旧pool。若只能靠假定未来closure/event已知胜出，停止该实现。

只有root另安排后，最多8组各native/intervention两条**真正重新规划到季末**，共16续局；按已测433–522秒/完整季估计约1.92–2.32串行worker小时，4个2CPU worker仅CPU上限约0.48–0.58小时，实际依赖/前缀恢复另测。不动锁定teacher批次。所有正、负、tie、absent保留，L1/L2才可拟合/选参；不用L3负标签救阈值，不打开sealedL4。若同预算真实终分均差<=0、预算gate失败、收益来自遗漏required/REQ/Jain/loss，立即停止。

若16续局值得继续，验证应另留至少8个新official-generator seed/config和未见分布条件：未知closure、direction、fault、offset、loss以及不同月份/footprint，source/超参数先冻结。同seed control/intervention都是真实官方执行，actor只挂public输入。以独立world paired total增益和预算完成率检验，不能用相关前缀作为8个独立world。GPU拟合标签也须来自多种已执行公开反馈分叉；新world验证均差不正或风险尾部下降不可接受时拒绝部署。正式E–H仍是未见测试，不用其反馈调参。

## 文件与状态

- 可运行代码：`results/cold_closed_loop_evolution_20261004/probe.py`、`audit.py`。
- 修正版8条runner产物、score report、人工scenario、公共域和trace均在同目录；第一版失败记录在 `revision1/`。
- `summary.json` 保存修正版结果；`audit.json` 保存19门检、work counts、差值与source/public-input SHA。

状态：**PUBLIC_FEEDBACK_PARTITION_MICRO_IMPLEMENTED / SYNTHETIC_ONLY / NO_DEPLOYMENT_GAIN_CLAIM / STOP_BEFORE_SEASON**。
