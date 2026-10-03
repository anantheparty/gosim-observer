# 正式 V4 科学收益模型冷审计（2026-10-04）

结论：发现两处具体的模型语义差，均有官方函数计算反例。其中 **曝光起点 program 分类替代曝光积分分类** 已在当前线上 δ 的公开历史上产生固定指派候选排序反转；**terrain 清晰概率先乘质量再封顶** 在 α、δ 的真实前缀中确实触发，但已扫描 δ 指派的科学估值偏差很小。它们支持窄范围修正实验，不能解释榜首与本队全部科学差，也不能据此断言短曝光是错误策略。

本次只新增本文和 `results/cold_science_model_audit_20261004/`。先独立读官方 `v4_scorer.py / v4_fiber_map.py / v4_runner.py`，随后核对 RequestCache ZIP 与 native READY 锁源，最后才读 `ALGORITHM_PORTFOLIO_ZH.md` 查重。没有运行整季、调用 planner.choose、SSH、GPU、提交、修改生产或固定教师/学生；没有读取 sealed L4 教师标签、L3 救参或未来 truth。早期文件发现搜索返回了旧结果文件名和少量匹配行，没有使用这些标签建模或选择条件。

## 官方结算与实现逐项对账

记 `H_i(t)=lunar_i(t)/airmass_i(t)^0.6`。官方配置为 `q0=.68`、`f0*t0=.5*900=450`。

\[
 q_{exp,i}={1\over q_0 t}\sum_j\Delta t_j E_j
 {T_j S_j\over seeing_j}H_i(t_j),\qquad
 g_i=\min(1,f_i t q_{exp,i}/450),
 \qquad c_i=w_i g_i m_i.
\]

积分按槽边界和事件 start/end 切分，每片最多 120 秒，取中点。关闭与 gap 的贡献为零，仍占整个曝光时长分母。`q_band` 另行积分 site weather 与每目标 H，排除 instrument efficiency 和 directional events。`m_i` 由每目标曝光平均 `q_band` 与声明 program 决定；同一次曝光允许不同目标分属不同实际档位。

| 项目 | 官方 | native READY / RequestCache | 审计结果 |
|---|---|---|---|
| flux、duration、q0、封顶 | `min(1,f*t*q/450)` | 同一常数与形式 | 无漏平方、漏权重或额外 q0 的错误 |
| 科学收益 | `max_e c(i,e)` | 候选增量 `max(0,w*g*m-best_score)` | 公式一致 |
| 历史 best 与 factor | 科学 best 按 score；required/Jain 按独立最大 raw factor | score/factor/lower 独立数组；resync 重建有效历史 | 无“best score 所属 factor 替代最大 factor”的错误 |
| factor 反馈 | agent 只收到六位 target score | fit 同时枚举匹配/失配；规划使用无条件 `factor_lower` | 下界正确；point fit 仍有 C/E/program 不可辨识性 |
| REQ 证明 | 窗口内完整曝光，独立 raw factor 门槛；失效可撤销 | active/result/resync 提供 proof，替换 completion 集合 | 没发现把 REQ 当可累加 science 或永久不可撤销证书 |
| pointwise Moon/airmass | 官方天体与 airmass 模型 | 公共 vectorized 模型 | L1/L2 点值负对照误差 <1e-10；差异来自时间聚合 |
| 普通 science 曝光积分 | 每目标、每 duration 积分 | `SpatialPlanner.choose` 在 now 计算 `public_quality` 与 band，所有 duration 共用 k/mult | **差异 A**；native 和 RequestCache baseline 均继承 |
| RequestCache request columns | 同上 | `_average_public_quality/_average_raw_quality` 按槽/120s 积分 | 公共几何积分正确；仍先平均 terrain 再封顶 |
| terrain uncertainty | 真 sector 对每积分片为 clear/zero | posterior `expected_clear_fraction` 当乘法质量输入 | **差异 B**；RequestCache 专属 posterior 路径 |

RequestCache ZIP SHA 为 `e55becb74bbf2a707aeb893fb054a857610312c81d815181a28bfcf5e5ff092a`，其 policy、spatial_candidates、feedback_model、request_deadline_common 与工作目录读到的四文件逐字节相同。native READY 的 policy/spatial/feedback 与其锁源相同，因此本次读到的是实际目标实现。全部 source SHA 在 `source_manifest.json`。

## 差异 A：duration-dependent band 被冻结为起点 band

确切位置：`research/spatial_candidates.py:281` 使用起点 H 构造 k；`:283` 构造起点 bands；`:430` 与 `:435` 在全部 duration 中复用。native 几何和 CPUPhase 的最终精算仍调用这个父类。RequestCache 缓存只改变重复计算开销，没有修复 baseline 的时间聚合。

最小官方反例使用公开 L1 目标 `V4T000001` 的真实 RA/Dec（36.126988°, −51.687990°），2026-11-02 04:30Z 开始，3600 秒；共同的合成常量 weather、Moon penalty 明确设零，没有使用真天气。起点 `q_band=.651` 属 DARK，曝光平均为 **.646789326**，实际 BRIGHT。factor 已饱和：起点模型给 DARK **1.2**；官方声明 DARK 得 **1.0**，声明 BRIGHT 得 **1.12**。所以仅公共 sky geometry 的时间变化就能改变 program 排序；不需要天气 forecast 正确。

