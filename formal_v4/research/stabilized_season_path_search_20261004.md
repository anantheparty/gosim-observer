# 稳定价格与全季整数路径重建：固定公共图试验

## 1. 范围与预声明

本轮在既有 `season_pattern_controller_20261004/time_dp/L2_night08/SHARED_PUBLIC_GRAPH.npz` 上研究新组合搜索机制。复用 8600 个目标、3709602 个动作和 12845824 条共享几何边，不重建、不扩大候选域、不读取 hidden future、封存 L4 或旧 NN test。原目录、原 controller 和 closure 负结论不修改。本轮不执行正式 actor、完整季节回放或提交。

冻结总预算 **480 秒 wall**，单 BLAS 线程；记录 CPU 秒与峰 RSS。先对旧 57 条共同路径作全局匹配，随后最多 240 秒近端 bundle（每个既有首动作分支最多 200 次 oracle，共最多 600 次完整图扫描），最多 150 秒连续夜块重建（四个固定 sweep）。留出末尾完整验证和输出时间。已在 root 源锁审查和私有备份后执行，但实际 v2 于 **21.13 秒**因日志键冲突退出，只有部分近端迭代，未完成预算或夜块重建。用户随后明确停止新试验、收尾思考，故不重启。以下真实结果严格标为 partial。

该量是**冻结确定物理系数下的 science 增量代理**。REQ、required、Jain、report、未来 data loss、实际闭环天气与未来信息更新均不在目标中。当前公开 snapshot 无活动 REQ，不能据此声称正式多目标策略提升。

## 2. 从官方最高分账本到固定模型

官方 `v4_scorer.py:390–401` 先饱和 factor，再乘 science weight 与 program multiplier。`BestLedger.best:443–452` 只在 valid 条目中按 score 取最高值；`max_factors:454–460` 是另一账本。因而本轮固定系数记为

\[
c_{ie}=w_i F_{ie}m_{ie},\quad
g_{ie}=(c_{ie}-B_i)_+,
\quad V(P)=\sum_i\left[\max\{B_i,\max_{e\in P:i\text{ assigned}}c_{ie}\}-B_i\right].
\]

先固定三个已保存首动作 `B/priced0/priced1`，使用它们已有的 `first_ledger` 与真实时长（B 为 2431 秒，另外两个 3600 秒）。后续路径必须在首动作结束以后开始。历史 ledger、首动作系数和图的所有公共来源文件逐字节 SHA 锁定，不重新拟合系数。

对于一个确定路径，目标多次指派仅最高 score 有效。留下最高条目、删除其余条目的指派，保持每个曝光的完整时间区间，收益不变且不会增加纤维占用。因此 future target≤1 是这一确定模型的等价化简。不能迁移为随机期望 max 模型的容量限制，也不能迁移为具有 observe-rank data loss 的正式控制动作删除。

## 3. 固定路径的精确全局分配与归因

资源节点是每个 `(exposure,fiber)`，目标节点容量为一。可行边的权重为 `(c_ie−B_i)_+`。每个资源增加自己的 dummy，所有边加常数 1；满匹配选择固定数目的边，故常数不改变优化目标，dummy 允许资源空置。稀疏 LAPJVsp 求得该路径的精确 science max-ledger。

所有空指派曝光仍保留在输出路径与 schedule 中，完整时间容量仍验证。对于本固定路径，这一求解器至少不差于旧 chronological fiber greedy，因为旧解可删除弱重复条目而嵌入匹配。跨曝光匹配已见于 `cold_population_search_20261004`、`cold_common_exposure_control_20261004` 与 `STOCHASTIC_PATTERN_MODEL_ZH.md §8`，**不是本轮的新发明**。

报告分三层：

1. 原共同池 chronological incumbent：**1536.8405728322216**；
2. 同一旧 57 路径池改为全局匹配后的 incumbent：纯分配器贡献；
3. 所有新路径也加入同一池、所有三个首动作分支都全局匹配后的 incumbent：新增搜索路径贡献。

不以分支各自 LP 下界或上界制造 first-action winner。近端价格路径和每个夜块重建路径，即使生成分支上没有改善，也提供给所有首动作分支。共同池只在三个分支全部重估后提交。

## 4. 新机制一：低维近端 bundle 稳定价格

确定模型放松 target≤1，保留完整时间路径与 fiber 约束。对非负目标价格 σ：

\[
D(\sigma)=\sum_i\sigma_i+
\max_{P\text{ nonoverlap}}\sum_{e\in P}\sum_f
\max\{0,\max_{i\in(e,f)}(g_{ie}-\sigma_i)\}.
\]

每轮 native oracle 重新扫描全部 allowed 动作，按当轮价格压缩相同区间，再作精确 interval DP。同一区间的 field/program 替代不会永久删除。具体 oracle 指派给出计数 `n_i` 与 raw gain `r`：

