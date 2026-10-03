# 正式 objective、跨时段竞争与完成证书

2026-10-04 JST；先独立阅读 upstream scorer/runner/fiber/config/公开 L1–L4，再阅读 ALGORITHM_PORTFOLIO_ZH.md 去重。没有访问线上、修改生产策略或 Git index。

## 1. 完整目标与图结构

曝光 e 由开始 t、实际结束 t+d、指向 (a,A)、program p、每 fiber 至多一个 target 的 assignment 构成。最低高度须在整个曝光内满足；几何只在开始命中一次。单次信号 g 是截断至 1 的时间积分，多次曝光不累积信号。

对给定动作序列 π，记 v_e(π) 是该曝光最终有效性。正式目标是：

S(π) = Σ_i max_{e:v_e=1} c_ie − P Σ_{i required} 1[max_{e:v_e=1} g_ie<θ]
       − U(1−J(n_1/N_1,…,n_B/N_B))
       + Σ_r R_r 1[Σ_{i∈T_r} 1[∃有效e，e完全位于r窗口且g_ie≥θ_r] ≥ k_r]
       + report settlement.

scientific best、required factor、每个 request window 的 factor witness 可以来自不同曝光。不能只保留最高 science 对应曝光的 factor。现有 Policy 确实分别保存这两个最大值，并按 loss rescan ledger；这里没有找到缺失的基础实现。

**固定终局存活曝光集合** 后，science max 是单调子模函数，可等价为 target 分数层的加权 coverage；required 是 target 的阈值 OR coverage，也是子模项。Request 的 k-of-n gate 在不足 k−1 时有互补、过 k 后有替代，对 k>1 既不全局子模，也不全局超模。Jain 可能出现负边际，不保证单调或子模。

这不能直接推广至动作序列：时间可行性是路径约束；缩短/增加曝光改变后续时刻、program band、request window 内 witness；data_loss 又按 trigger 时的 observe 总数 N 与 action rank 的 floor 比例撤销旧曝光。空 assignment observe 也计数。任何改变时长、数量、跨 trigger 的搜索都须重算 v_e(π)，不能冻结原有效标记。

一个有限曝光列模型的精确表示是：

- 时间 DAG 的弧 x_e 是一个合法曝光；wait 是另一类弧，path conservation 排除时间冲突。
- 每 target 的 science 层 ℓ有 OR gate z_iℓ = OR_{e:c_ie≥ℓ}(x_e v_e)；相邻分数层差作权重。
- y_i = OR_{e:g_ie≥θ}(x_e v_e) 表示 required/RA 完成。
- u_ir = OR_{e:e⊂window_r,g_ie≥θ_r}(x_e v_e)，request gate h_r = 1[Σ_i u_ir≥k_r]。
- RA 只有 B≈12–13 个整数 count；Jain 应在叶/实际组合上精算，不把正梯度当严格 reward。
- 时间节点还须携带 observe rank；loss 情景增加 trigger 时 N，或直接由完整序列回放生成有效性。

这是一张带 quota gate 的 coverage/interval-conflict hypergraph。它不是普通 matching；只有固定 field、固定时间与 program、忽略组合 gate 后的每 cell 指派可分解成独立 maxima。

公开卡均只有两条 8选6 请求，奖励各100，无 requested target 与 required 重叠。请求 gate 的总奖励200使它值得精确处理，但不足以解释主要科学分差。单 focus quota DP、required mincost 预约、旧 resource-graph 上界已有实验，不重做。

## 2. 实际遗漏：program 也决定 raw-factor 完成证书

Policy._ingest_result 使用无条件安全 factor_lower；feedback_model 的界是

    L_i = min(1, (score_i/w_i − rounding_i) / max(m_declared, mismatch)).

于是 required 真完成与其**可从反馈证明完成**是两个状态。_evaluate 的 required 加50只看预测 raw factor 跨0.5，没有续局中证书不确定性的代价。fitted_factor 已存在，但不能用低拟合残差把它当严格证明。

