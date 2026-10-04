# 共同曝光的路径—纤维匹配控制（2026-10-04）

## 范围与独立推导

先阅读正式 `v4_scorer.py`、`v4_runner.py`、`v4_workflow.py`、`v4_fiber_map.py`、Python protocol，以及 L1 public catalog/calendar 与 public site/instrument/score 配置，再检查 `ALGORITHM_PORTFOLIO_ZH.md` 与 quality-window 报告。这里采用的控制源是实际 29-member RequestCache ZIP：

`/Users/kamico/Downloads/observer_request_exact_cache.zip`

SHA256 `e55becb74bbf2a707aeb893fb054a857610312c81d815181a28bfcf5e5ff092a`。

运行前逐个验证解压的 29 个文件与 ZIP 字节一致。没有采用失败的 native composition，也没有使用 native/BasePolicy 的旧分数作为本原型证据。所有新增文件仅在 `results/cold_common_exposure_control_20261004/` 与本报告内。

正式曝光的公共抽象是同一 `(start, duration, pointing, program)`，搭配至多 16 个不同 fiber 的目标。一整个曝光共同消耗实际时间，天体跟踪使 fiber hit 只在起点检验；每个目标的 Moon/airmass 和 program band 仍需逐曝光积分。科学目标是每 target 的历史最大 contribution。短曝光累加不能替代一条高质量长曝光，也不能给每 target 独立领取自己的最佳 start。

这是一个可执行滚动窗口算子，不是整季上界，不是完成 production gate 的新策略。本轮仅检验 science 的共同时间竞争；required、Jain、REQ、report、loss 和观测信息价值不在该有限目标里。当前前缀无 active REQ 不表示未来没有未知 REQ。

## 具体模型：共同区间与联合 fiber assignment

未来候选 e 固定共同起点、时长、program 和指向，并保留每个可命中 fiber 的全部有用目标。设 `x_e ∈ {0,1}` 表示执行曝光；`w_ie ≥ 0` 表示 target i 的终局获胜贡献来自 e。目标为

`max Σ_(i,e) max(0, c_ie - b_i) w_ie`。

`b_i` 是当前公开六位 score 账本。每个 target 只有一条获胜边：`Σ_e w_ie ≤ 1`。对曝光 e 的 fiber f：`Σ_(i fitting e,f) w_ie ≤ x_e`。每段相邻端点间的时间片满足 `Σ_(e overlapping piece) x_e ≤ 1`。

固定整数 x 后，w 是 target 到 `(e,f)` 的二分匹配多面体；其容量都是 0/1，最优顶点为整数。因而 w 不必声明成整数，也不会将一个 fiber 分数化给两个目标。运行中检查实际返回的正 w 都等于 1。每条解码曝光按 w 回填真实 assignments，再校验时间不重叠。若一个 target 在多条真实曝光上可获不同 score，最优终局只需保留最高那条作为 science witness；其余重复 hit 对本 science-only 目标没有必要。这给出了有限候选域里共同路径与 assignment 的精确模型。

它不同于此前末夜 600 秒 beam：窗口在第 8/18 夜，曝光时长混合，目标选择直接由路径内的 fiber 匹配决定。也不同于 independent target Bellman 或 hourly required reservation：时间容量作用于整个共同曝光，未来各 target 不能同时领取不兼容的 field。相较 objective_graph 的设计，本轮给出了可运行的 sparse MILP、路径解码、独立枚举检查与真实公开前缀的短实验。

空间候选来自原 RequestCache/CPUPhase 的完整 24-anchor fixed workload，每个起点保留最多 4 个相异强 field。它限制了连续 pointing 搜索域，不能称为原问题全局最优。所有 eligible target/fiber 都重新按完整公开 catalog 几何计算；没有先逐 fiber 贪心钉死 suffix assignment。

## 全目标时间机会损失

在同一冻结共同域 D 上，`V_t(b)` 是可执行 suffix 的科学增量。首动作 a 的 score 更新为 `b' = max(b,c(a))`，直接增量 `I(a)=Σ(b'-b)`；模型值为