\[
D(\sigma)=\mathbf1^T\sigma+r-n^T\sigma,
\quad \partial D=\mathbf1-n.
\]

这也是有效 cut `θ≥r−nᵀσ`。安全盒 `0≤σ_i≤g_i^max`；超过盒上界时目标的所有 reduced gains 已非正，裁回不会增大 D。

旧 Kelley master 经常跳到远处价格。本轮以中心 `c`、近端尺度 `t` 解

\[
\min_{0\le\sigma\le m}\mathbf1^T\sigma+
\max_j(r_j-n_j^T\sigma)+\frac{\|\sigma-c\|^2}{2t}.
\]

令 cut 权重 `λ≥0,1ᵀλ=1`，记 `d=1−Nᵀλ`，则盒内价格可解析消去：

\[
\sigma(\lambda)=\operatorname{clip}(c-td,0,m),
\quad \Phi(\lambda)=\lambda^Tr+d^T\sigma(\lambda)
+\frac{\|\sigma(\lambda)-c\|^2}{2t}.
\]

最大化该凹函数只需至多 **64 个 λ 变量**，其梯度是 `r−Nσ(λ)`。不建立 8600×8600 Hessian，不再求旧未稳定 Kelley LP。QP 未充分收敛时仅把它当价格 trial；每轮记录近端 primal−dual gap，并通过真实完整图 oracle 重算 D，不以数值成功标记代替完整检查。

价格中心采用明确 serious/null steps：实际 D 降幅至少达到模型预测降幅的 20% 才更新中心；较好 serious step 把 t 乘 1.5；连续六个 null step 把 t 减半。t 被限制在初始尺度的 `[1/16,16]`。初始尺度为 `||gmax||₂/max(1,||1−n||₂)`。保留中心 exact cut、empty-path cut、最近 cuts 与旧 cuts 的凸组合；聚合 cut 仍是有效下支持。所有真实 D 上界及最高整数 incumbent 分开保留。有限预算、截断 bundle 与 LP/IP gap 均不允许宣称全局收敛或全局最优。

## 5. 新机制二：路径外账本驱动的连续夜块重建

固定一段一/二/四个连续夜晚，将与块边界交叉的曝光整条移除。只保留完全在块外的 incumbent 指派，以这些条目的实际最高 score 和 first ledger 得到 `B_out`。用 `B_out` 对块内完整固定图作 interval DP：零价格与稳定中心价格在固定 sweep 间交替。

局部 DP 的加性 gain 仍可能重复计入同一目标，所以它只是候选生成器。合并块外路径与替代块内路径后，必须对**整条季节路径**重新作精确全局匹配，重新计算完整 max-ledger。首动作分支的 incumbent 只随这一真实固定模型整数收益增加。任何生成路径都进入共同池供全部分支同等重估。

此机制改变整段夜块的 field/program/duration/target 组合，且用块外已经得到的最高分消除局部重复价值。它不是原 Kelley 增加几轮，也不是只收紧一个宽上界。旧 truth LNS 和既有 fixed-path matching 是相关路线；本轮的新组合是公开固定图、稳定价格候选、外部最高分账本重建和严格共同路径池。

## 6. 小合同与环境

源锁前仅加载合成小图。`CONTRACTS.json` 已通过：

- 30 个小固定路径与完整 max-ledger 穷举一致；
- 贪心 10、全局匹配 19 的最小例精确复现；
- 空曝光时间保留；
- 15 个 cut-simplex prox 与直接 epigraph QP 一致，最大 objective 差 **5.8190671503588476e−8**；
- 跨块曝光整条移除与外账本构造一致。

本机依赖使用既有缓存，无安装：Python 3.12.14、NumPy 2.4.4、SciPy 1.17.0、macOS arm64；新本机 native 动态库已编译。root 批准本次实际机制试验使用此 Mac 环境，BLAS=1；实际环境、CPU 秒和峰 RSS 已随 RESULT 记录，不能冒称 2CPU Linux 正式 runner 成本。

## 7. 重要的固定图局限

未来起点每 3600 秒一格，时长只有 900/1800/3600 秒。900 秒动作结束到下一个起点可能有 **2700 秒**无法选择任何新动作；实际强 actor 可选择约 151 秒等更短曝光。该有限域会系统改变短曝光吞吐与时间机会成本。本轮不扩大域或线性复制 factor 到虚构时间节点，正/负代理结果均不能代表完整正式动作域的策略优劣。

此外，public reconstructed ledger 不主张与原 actor 内部历史状态逐动作相同；未来 C/E、terrain、forecast 与 band 系数冻结；未来天气及事件并未由该图提供真实情景路径。即使发现更高的确定路径，转生产前仍须另行解决完整公开动作域、短曝光能力、随机 Emax、observe-rank loss、REQ/required/Jain 与闭环实际环境。

## 8. 实际固定图结果

### 8.1 两项机械失败与来源保留