真实线上 δ 前缀有更具体的候选证据。只从 `cloud_request_cache_delta_20261003` 的过去动作、rounded hit scores、已发布消息和公开 scenario/fiber/scoring/targets/night calendar 五组件重建状态，在 observe **46**（2026-10-25 03:21:04Z，**785 秒**）保持原指向、原 assignment、当前 C/E prior、start terrain scale、原 scarcity urgency，重算三个声明 program 的科学效用：

| 计算 | DARK | BRIGHT | BACKUP | 最好 program |
|---|---:|---:|---:|---|
| 起点 frozen H/band | 10.121010 | **10.389707** | 9.571112 | BRIGHT（原动作） |
| 官方槽/120s 网格的公共 H 积分 | **11.359271** | 9.834517 | 9.680279 | DARK |

该曝光有 8 个 assigned 目标在当前 prior 下从 BRIGHT 跨到 DARK；官方下载的已发生观察反馈这 8 条 `prog_mult` 均为 **1.0**，原 BRIGHT 声明确实失配。另 observe37 的一个目标跨档，固定指派最好 program 仍 BRIGHT，已保留这个负例。前220次 δ 曝光共有 9 条跨档、1 次固定指派 program 排序反转；α同样前缀没有该跨档条件。

这些数是 **共同 C/E prior 下模型排序**，不是已实现 gain。真实曝光未来 C/E 未知；失配反馈单独不能区分 DARK 与 BACKUP。不能声称换 DARK 必然提高真实终分 1.524755，也不能把一个动作的 immediate gain 当季末 best 增量。

可立即实施的最小修正：保留现有有限候选族和 ledger，用 `(start,duration,public_geometry)` 缓存每目标 H 积分，对最后 shortlist 的已有 duration 重新计算 k、bands、三 program、逐 fiber winners；保持 weather/efficiency prior 为同一个估计。积分利用 RequestCache 已有 `_integrated_public_quality` 的网格或其轻量 subset 实现。只翻 program 是较小门检，完整 shortlist 重评分还需重新选同 fiber 目标。duration breakpoints 当前针对 frozen k 才“精确”；积分后的 k(d) 不应继续宣称全时长精确，也不需要先扩大候选池。

## 差异 B：posterior clear probability 与连续透过率混用

确切输入链：`terrain_version_space.py:172` 返回剩余 sector box 的 volume-weighted clear probability；`terrain_policy.py:83` 将其送入 target quality scale；`spatial_candidates.py:278–282` 乘进 k，然后 `:430/:435` 做 cap 与 best 正部。request column 的 `_average_raw_quality` 先积分每片 expected_clear_fraction，`request_deadline_common.py:200/:218` 之后再 cap/正部，因此也有相同运算顺序差。

若令 `A_s` 是同一个后验 sector 场景产生的曝光未封顶容量，真正与官方 payoff 相容的条件期望为

\[
 E_s\big[\max(0,w\min(1,A_s)m_s-B)\big].
\]

现模型为 `max(0,w*min(1,E[A_s])*m_point−B)`。固定 B=0、m 与场景无关时，cap 的凹性使后者高估；B>0 时正部还会产生反方向漏值，所以不能用一个统一打折系数修复。

最小排序反例已同时调用官方 `score_target_exposure` 与实际 `SpatialPlanner._evaluate`（固定合法900秒时长，one-fiber collision 夹具，required/均匀项为零）：

| 同 fiber 候选 | clear posterior | 未遮挡容量 | strategy plug-in science | 按官方两场景先评分后的期望 |
|---|---:|---:|---:|---:|
| uncertain | .5 | 2 | **1.2** | .6 |
| safe | 1 | 2/3 | .8 | **.8** |

真实父类 `_evaluate` 选 uncertain，后验期望应选 safe。另 `B=.9,A=.8,p=.5,m=1.2` 的 strategy gain 为0，正确期望为 **.03**。这说明漏选有增量的旧目标也是该差异的结果。

required/REQ 的门槛也必须放在场景内：`Pr(g≥.5)` 不能替代为 `1{E[A]/safety≥.5}`。例如 p=.5,A=2，当前 robust mean 达门槛，却只有 .5 的实际完成概率；若 required 奖励价值按官方50计，模型把期望25当50。`duration_safety=1.1` 在 Bernoulli 全遮挡场景中无法保证完成。

真实历史触发扫描限制为每卡 **前220次已发生曝光**，避免用后来的 terrain evidence 初始化早期状态。逐条 ingest score 与公共消息更新同一 posterior；排除 temporary modifier 与1200秒 blocked spot 的额外缩放，只计一个可能遮挡 family 的情形。在每个 surviving box 中按同一公共120s轨迹积分，再 cap/best；C/E 在两个比较式中固定为同一个当前 prior。它是 **部署 posterior 模型内部的运算差**，posterior 未经真实概率校准，不是对实际未知天气的精确条件期望。

