# 稳定价格与全季整数路径重建：固定公共图试验

## 1. 范围与预声明

本轮在既有 `season_pattern_controller_20261004/time_dp/L2_night08/SHARED_PUBLIC_GRAPH.npz` 上研究新组合搜索机制。复用 8600 个目标、3709602 个动作和 12845824 条共享几何边，不重建、不扩大候选域、不读取 hidden future、封存 L4 或旧 NN test。原目录、原 controller 和 closure 负结论不修改。本轮不执行正式 actor、完整季节回放或提交。

冻结总预算 **480 秒 wall**，单 BLAS 线程；记录 CPU 秒与峰 RSS。先对旧 57 条共同路径作全局匹配，随后最多 240 秒近端 bundle（每个既有首动作分支最多 200 次 oracle，共最多 600 次完整图扫描），最多 150 秒连续夜块重建（四个固定 sweep）。留出末尾完整验证和输出时间。先源锁与 root 私有备份，再运行完整图；目前只完成小型合同核验，真实图结果待填。

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

仅加载合成小图，尚未加载实际图。`CONTRACTS.json` 已通过：

- 30 个小固定路径与完整 max-ledger 穷举一致；
- 贪心 10、全局匹配 19 的最小例精确复现；
- 空曝光时间保留；
- 15 个 cut-simplex prox 与直接 epigraph QP 一致，最大 objective 差 **5.8190671503588476e−8**；
- 跨块曝光整条移除与外账本构造一致。

本机依赖使用既有缓存，无安装：Python 3.12.14、NumPy 2.4.4、SciPy 1.17.0、macOS arm64；新本机 native 动态库已编译。root 大计算应在独立目录用 Linux native 编译，优先 Rhodes CPU，2CPU/2GiB，BLAS=1；实际环境与 RSS 会随 RESULT 记录，不能把本机成本冒称正式 runner 成本。

## 7. 重要的固定图局限

未来起点每 3600 秒一格，时长只有 900/1800/3600 秒。900 秒动作结束到下一个起点可能有 **2700 秒**无法选择任何新动作；实际强 actor 可选择约 151 秒等更短曝光。该有限域会系统改变短曝光吞吐与时间机会成本。本轮不扩大域或线性复制 factor 到虚构时间节点，正/负代理结果均不能代表完整正式动作域的策略优劣。

此外，public reconstructed ledger 不主张与原 actor 内部历史状态逐动作相同；未来 C/E、terrain、forecast 与 band 系数冻结；未来天气及事件并未由该图提供真实情景路径。即使发现更高的确定路径，转生产前仍须另行解决完整公开动作域、短曝光能力、随机 Emax、observe-rank loss、REQ/required/Jain 与闭环实际环境。

## 8. 实际固定图结果

待 root 完成源锁审查和私有备份后运行预声明预算。尚无真实图 winner 或提分结论。