v1 源锁 SHA `867c33fb27c164f73ccc28ee33138a8cf8914c78ee1b851a2d48ba6aee537032`，root 已私有备份 HEAD `71ea44702794244f37db9f4c21c4c2cf8ff052c6`。v1 首条真实图路径匹配即因 `k*nf + uint8_fiber` 在资源编号 256 溢出，实际 `time.perf_counter` 0.894542 秒、CPU 0.227102 秒、峰 RSS 361250816 B，没有近端 oracle 轮次。原 source/lock/launch/RESULT 保留。

v2 独立 `fixed_graph_v2.py` 仅把 fiber 转为 int64 再计算资源编号，独立 `run_search_v2.py` 仅改变其 import。score/model/prox/预算均未改。源锁 SHA `a9ec06c0c6adb37d1094ae5de4a4af83c7130a315c2db5d0fb68cfaa1f645565`，root 备份 HEAD `f5d9cc891bf7aa9e79db6196753165c96ceacac4` 后启动。

新增单项 uint8 回归覆盖 17 个曝光、fiber 0/15、资源编号 256/271：旧版 OverflowError 可复现；v2 非空匹配 science gain=34、全空 gain=0，两种情况都完整保留 17 个曝光时间，纤维与最高账本检查通过。该测试没有读真实图。此前一次 `.264 秒`的 uint8 toy 小合同复跑亦原样保留，没有抹去。

v2 在 B 第 20 轮写进度日志时失败：`dict(event='prox',seconds=total,**row)` 中 row 已有单轮 `seconds`，产生重复 keyword。故状态是 **error/partial**。日志键改名为 `elapsed_seconds` 的 v3 draft、独立 log-contract 与新锁已在暂停消息前保存，**从未执行**；没有调参、增加域或继续搜索。

### 8.2 已保存的真实确定模型数值

所有数字来自实际 `RESULT.json` 和 `INCUMBENT_TRACE.json`，不是宽松上界。旧共同池和新共同池都对三种既有首动作使用相同的完整路径池与精确全局匹配，目标始终是同一冻结系数/历史 ledger 下的最高 score 增量。

| 固定首动作分支 | 原旧57池 chronological | 旧57池全局匹配 | partial 新共同池 | 新路径贡献（相对同分配器旧57） |
|---|---:|---:|---:|---:|
| B | 1536.840572832222 | 1565.916932829288 | **2252.838948943948** | **+686.922016114660** |
| priced0 | 1515.062431570760 | 1544.130304748807 | 2237.947912362796 | +693.817607613990 |
| priced1 | 1515.593944751741 | 1544.130304748807 | 2239.122828062094 | +694.992523313287 |

纯分配器对当前最佳 B 的贡献为 **+29.076359997066**；新增稳定价格路径相对同分配器最佳旧池的 partial 增量为 **+686.922016114660**；二者之和相对原 chronological incumbent 为 **+715.998376111726**。不能将后者全归因价格，也不能将任何代理增量当正式 science 提分。

共同池从旧 **57** 条变为 **114** 条，新增 **57** 条唯一完整路径。实际近端轮次为 B=20、priced0=19、priced1=19，共 58 次 oracle；一条生成路径重复，没有增加池大小。共同池新增来源分别为 20/19/18 条。最后改善来自 B 第20轮生成路径，已同时提供给三个首动作分支；partial 最佳仍是 B。

### 8.3 成本、未完成检查与停止状态

v2 `RESULT` 记录 `time.perf_counter`=**21.130014459137 秒**、CPU=**20.936338 秒**、峰 RSS=**467025920 B**，单线程。launch UTC 为 `2026-10-04T08:34:56.287002+00:00`；source-after receipt 的 exit UTC 为 `2026-10-04T08:50:43.513513+00:00`。UTC 间隔与进程 perf-counter 不同，两者原始保留，不把本机该计时解释成正式成本。

旧57池三种全局匹配 BASELINE_MATCHED 完整 schedule/ledger 已保存。新 partial incumbent 的数值、路径共同池与 provenance 已保存，但进度日志异常发生于最终 `BEST_*.json` 与完整最终 schedule validator 之前，**新 incumbent 没有保存其完整 assignment schedule，也没有执行独立最终 schedule audit**。不能称该部分结果已完成完整真实控制审查，更不能称正式策略部署成功。纯 post-run `audit_actual.py` 已写，但因停止指示没有执行。连续夜块重建未进入，不能为该机制声称任何实际收益。

SOURCE_AFTER_V2 确认全部 15 个锁定文件仍逐字节一致；v1 源/锁同样保留不变。只读 `ps -p 62930,64389` 未返回进程，两条 owned exec session 均已 exit1，**没有剩余本任务计算进程**。遵循用户「提交一下然后收尾，写报告，我思考一下再继续」的最新指示，停止本研究，不运行 v3、不续预算、不加搜索或救参数。正式最强包与 closure 负结果不变；提交与全局 goal/heartbeat 由 root 处理。