`J(a)=I(a)+V_(t+d)(b')`。

保留同样初始 b、同样 duration d，但首区间不产生任何 score，重新求 `V_(t+d)(b)`。于是共同时间机会损失是

`L(d)=V_t(b)-V_(t+d)(b)`。

这次重求对整个 catalog 生效，包含本次未指派目标，不能只计算 `sum tail_delta/d` 或当前 assigned targets 的未来损失。还存在 coverage 重叠代价

`R(a)=V_(t+d)(b)-V_(t+d)(b')`，因此 `J(a)-V_t(b)=I(a)-L(d)-R(a)`。

结果保存所有目标的 contribution 差与未指派目标的净差。一个目标减少、另一个增加可以互相抵消；逐目标差是路径重分配，不应全部解释成不可挽回损失。MILP 有 gap 时保存 L 的 lower/upper 区间，不把两个不完全求解的 incumbent 差当作精确损失。

同 duration 空曝光比较表示该区间被占用但无 score。它与只等待最短合法 60 秒后重新规划不同。原 600 秒格点会在首动作结束后留下人工空隙，实验出排名前改成共享起点域：0 与每个 first-duration 的结束时刻，各自再加 600 秒步长。每个分支使用完全相同的 union domain，而不是按不同首动作生成不同有利域。

## 公共信息合同与积分

历史输入使用原控制 `actions.jsonl`、公开时间/动作、公布消息，以及 observation 表的 `target_id,score` 投影视图。actor 的 Policy/terrain/calibration/feedback/ledger 只接收旧动作尚未改变之前的公开 hits。`factor, quality, prog_mult, fiber_id, valid, invalidated_by` 不作为模型输入。CSV 是含诊断字段的宿主历史文件；代码在 ingress 丢弃这些字段，并仅按前缀 observe rank 消费 score。此研究不是严格只挂载 sanitized 文件的容器隔离证明。

completion 必须承认不确定性：由 six-decimal score 得到的 raw 下界为 `(score-.5e-6)/(weight*max_program_mult)`，上界为 `(score+.5e-6)/(weight*min_program_mult)`，裁剪到 [0,1]。不能把 policy 的估计 factor 当作真实完成。本轮优化不使用任何 raw completion bit，结果记录公开区间的 guaranteed/ambiguous counts。

当前 C/E 来自旧合法公开反馈的原 estimator；不存在过去完整 wallclock snapshot，所以状态称为 reconstructed public state，不声称逐动作重现旧策略。当前 strong incumbent 在这一相同重建状态上由原 29-file source 重新选择。不同动作以后没有继续投喂旧 feedback，没有运行一条伪反事实续局。

Terrain expected-clear 先进入条件积分，再应用 cap；这不是对障碍随机变量/天气随机变量完整分布的正确期望。C/E 的三档只各自定义一个共同的 deterministic conditional future，没有校准 posterior，也没有模拟途中 feedback 后的自适应。模型中的科学值、时间价格与数值证书都限定于这个 surrogate。

每个完整曝光按公开 night anchor/900-second slot boundary 与 ≤120-second midpoint piece 积分 Moon/airmass。raw quality 的方向项来自冻结的 Terrain posterior、当前已公布 bulletin 与 forecast support；幅度只是原公开 conditional model。program band 从独立的未乘 instrument/directional 的积分计算。未来尚未发布的消息、真实天气、真实事件、真实仪器效率不参与计算。`.9/1/1.1` 是事先固定敏感性，不是校准概率，也不是实际天气情景频率。

## 固定短 gate 与实现检查

`PREDECLARATION.json` 固定四个状态：L1/L2 各第 8 和第 18 夜，取该夜开始一小时后的第一个合法 observe 状态；无 active REQ、剩余至少四小时。窗口 14400 秒，未来 duration 300/900/1800，first 保留原 strong action 的完整 duration/program/assignment，另比较同 field 的三种 duration。每个 sensitivity、每个候选，分别解共同 suffix 与同 duration 空曝光 suffix；每个 HiGHS solve 8 秒，不扩 prefix、不增加方法或 rescue 参数。