| 前缀统计 | δ | α |
|---|---:|---:|
| assigned target occurrences | 3267 | 3252 |
| start terrain probability 严格在(0,1) | 575 | 401 |
| 排除额外 modifier、单 family 后可比 | 140 | 354 |
| cap-before-expectation factor 偏差 | 14 | 76 |
| 科学 gain 高估 / 漏值 occurrences | 14 / 3 | 76 / 6 |
| 单项最大 gain 高估 / 漏值 | .028877 / .011945 | .201821 / .018253 |
| 高估相加 / 漏值相加 | .157836 / .016055 | 4.833168 / .071261 |
| missing-required mean 达门槛而后验完成非必然 | 24 | 34 |

δ最明显：observe32 的 V4T003879，p_start=.972185、未遮挡capacity1.465683，plug-in gain1.2、posterior mean gain1.171123；其已发生真实 score 恰为1.2。因此这条触发**不能**被称为实际损失。αobserve176 的 V4T001104，p_start=.664512，model integrated factor .917922 与 posterior expected factor .749738，science高估 .201821，其真实反馈是0；αobserve53 的两个 .42 clear probability 目标也真实得0。零反馈只核对触发条件下的实际 outcome，不证明 posterior 概率被校准。

上述 sums 是同一前缀中旧模型估值与后验估值的代数差；重复目标、后续 best 替代、其他行动机会、共同地形相关性没有转化成终分。**δ扫描结果不足以解释739.44科学分差**，并且没有真实完整候选族上由此独自触发的 field 排序反转证据。

窄修正对象是当前有限 terrain posterior：保持每个 box 的静态 sector 在曝光片间一致，先积分每个场景，再 cap、减 best、计算 threshold，最后做 volume-weighted average。一次 fiber 决策在执行前必须选择一个 target；不能把 `E[max_target payoff]` 当作 `max_target E[payoff]`。不确定性 source（terrain probability、temporary attenuation、site weather C/E）需要保留各自含义，不能统一用一个 target_quality_scale 再期望。原 native 的 .05/.28 heuristic 没有声明为 posterior probability，本报告不把这套概率证明无条件套到 native heuristic 上。

## 已排除假设与查重

1. **“覆盖数少所以 science低”不是充分解释。** δ官方 targets_observed=8917中只有12个是仅零分，正分8905；其最佳曝光 factor 分类是 saturated3140、.5至1有3901、正分<.5有1864、零分12。8917是账本包含目标数，不代表已完成或已饱和。更高覆盖也不能单独证明短曝错误。
2. **累计曝光 factor 相加、历史 best 乘子错账、q0重复归一化** 均未找到源码错误。官方 best(score)与max_factor的合成负对照已验证：factor1/score1与factor.9/score1.08共存，best=(.9,1.08)、max_factor=1；生产同样分账。
3. **缓存改变收益模型** 被排除。exact cache scope是同build/start/field，复用相同中点数组并保持各duration原加法顺序；它继承上游模型差，没有独立引入这两处差。
4. **pointwise astronomy模型错** 被L1/L2公共点值对照排除；公式与官方相同。普通search的起点近似和request积分路径要分开看，不能说所有RequestCache都漏积分。
5. **任意场景模型都应采用** 被既有实测否定。独立审计结束后才读取 portfolio，发现其20261003 scenario_value 已实现“路径内积分→program→cap→best→threshold→期望”，修复 prefix consistency 后 L1+25.788278、L2−59.321419，已拒绝。此数学顺序不是新算法；本次新增的是部署代码的确切输入链、实际父类排序反例、当前线上δ固定指派program反转、两真实前缀的有限posterior触发计数。它不支持重启旧16条AR路径bank或重新救参。
6. **REQ损失撤销与required预约不足** 已有研究，本审计没有用它们重新命名新算法。当前δ仍有6个required missing；线上 trace 审计同伴指出六者都是低flux QSO，science欠饱和的主要权重也在QSO/ELG/LRG。这与本次小额terrain偏差并不构成因果等价。

## 复现与文件

执行：

```sh
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 python3 -B formal_v4/results/cold_science_model_audit_20261004/audit.py
```

- `audit.py`：公开初始化、官方合成反例、真实score前缀重建、后验box内评分；不会调用choose或workflow。
- `minimal_counterexamples.json`：实际父类排序、官方program积分反例、best/factor负对照、pointwise geometry负对照。
- `delta_public_history_audit.json` / `alpha_public_history_audit.json`：限定220曝的触发、真实已发生score、固定指派program排序、完整既有历史的结算诊断。
- `source_manifest.json`：源码与ZIP锁源、actor输入范围、禁止操作范围。

扫描过程中 observation CSV 的 factor/quality/prog_mult 仅用于独立的事后结算诊断或已发生失配核对；actor重建只使用 target_id/rounded score。没有将事后factor、未来失效标志、最终score或未来公告送入早期 C/E/terrain状态。重建没有调用完整action选择，不声称每个未知active-request snapshot都被恢复；这些缺失不会影响本次 terrain posterior、C/E输入与其科学score账本对比。
