# 独立运行预算审查：RequestCache 与 native geometry（2026-10-04）

结论：线上 RequestCache 的主要成本是约千次完整 baseline 搜索与请求列的重复构造。配额 DP 本身只占规划时间约 0.17%。α/β 的超时只截掉第 38 夜末尾约 5.15/5.18 小时，已执行公开可观测夜时的 98.3544%/98.2718%；不能表述为损失大量赛季。当前 20 文件 native release 改变了策略组成，缺少线上最佳 RequestCache 的 TerrainPolicy、未来请求列、RequestDeadlineMixin 与 exact cache；单独换入口不能当作完整线上策略升级。root 后续构建的 35 文件组合包已经保留这些机制，本文对其 baseline/裁剪/预测合同做了短检查。

## 范围、规则与证据边界

本审查只读取指定源码 ZIP、native 源码/库、已下载实际线上输出、α–δ 的公开目录/日历/config 与官方已发布文档。没有读取天气 truth、sealed L4 教师标签；没有 SSH、部署、提交或改变共享 actor。只在本报告及 `formal_v4/results/cold_runtime_budget_audit_20261004/` 写文件。没有工作区根 AGENTS.md；已读官方 Python 示例的 `formal_v4/upstream/gosim-observer-examples/python/AGENTS.md`。

官方评分/协议原文为 `formal_v4/upstream/gosim-observer-examples/docs/participant-guide.zh.md`：第 7 节（639–658 行）规定每目标有效曝光中的最佳贡献、不累加信号、required 原始完成因子门槛、Jain 均匀度、请求奖励与 report 结算；第 8 节（664–761 行）规定每条 decision_request 恰回一条同序号 JSONL response。744 行明确：900 秒计时从第一条决策请求开始，包含程序和后端处理，没有独立单轮时限；已接受合法动作仍结算，正在计算的超时响应会被忽略。官方 runner 原文 `runner/challenge/v4_workflow.py:233–283` 实现这些语义。