例如真实 g=.55、DARK 声明 mismatch，score/w=.55，安全 lower=.4583；同物理曝光声明 BACKUP，mismatch 时 lower=.5189，可以确认完成。program 不改变 g、实际 required 物理奖励或时间；潜在收益来自避免后续再次调度、改变天气拟合/后验和 request 公布 witness。不能再给 certificate 加一笔50而重复计入真实 required 奖励。

单纯选择 BACKUP 也不是一个已证明策略：同 field 其他匹配 DARK/BRIGHT 的目标可能失去 bonus，天气后验会变化，多个目标的证书集合也可能改变。因此要做 program-only 分叉、真实重新规划续局，而不是固定后续排程评分。

现有强 CPUPhase 完整 trace 的 observational audit：

| 卡 | 首次真实完成但没有安全证书 | 其中后来 revisit | 到首次证书前后续 hit | 这些 hit 的 science 增量 |
|---|---:|---:|---:|---:|
| L1 | 0 | 0 | 0 | 0 |
| L2 | 16 | 16 | 18 | 3.521683 |
| L3 | 1 | 1 | 5 | 0.000476 |
| L4 | 5 | 5 | 5 | 1.690741 |

L3/L4 这里只过滤最终有效记录，没有重构 resync 前证书时间线；这些计数不能当作精确省时或因果收益。L2 中10个首次曝光 g≥.530002，原 program 都 mismatch；换 BACKUP 可在同 raw factor 下无条件证明完成。

预声明单次因果教师选点：L2 rank6，2026-11-09T00:54:54Z，(31.0428622,136.5797864)，627s，15 assignments 保留，仅 BRIGHT→BACKUP。整个 field 的真 band 均 DARK，两种声明均 mismatch，因此物理即时 science 差精确为0；V4T007377 的证书由除1.12改为除1.06。最低真实 science 成本按 feedback rounding 容差并列后选最早 rank，使用 truth 选点属于 privileged teacher，不能当在线选择规则。两条分支都重新规划到终局，control 必须重现6792.219245与原 prefix。

**因果教师已完成，停止采用该路线。** Linux同源强CPUPhase的control完整actions逐条匹配旧trace，终分6792.219245；BACKUP分支6765.980248，真实完整续局差 **−26.238997**。全部same-prefix、只有program改变、原control精确重放、完整survey、无traceback门检通过。science差−26.251138，required/REQ/report不变，Jain项改善0.012141。

证书机制本身确实发生：V4T007377 lower由0.4990977679升至0.5273485849，fitted factor与反馈score在两条分支都为0.55899。但是joint score拟合的C/E分解由(1.0549934,0.8538694)变为(0.9514425,0.9468009)；相似有效quality乘积没有锁住program band或后续排程。全季observe数1096→1103，更强证书没有带来预期节省。当前零science代价与更紧安全界不能替代终局价值。只保留这条真实replanning分叉作教师负样例，不换选点、不以L3/L4救结果、不训练或部署certificate优先program模型。

## 3. 合法几何自由度：天顶 az 旋转

actual altitude=90° 时，center RA/Dec=(LST,site latitude)不随 az 变，但 fiber tangent up/right 随 az 旋转。只按球面中心向量去重会漏掉这个角度。已与 global_field agent 协调，由它负责 native proposal，我只做历史/合法性核验。

目标 horizontal unit vector 为(x,y,z)，天顶 tangent 坐标：

    dn = (−x cosA−y sinA)/(z DEG)
    de = (−x sinA+y cosA)/(z DEG).

两轴等于玻璃格边界（包含生产.008°安全 margin）的解析根切分 az；每个 open interval 内 assignment 分类相同。固定 duration 时，所有目标分数独立 az，可逐 cell 最大值/event sweep。退化边界 tie 如需严格全集还应验 roots 本身；正式命令 rounding 后再次分类。4×4 square 的天顶总效用有90°周期。最大合法 actual altitude<90° 时须扫360°近天顶环。