正条件：同一个非 baseline first candidate 在 `.9,1,1.1` 全部是严格 certified winner，即其可行值高于所有其余候选的 MILP upper bound。负条件：没有这种稳定变化，保留负例并停止，不以扩大搜索域补正结果。

`check_operator.py` 的 12 个 finite instances 包含相同 fiber 竞争、时间重叠、成熟 best ledger 与不同 first durations，全部与独立完整枚举一致。72 项合成恒定天气下的官方 v4 scorer/program 检查通过，最大 science 误差 `6.661338147750939e-16`。这项检查只构造 synthetic SlotTruth，不读取实际 truth。第一次 synthetic check 未按 900 秒切槽，导致 1.2e-7 的积分差；修正 synthetic fixture 后与官方网格相同，失败日志保留。

最初 public initial 缺 `grid_side`，已补公开派生参数；首次运行失败日志保留。积分最初对每个 field/program 重复计算，机械缓存 `(start,duration)` 后不改变值。出最终结果前又将静态 suffix assignment 替换为联合 fiber matching，并保留中断日志。没有使用中断的任何候选排名来选参数。

一次固定 8 秒 MILP 没有返回 incumbent，原脚本异常结束；这个真实失败在 `failed_attempt_05_no_incumbent.log`。不能把空 suffix 当作已经丢掉所有已知控制。最终初始化先在完全相同的 domain 中构造非重叠 greedy 时间路径，再对固定 x 的所有 target/fiber 边做一次精确 Hungarian matching，得到手工可执行 primal。SciPy `milp` 没有 warm-start 参数，手工 primal 在 solver 外保留；MILP 超时或未给 incumbent 时仍返回这条实际路径、实际 objective 和失败状态，8 秒预算不变。它也可以比 solver 当时的 incumbent 更好；输出标明 primal 来源。没有增加字段、时长、prefix 或敏感性参数。这个初始化是可连接生产的具体额外算子，不是重新计算独立 target 最佳未来。

## 实测结果

固定四状态全部完成。0/4 通过预声明的“同一个 overall winner 三档一致”正条件，原型不采用、不扩大样本、不启动整季。一个状态存在稳定的相对真实强候选的 pair 反转；这不是改写正条件。

| 公共状态 | 首强候选时长 | 有限 future 列数 | `.9 / 1 / 1.1` 获胜时长 | 三档 overall winner gate | 总秒数 |
|---|---:|---:|---|---|---:|
| L1 第8夜，2026-11-09 01:39:40Z | 273 | 2460 | 900 / 900 / 273 | false | 251.101 |
| L1 第18夜，2026-11-19 01:49:13Z | 2223 | 2328 | 300 / 1800 / 1800 | false | 133.022 |
| L2 第8夜，2026-11-16 01:40:51Z | 2431 | 2316 | 300 / 300 / 1800 | false | 265.325 |
| L2 第18夜，2026-11-26 02:07:17Z | 151 | 2460 | 300 / 900 / 900 | false | 254.634 |

L1 第18夜的 **1800 秒** alternative 在三档均严格胜过 **2223 秒** strong incumbent 的 upper value，因此这一相对排名变化有有限模型的数值证书：

| 质量缩放 | 原 strong 四小时 science 增量 | 1800s alternative | 实际可行值差 | alternative lower − strong upper |
|---|---:|---:|---:|---:|
| .9 | 55.251885 | 55.833028 | +0.581143 | +0.473065 |
| 1 | 69.974381 | 70.273190 | +0.298809 | +0.298809 |
| 1.1 | 76.306958 | 76.539577 | +0.232619 | +0.232619 |

真实 action diff：共同 pointing 为 `alt=58.3280019, az=134.4347379`，program 都是 DARK，仍为16 fibers。时长 `2223→1800`，fiber8 从 `V4T007086` 改为 `V4T000659`，其余15个 assignments 完全相同。两处更换目标均 `required=false`；该 field 唯一 required `V4T007732` 的 prefix 公开 best_score=.702134，考虑六位舍入与 max multiplier1.2 后 raw 下界=.58511125，已经认证完成。不能将本例称为只缩短时长的消融，也不能据此消去未来 Jain/REQ/loss 的代价。