赛制/容器依据 root 于 Oct 3 正常读取官方 [规则页](https://create.gosim.org/survey26/platform/rules) 后保存的 `formal_v4/research/FORMAL_RULES_CURRENT_ZH.md`（页面版本 2.0 / 2026-10-01）：每卡 900 秒、2 CPU/2 GB，允许自有服务器和外部服务；线上 A–D 按一次完整批次平均，最终 E–H 平均决定排名。此次独立尝试 Web 工具读取该原页失败、IAB 超时，随后遵从 root 不再浏览；未假称独立刷新成功。运行预算/响应丢弃还由直接读取的官方协议和实际 workflow 双重支持。

源码 ZIP `/Users/kamico/Downloads/observer_request_exact_cache.zip` 实算 SHA256 为 `e55becb74bbf2a707aeb893fb054a857610312c81d815181a28bfcf5e5ff092a`，29 文件，解到审查目录 `source_request_cache/`。其中 build_manifest 覆盖的 28 文件全部匹配。给定 provenance 及 ZIP 内 provenance 的 `source_zip_sha256=bfcc...` 是不同值，故不能把该字段当作当前 ZIP 外层哈希的证明；本审查以实际 e55... ZIP 的字节为准。Policy/config 哈希分别与 provenance 的 `e7ab68...` / `590da7...` 一致。四个官方输出目录 archive_manifest 中所有逐文件哈希已独立核验匹配。

线上 artifacts 不含每条 decision_request 的 wallclock、接收时间或逐轮搜索时间；`decisions.csv.duration_seconds` 是模拟望远镜动作时间。α/β 进程超时没有 finish summary，γ/δ 的 agent.log 有总项计时。因此**线上单步 p50/p90/p95 和后期计算耗时趋势不能从这些文件精确恢复**。下文单步分位数明确来自 9.38 秒的短小公开状态 profile，不能冒充线上测量。

## 实际线上成本、决策类别与截止位置

直接统计来自 `formal_v4/results/cloud_request_cache_{alpha,beta,gamma,delta}_20261003/` 的 actions/messages/decisions/observations/score_report/workflow_result/agent.log；全部结果保存于 `actual_summary.json`。所有卡均为 38 夜。

| 卡 | 总分 | 已用真实秒 | agent 秒 | 请求数 | 已回复动作：observe / wait / report | 后端行数 | 终止 |
|---|---:|---:|---:|---:|---:|---:|---|
| α | 7248.868252 | 900.000 | 883.717 | 1289 | 1152 / 135 / 1 | 1848 | timeout，1 条 in-flight |
| β | 6517.864140 | 899.991 | 883.168 | 1255 | 1120 / 133 / 1 | 1829 | timeout，1 条 in-flight |
| γ | 6750.550861 | 883.744 | 867.097 | 1217 | 1107 / 109 / 1 | 1783 | survey_complete |
| δ | 6423.086757 | 587.273 | 574.022 | 1275 | 1096 / 178 / 1 | 1856 | survey_complete |

四卡均值为 6735.09250250。后端 decisions.csv 的 wait 行数分别为 695/708/675/759；长 until_utc 等待内部拆行，所以后端行数不能当作搜索调用数。agent 秒 / 请求数的算术均值为 0.6856/0.7037/0.7125/0.4502 秒，混合了廉价等待、举报、昂贵观测、请求重建与超时在途工作；它不等于 baseline 单步耗时。

α 最后已执行 UTC 为 2026-11-11 03:05:57，公开日历总夜时 1,126,800 秒，剩 18,543 秒（5.1508 h，1.6456%）。β 为 2026-11-25 03:04:27，总 1,078,200 秒，剩 18,633 秒（5.1758 h，1.7282%）。两卡的两个限时请求均已完成；required_missing 分别 4/11。余时百分比不能直接换算得分百分比，也不能保证这些缺失 required 在余时可完成。

后端/解析等开销为真实总秒减 agent 秒：α 16.283、β 16.823、γ 16.647、δ 13.251。即便全部 agent 计算改成零，平台开销也仍需预算。

γ/δ agent.log 可直接分解如下；各分项由原实现 time.perf_counter 累计。

| 项 | γ | δ |
|---|---:|---:|
| Policy 规划合计 | 827.921 s | 548.894 s |
| 实际 baseline 搜索 | 600.860 s / 1111 次 | 458.527 s / 1101 次 |
| baseline 平均 | 0.54083 s | 0.41646 s |
| 请求列重建 | 225.639 s / 12 次 | 89.342 s / 8 次 |
| 每次重建平均 | 18.803 s | 11.168 s |
| quota DP | 1.373 s / 74 次 | 0.985 s / 116 次 |
| baseline / 建列 / DP 占规划 | 72.57% / 27.25% / 0.166% | 83.54% / 16.28% / 0.179% |
| phase 候选总数 | 14,279,597 | 14,154,479 |
| phase exact probes | 17,776 | 17,616 |
| phase 改进调用 | 969 / 1111 | 949 / 1101 |
| midpoint hit / miss | 58,509 / 20,574 | 42,185 / 14,974 |
| midpoint hit 率 | 73.98% | 73.80% |
| midpoint 峰值 | 6,177,600 B | 6,316,800 B |

midpoint 缓存峰值低于既有 16 MiB 上限，不能据此把失败归因于 cache 容量不足。线上 remote_calls、remote_seconds、remote_baselines 均为 0；γ/δ 明确记录 disabled transport，网络不是这批 RequestCache 的直接耗时来源。

实际模拟曝光也在后期变长：前 5 夜平均曝光秒为 α534.6/β539.7/γ616.8/δ497.6；倒数第 6 至第 2 夜为 α1251.5/β1741.0/γ1354.3/δ1413.6。后期每晚曝光数量减少。该趋势只描述模拟决策量，不能替代逐轮 CPU 时间。

## 短小公开状态 profile

`profile_public_states.py` 对每卡已执行 observe 序列的 0/20/40/60/80/98% 六个位置作一次 CPUPhase、一次 native 调用，共各 24 点；取该时刻之前已经输出的 observations 构造最大 score/factor ledger。没有运行整季模拟，也没有读取未来天气。对于事后被 invalidation 的曝光，profile 保留此前已输出值，不试图还原当时完整纠正/terrain/belief 历史。质量尺度统一冻结 `.55`，target scale 为 1，active requests 为空；使用原 RequestCache config 以比较 baseline 算子。由此只能测算工作量形状与条件吞吐。

环境为本机 Darwin arm64、Python 3.10.12、NumPy 2.0.2、BLAS/OMP/MKL 单线程；正式包是 Linux x86_64、Python 3.12、NumPy 2.2.6，故绝对速度不应外推到 2 CPU 容器。总 profile 9.383 秒，另有两个 integration 方法调用，未改变共享来源。

| 单步（秒） | CPUPhase | native |
|---|---:|---:|
| 24 点均值 | .194435 | .164497 |
| p50 | .209208 | .165172 |
| p90 | .225393 | .237333 |
| p95 | .226933 | .269015 |
| 最大 | .227319 | .294147 |
| 前段 0/20%（8点）均值 | .194964 | .172654 |
| 后段 80/98%（8点）均值 | .181481 | .141630 |

native 的均值低 15.40%，但尾部更高。两者每点 inherited SpatialPlanner 都检查 400 个 candidate。CPUPhase 平均额外扫描 12,651 个 phase center，约 607,652 个 center-target 对；build/scan/exact 均值分别 .00450/.08012/.00419 秒，留给 inherited baseline 的约 .10563 秒仍是主要公共成本。native 平均访问 169,005 个 arrangement cell，最大 511,945；sweep 均值 .05485 秒、最大 .16983 秒，exact center 平均 14.83、最多 24。native 尾部随局部目标/边界 cell 数波动。

同一 frozen state 的 selected_exact_rate，native 比 CPUPhase 高 9 点、低 4 点、相同 11 点；两者各有 19/24 点改进 inherited baseline。native 与 CPUPhase 是不同候选族，不是无条件输出等价的实现替换。没有持续的后期 CPUPhase 变慢证据，也没有证据把 α/β 截止归因于最后一夜单步突然变慢。完整源策略受限回放的得分/总时间仍是必要验收。

## 复杂度与保留精度的结构优化

记 catalogue 大小 N=10,000、fiber 数 F=16、side s=4、局部目标 m、duration/program utility 行 Q≈3D。

1. **共有 baseline**：原 SpatialPlanner 每次先作 O(N) 公共几何/质量/priority，再为最多 24 个 anchor 重做全 catalogue 角距扫描，约 O(24N)；400 个有限指向各重做局部投影/按 fiber 选择/曝光 breakpoints。CPUPhase 将 `.planning_budget_seconds` 强制设为 `1e9`，CandidateGeometryPlanner 强制设为 30 秒；二者都会绕过 Policy 原来随剩余预算缩小的 `.22` 秒控制。root 新组合不会仅因接入 native 自动恢复有效预算。

2. **CPU phase**：最多 4 seed、50 ranking targets、24 boundary targets，boundary 构成约 O(b²) center；各 center 与局部目标/3 program/各 duration 作批量 NumPy 分类、排序和选 fiber，主项近似 O(seed·b²·m·D·P)，还带排序开销。真正 spherical/breakpoint `_evaluate` 最多 16 次。其固定 workload 比较稳定，但反复生成大型 NumPy 中间数组。

3. **native sweep**：全 cap 目标而非只用 50 ranking targets，x/y 事件边界各 O(ms)，cell 数 O(m²s²)。它扫 x 列、维护每 utility 行每 fiber 的 winner；winner 离开时会重扫全部 m 目标（`geometry_native.cpp:155–165`）。加上逐 cell 遍历 F 并按 Q 汇总，坏例可以出现 O(Qm³s² + QFm²s²) 工作量；内存为 O(ms+QF)，调用端另有 Qm utilities。C++ 省掉解释器/大中间数组，但当前删 winner 的全表 rescan 是可继续改进的算法点。它精确求解固定切平面的 additive utility arrangement；曝光/球面/projected quota仍靠最终 exact probes，不是球面全局最优证明。

4. **请求列构造**：对 deadline 前所有 900 秒 starts，对至多 8 request anchor、至多 16 fiber-center、2 prefer 分支、3 programs 填列，并为各 distinct duration 重跑 science price baseline。需要 O(starts·request_targets·F·prefer·programs) 次局部工作、重复的 O(N) quality 数组与 science 搜索。原 `_build_geometry`/`_build_quality` 是一次 build 字典；ExactRequestCache 又在新 start/新 build 清空 midpoint。实际 expensive build 是十几秒，而 DP 只为 ≤8 bits 在 endpoint DAG 上作 O((E+C)·2^8)，全季约一秒。优先优化建列和共有 baseline，不应先换 DP。

可执行的精度保留重构顺序：

- **静态邻接与按需投影**：catalogue unit-vector、目标 pair 角距和 target-centered cap 邻接在整个赛季不变。对 anchor lazy cache 一次 exact spherical cap 的完整目标索引；之后只过滤 dynamic visible/priority。请求 anchor 的 `2*fov` pool尤其可跨每个 start/质量 epoch复用。baseline动态偏移中心可用 unit-vector 空间格的保守 cap AABB查邻居，再 exact dot过滤，避免每个 center扫描全 N；不可把邻居数硬截断。用原 candidate集/动作/tie顺序做等价验证。

- **公共量与状态量拆开缓存**：让公共 alt/az/up、月亮/airmass quality midpoint 与投影membership跨 build复用；key含 catalogue/site/scoring/model hash和准确 UTC，不包含非相关 ledger。保留原积分 pieces 的顺序与尾部 midpoint，不以粗时间网格或近似积分替代。raw directional future field 要额外按 terrain posterior、公告有效区间、empirical blocks及质量epoch版本区分，不能按旧 field对象/旧值直接跨 drift复用。已知 public geometry本身无需因 score ledger更新重算。

- **填列共享**：同一 `(start, anchor, fiber placement, duration)` 的 `_fill` 目前对 prefer=False/True各计算一次相同分类和系数；先计算一次共享几何、integrated coefficients、eligible、forced_fiber，再分别执行两个选择规则和三 program。缓存必须保留完整的 membership与原 tie顺序。science fixed-price多 duration仍可拥有独立 priority/anchor集合，但共同 center的分类可以复用，不能偷偷把所有 duration改成同一 anchor shortlist。

- **native winner数据结构**：每 `(Q,fiber)` 用支持删除/过期检测的 max heap或平衡树，utility tie按原 target顺序处理。事件只更新受影响 fiber；减少 winner离开时 O(m)全扫，目标趋于 O(Qm²s² log m)而不是 cubic坏例。保留当前每个 cell的F项求和顺序及 `1e-14` / `.04*pitch`去重语义，避免“数值更快”改变tie。先在 synthetic与真实公开frame比较全部 bestx/besty/bestv，再看实际尾部。

- **2 CPU用于独立公共准备**：第二核心可准备下一已知 start的immutable公共几何或同一同步build的独立 starts；结果按原 starts排序归并。不能在未知未来天气上执行确定决策，也不能把后台/外部计算误当计时豁免。NumPy当前单线程设置合理，2 CPU不是允许各 BLAS线程无限扩张；双进程要记录RSS峰值、限制排队和数组复制。

## 组合合同审查

旧 ZIP 29 文件 vs原 native 20 文件的逐文件差异保存于 `source_comparison.json`。完全相同的11文件包括 `agent.py`、`policy.py`、`research/spatial_candidates.py`及基础反馈/校准模块；3文件不同为 manifest/project/config；旧包独有15文件，含 terrain/request/CPUPhase/transport模块；native独有6文件，含入口、sweep、bridge及两平台库。旧config有31个键，native config仅 `neural_continuation_strength=.3`，且 native release源码没有引用该键。基础 Policy默认仍有修复/clock/calibration，但有默认不等于安装了线上Terrain及RequestDP类。

root现有组合 `formal_v4/results/request_geometry_integration_20261004/geometry_package/` 为35文件，保留旧29文件中的27个逐字节一致；变化为 `observer.project.json`与`build_manifest.json`，新增6个 native/adapter文件。`policy.py`、旧 `policy_config.json`、全部请求/terrain/disabled-transport模块保持原字节。该事实见 `root_composition_source_check.json`。

composition方式适合此MRO：`GeometryCachedRequestPlanner(ExactRequestCacheMixin, RequestRemotePlanner)` 的 `_choose_baseline` 调独立 `CandidateGeometryPlanner` child。原 `ExactCachedRequestPolicy -> DistributedRequestPolicy -> TerrainPolicy -> ModelGPUPolicy` 保留；factory guard的模块变量与 `policy.SpatialPlanner`在initialize前同步替换。REQ pool、future field、cache与score ledger仍属于原owner。传入 env中的 `target_quality_scale`承载parent Terrain后验；offset校准、scores/factors、active_requests同调用传入child；返回动作并复制 `last_prediction/stats`供原反馈链使用。child不拥有独立ledger。

`check_root_composition.py` 用实际公开αcatalogue实例化、一个cached request列以及stub baseline，约0.11秒完成方法合同检查：原 baseline900秒遇120秒请求边界后 outer RequestDeadlineMixin真正在同一轮重新调用 `_choose_baseline`；child tmax 依次3600→120，最终动作120秒；parent/child都finally恢复3600。scores/factors/active_requests/target_quality_scale对象身份保留，prediction正确复制；`clipped_baselines=1`、`forced_cpu_crops=1`、baseline calls=2。未发现改变反馈或请求执行语义的bug。结果为 `root_composition_contract_check.json`。这不是完整得分验证，build/forecast/terrain更新仍要完整回放。

另一个same-object MRO组合最小检查也保存在 `combination_contract_check.json`，证明显式 `_choose_baseline -> CandidateGeometryPlanner.choose(self,...)`可以跳过CPUPhase.choose与REQ.choose且不递归。root采用composition更容易保持ownership，当前无需改路线。

发现一项统计漏洞：CandidateGeometryPlanner.choose在 base=None / frame=None的早返路径未重置stats；adapter原先会复制child上轮stats。默认deadline路径通常重新覆盖planning_seconds，但bypass+None路径会累计旧planning值。root已在adapter调用前清空 `engine.stats`与`engine.last_prediction`，它不改变搜索精度。修复后对当前组合源码重跑边界合同检查仍通过，复核源码哈希见 `root_composition_review_hashes.json`。

## 900秒预算管理与外部计算

Policy虽然估计 `2200*fraction_remaining`，但CPUPhase固定workload与native 30秒覆盖使该budget不控制主要搜索。请求build只在 `remaining_seconds<30`时不启动，缺乏“本次build+余下baseline+平台”的联合检查；18.8秒仅是γ平均，不能当最坏上界。故完成预算需覆盖stage，不应靠临近截止把anchor/precision骤降。

建议每轮记录stderr上的 sequence/now/action/remaining、实际baseline/build/DP/geometry秒、候选/arrangement cell数与cache hit/miss、stageRSS。把剩余昂贵观测调用预测建立在滚动曝光数、模拟曝光时长、剩余night window及缓存中尚未完成请求build上；wait/report单独计价。更新预算为：剩余wallclock减近期p95平台开销、所有必需stage、余下baseline估计与完成reserve。实际四卡平台全季13–17秒，不能只预留零。

完成reserve应该对应可执行工作：保留已经计算出的合法baseline，pending request重建以public/geometry部分增量复用；重建结果按完整epoch原子提交，未完成epoch不能伪装为完整有限列最优解。通过消除重复计算先获得余量，然后保留固定搜索族和精度。只有可验证的上界剪枝（候选不可能胜过当前best）或计算memoization能够在保持解意义下缩短固定工作。根本未做的搜索可在描述中明确为预算策略，但不能宣称与原精度等价。

2GB没有被实际日志证明耗尽，不能把timeout描述成内存问题。midpoint peak约6MB只是该cache，不是全进程RSS；跨build缓存及child重复catalogue应有真实nbytes/RSS配额，不能把2GB全部分给一个cache。

规则允许外部自动计算，但本次offline RequestCache没有remote工作。外部收益必须比较端到端发送catalogue/ledger、建session、等待、反序列化、fallback以及失败超时后的剩余预算，不能只报告GPU kernel秒。第一个失败调用仍消耗900秒预算。普通高频baseline在正式γ平均约.54秒，若network round trip比它长，需要持久session、batch public preprocessing或减少往返才可能有益。此次未测网络、未启用或部署服务。

## 下一步验收

1. root已启动当前最佳RequestCache control vs保留Terrain/REQ/cache的geometry组合，保持原参数，对合法L1/L2作四条完整协议、2CPU/2GiB/900秒受限回放。本审查未SSH或读取远程结果。应记录总分组件、required/request完成、终止原因与各stage秒；profile15.4%只是条件均值，不是线上季节加速承诺。
2. 在组合验证后，优先做exact静态邻接缓存及`_fill`共享，再扩展跨epoch公共midpoint缓存；用原候选输出/动作/数值tie等价验证，避免依赖密封标签。
3. 给native winner删除做heap/tree改造，以相同frame全输出比较及密集局部坏例检查尾部。只有arrangement访问证据支持该重构，无需盲试更少seed/更少duration。
4. 下一次受限运行保存逐轮stage trace，再报真实每卡p50/p90/p95、请求重建spikes与后期趋势。现有下载文件不足以补造这些数字。

审查产物目录：`formal_v4/results/cold_runtime_budget_audit_20261004/`。核心证据为 `actual_summary.json`、`public_state_profile.json`、`source_comparison.json`、`source_manifest_verified.json`、`root_composition_source_check.json`、`root_composition_contract_check.json`；三个Python脚本可独立重跑。以上改造建议均未在共享actor或正式提交生效。