合法例证：L1 2026-11-02T03:30:00Z，V4T001104 在60s内最低高度88.955129°；(90,0)命中fiber1，(90,30)命中fiber4，中心都为(23.5294193588,−24.6157)。L3正alt offset可补偿到实际天顶；L4负alt offset使最大实际高度89.950631665°，只可扫环，不能提交>90°命令。

16个真实首夜 prefix（L1/L2各8）的微验证花3.1秒：4/16最佳天顶 az胜A0，0/16胜同 frame 强CPUPhase。全部所选动作通过官方 schema、fiber、整曝光高度检查。history best-score来自真实trace；factor为离线truth，天气共用.55 prior，不能当exact原policy belief。该结果只支持便宜的边界候选补充，不支持独立切换或整季提分。prefix frame已交给global_field作等价与成本核验。

## 4. 突破局部 action critic 的具体普通 NN 教师

现有 urgency 是 future_nights 的独立目标函数；它看不到两个目标共同竞争一个未来 cell，而另一个目标有不竞争的替代 cell。举例：当前可完成a或b，未来resource1只能从{a,c}选一个，resource2只能选b。a/b/c均有一次未来机会、同权重、同flux；先a可最终完成3个，先b只能完成2个。单个目标的“未来次数”相同，竞争图不同。required 每目标50时，聚合 action 特征可以漏掉至少50的差。

下一种教师不应继续固定后续排程并删除重叠动作。建议使用两晚/多晚的真实 replanning 分叉：包含原动作、等时 wait、替换field、program-only、短/长曝光，每条分支按新反馈重建政策并重新生成后续动作，完整真结算给标签。原动作保留，先验证same-prefix与原样control。

图输入限定已公开信息与反馈：target节点（best score、安全factor区间、required、band、flux）；候选曝光节点（真实时间区间、program/duration）；每曝光的fiber节点与所有可选target边；时间冲突边；request quota节点；RA count节点；历史 witness节点（rank/start/end/survival）。candidate→fiber 的层级保留“同field16格必须同时使用”的耦合，不能把各target独立预约。

GNN/普通NN输出应是 continuation **结构量**，而不只是35维action汇总→scalar：每 target 的终局winning-score、raw完成概率；每 request 的联合quota成功概率；RA count的联合样本/终局Jain；完成证书状态及未来重复访问资源量。科学 max、required、quota、Jain在图外按真实定义结算。这样分叉的终局标签可归因到争用目标和certificate，不会把 signed science、物理完成与信息证书混成一笔奖励。

上述结构化竞争图路线尚未实现或训练。此次program-only分叉是一个合法、真实重新规划的负教师样例，说明输入必须保留factor interval与C/E belief的结构，不能只把证书变紧当正标签。它没有证明GNN或NN有效；certificate优先program路线已停止。若后续独立测试竞争图，必须另行预声明多策略分叉教师与训练/验证/最终卡，不能部署此次truth选点。

## 文件

- research/objective_graph_zenith_probe.py：解析天顶events、16-prefix冻结utility/官方合法性核验。
- results/objective_graph_20261004/zenith_prefix_probe.json：微验证、源锁及frame。
- results/objective_graph_20261004/program_certificate_audit.json：现有轨迹证书统计。
- results/objective_graph_20261004/program_certificate_switch_L2.json：固定field逐program真实science代价。
- research/objective_graph_program_agent.py、objective_graph_program_gate.py、objective_graph_program_plan.json：单次program-only正式protocol因果教师。
- research/objective_graph_certificate_audit.py、objective_graph_program_pair_audit.py：可重建的现有轨迹统计与严格same-prefix/终局门检。
- results/objective_graph_20261004/program_predeclared_plan.json：选点规则与原prefix/action。
- results/objective_graph_20261004/program_pair_causal_audit.json：负教师、11项通过的因果门检、target层终局差及artifact hash。

首次快照漏agent.py的启动失败目录单独保留，不把其分数当算法结果；修复后源冻结未改。两个正式容器和PID终止状态以及归档manifest另存于结果目录。