名义模型的机会分解是：

| 项 | 原 2223s | alternative 1800s | 改变 |
|---|---:|---:|---:|
| 当前直接 science I | 9.618702 | 7.450656 | −2.168047 |
| 全目标共同时间机会损失 L | 9.917511 | 7.450656 | 释放 2.466855 |
| coverage overlap R | 0 | 0 | 0 |
| 共同路径 science J | 69.974381 | 70.273190 | +0.298809 |

原时长的空首区间重排中，未指派目标的净 contribution 差为3.057304；1800s 时为0。这个差包括路径重新分配，不能称为逐目标永久损失。它具体展示了只盯当前16目标的增量或 rate 会遗漏的机会。`.9` 下原/短时长 L 为7.381549/5.026537；`1.1` 下为10.678007/8.456621。完整逐 target contribution 与路径在 JSON 中，名义两条模型路径及完整作用动作单独摘出到 `L1_night18_stable_pair.json`。

L1 第8夜、L2 第8夜、L2 第18夜没有稳定 certified pair 反转。L2 第8夜的8秒 MILP bound 尤其松，不能解释其 primal 排名为已求得 joint optimum。未完全求解时，L/R 的两个 feasible-point 差可能出现负值，只有保存的 lower/upper 区间可描述模型最优量；不把负点差解释成负机会成本。输出保留这些负例，不以更高 solver budget 救结果。

最终108个 solver calls 里25个 optimal，0个 no-incumbent；43次手工 greedy-path+joint matching 比当时 MILP incumbent 更好，65次选 solver primal。较早一轮的 no-incumbent 失败独立保留，不能被最终0覆盖。手工 primal median/max 为 `.016143/.025366` 秒；建共同域需24.898–37.973秒，四个状态合计904.082秒。这是 Mac unrestricted 运行，默认 HiGHS thread selection，抽样最高 RSS约1.52GiB、CPU约261%；不是2CPU/2GiB/900秒 production gate，也不是精确峰值采样。

解码的1617条曝光、20357个 assignments 经过正式 FiberGrid 与全曝光 minimum-altitude 校验，零违例；使用公开校准 point estimate，没有读取实际 offset truth。四个 prefix 的重新构造公开分数总和、时点及 action-prefix hash 也一致。检查、资源与文件锁分别在 `checks.json`、`audit_summary.json`、`RESOURCE_RECEIPT.json`、`MANIFEST.json`。没有真实未来反馈、官方反事实分叉、完整季节或线上提交；上述稳定反转只属于冻结共同域的条件 science 模型。

## 接口与生产连接

`build(policy,snapshot,env,scores,factor_lower)` 直接接原 RequestCache Policy，复制 planner 与 Terrain posterior，返回 strong incumbent、首候选和共同未来列。`solve(planner,arcs,scores,factor_lower,env,scale,first,blocked_seconds,time_limit)` 返回可执行路径、全目标增量、MILP gap 和 upper bound。`run_state` 实际执行这一接口，没有修改原 29-file source。只应用获胜 first 时，生产 Policy 可沿原 pending/feedback/ledger 接口消费随后真实公开结果；本轮没有启用这个写回动作。

当前成本是重要限制：完整 strong field 生成、全目录积分、MILP 在滚动时都可能太贵；此处安装到结果目录的 SciPy 1.14.1 也不是当前 numpy-only submission 的依赖。2CPU/2GiB/900 秒门检尚未完成，不应直接塞进每次决策。后续若机制成立，可缓存 nightly common domain 并在公开 b 改变时更新 matching objective，保留 current incumbent；仍须重新核验窗口、未知 future REQ、completion posterior 与实际 wallclock。固定 assignment column、独立 best-start 或再调 urgency 不能替代这一步。
