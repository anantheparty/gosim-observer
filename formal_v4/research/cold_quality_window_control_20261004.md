# 公开条件下的整季质量时间窗控制：目标 Bellman 与资源价格原型

日期：2026-10-04，Asia/Tokyo。先独立阅读正式 v4 runner/scorer/workflow/fiber，再查阅 `ALGORITHM_PORTFOLIO_ZH.md` 去重；随后阅读线上科学轨迹审计及当前最强 ZIP。只写本报告与 `results/cold_quality_window_control_20261004/`。没有 SSH、GPU、完整季节、训练或提交，没有读取 sealed L4 教师标签或真实未来 weather/events/requests。root 后续另行启动独立 CUDA 后端，属于另一任务。

**结论：目标续局价值确实能改变“谁使用当前优质长曝光窗口”，但当前全目录原型的机会模型和价格尚不允许部署。** 它保留公开 best score 与 raw 阈值概率两个维度，先合并不可区分的公开 score 再更新阈值概率；以全目录 future service demand 求 fiber 秒价格，将续局边际交给真实几何/assignment 内层。它没有预约小时、修改 urgency 常数或让未知真实天气进入 actor。公开 δ 全目录试算捕捉到 2.12 倍总资源需求，但三步固定 subgradient 过冲，最佳价格仍为零；每目标每夜独立挑最佳 start 又严重高估了服务机会。应先修正资源求价与公共未来几何的共同服务约束，再进入实际强策略分叉。

## 1. 正式问题与可见状态

正式依据是 `upstream/gosim-observer-examples/runner/challenge/{v4_scorer.py,v4_runner.py,v4_workflow.py,v4_fiber_map.py}`。

对曝光 e，

\[
 g_{ie}=\min(f_i d_e Q_{ie}/450,1),\qquad c_{ie}=w_i g_{ie}m_{ie}.
\]

`Q` 是整个曝光内 efficiency、transparency、sky、seeing、airmass、Moon、directional events 的积分，不能把曝光延长后仍当原平均 quality。program band 不含 instrument efficiency 和 directional multipliers。真实 geometry 在曝光开始分类一次、随后 tracking；整个曝光最低 altitude 必须过限，每个 fiber 只能给一个目标。曝光跨槽合法，但 runner 会在当夜结束截断。这里不存在额外公开 slew/readout 时间。

完整目标为

\[
F=\sum_i\max_{e\in\mathcal V} c_{ie}
-\sum_{i\in required}P_i1\{\max_{e\in\mathcal V}g_{ie}<\theta\}
-U(1-Jain(r)) +\sum_r R_r1\{quota_r\ reached\}+report.
\]

请求 witness 必须整段曝光位于该请求 issuance 与 deadline 之间；普通历史完成不能代替它。data loss 按 observe rank 回溯取消窗口、时间不退，还会修订已结算请求。

actor 的公开历史包含初始化 catalog/calendar/site/instrument/scoring，以及截至当前的 bulletin、forecast、请求、公开 hit score、report result、resync。未来真实天气和未来未发行请求不可见。`last_result.hits` 只有 score，没有 raw factor、真实 band 或 program 是否匹配；resync 只有新 best score 和指定失效窗口，也没有 raw factor。

因此真实终局需要两个不同纪录：science best score 与 maximum raw factor。对目标 i 定义

\[
b_i=bestScore_i/w_i\in[0,1.2],\quad Z_i=1\{maxRawFactor_i\ge\theta\},\quad
\pi_i=P(Z_i=1\mid public\ history).
\]

`b` 可由公开 score 历史及 resync 更新；`Z` 通常未知。单条未饱和 score 的无条件 factor 区间由所有合法乘子给出；DARK 的 normalized score .54 可来自匹配的 g=.45，也可来自错档的 g=.54。请求完成 target IDs 在阈值相同时可额外证实普通完成，但 loss 后必须撤回对应 witness。interval-only 情况下不得用隐藏真实 bit：可以保留 \(\pi\) 区间、在整个区间上做稳健候选门检，或由明确的公开 posterior 提供概率。

原型没有使用线上 `observations.csv` 的真实 factor。当前生产包 `best_factors` 是政策推断，不应重新命名成已知真实 factor。多次历史 score 对 C/E 的共同约束会关联各条 witness，更新 \(\pi\) 时不能擅自假设旧曝光独立。

## 2. 机制：已完成目标仍可能有高当前边际，未来易补目标当前边际可很小

若目标未来会得到最高 score M，且 M 的分布外生、与当前动作无关，当前由 b 提高到 c 的精确终局边际为

\[
E[\max(b,c,M)-\max(b,M)]=\int_b^{\max(b,c)}P(M<x)\,dx.
\]

这是一个最简单的解释，不是最终 actor：当前已知相同 science 增量，可以因未来质量窗口、月光、可见性和服务竞争不同而具有不同终局价值。阈值奖励对应“未来仍未合格”的条件概率。不能把整个低-flux 类统一加权，也不能仅用 nights-left 表达质量尾部。

下述 Bellman 将这些未来机会变成可选择的、要付资源价的观测，而非免费取得的 M；它不输出时间预约。

## 3. 原型的有限模型及诚实的信息更新

每个公共机会窗口 k，为各目标给出有限服务选择 a=(duration,program)，潜在结果 s 的 normalized science score \(c_{ikas}\)、raw factor \(g_{ikas}\) 和概率 \(p_{ks}\)。窗口内只允许一个该目标服务选择，skip 永远合法。各目标共同的 physical field coupling 暂被移除，由容量价格近似。

公共 δ pilot 使用 W=38 个夜窗口，每夜每目标至多一次，A=9 个选择（900/1800/3600 秒 × 三 program），S=3。对每个 duration，公开几何积分在 night start、可行 start 区间中点、night end-duration 三个时刻求最大值。这个 max 只使用确定的 Moon/airmass/altitude，未看潜在天气结果；但各目标可独立挑不同 start，仍是明显的服务近似。

声明的、**未校准**的三个整夜 weather 节点为 \(Z=transparency\cdot sky/seeing\in\{.38,.60,.86\}\)，E=.95，概率 {.25,.5,.25}。令

\[
H_i(u)=lunar_i(u)/(q_0\,airmass_i(u)^\beta).
\]

`q_band=Z*mean(H)`、`q_raw=E*Z*mean(H)`，再逐 target 决定 band、饱和、乘子和 score。公开积分按正式不超过120秒的 midpoint pieces 计算，整个曝光最低 altitude 精算过滤。weather 节点在 duration/program 各选择间固定，不因候选最大时长重新抽路径；同一 start 的长短曝光来自同一固定节点，避免旧 scenario bank 的前缀不一致。

未来公开观测值是 \(y=round(w_i c_{ikas},6)\)。先将给出同一 y 的潜在结果合并：

\[
\tau_{ika}(y)=P(g_{ika}\ge\theta\mid y),\quad
b'=\max(b,y/w_i),\quad \pi'=\pi+(1-\pi)\tau(y).
\]

**后一条只在旧完成状态与本次潜在结果条件独立的有限模型内成立。** 一般真实模型应使用

\[
\pi'=P(Z_{old}=1\mid y)+P(Z_{old}=0\mid y)
 P(g_{new}\ge\theta\mid Z_{old}=0,y).
\]

persistent E/fault/terrain、night AR 和过去 score 对 C/E 的约束都可能破坏独立性；本次 score 也应改变未来 C/E posterior。单独 \((b,\pi)\) 并不是完整真实 belief 的充分统计量。这是本原型明确的近似，不是已解决的辨识问题。

各目标 DP 也没有表达一条公共曝光对其他目标天气 belief 的信息收益，或共享 weather 世界的路径相关容量。全量 PMF 有共同节点标签，但独立目标策略只基于自己的 modeled score，省略了跨目标共享学习。正式未来模型需保持 `(world,time,latent)` 固定索引、完整曝光积分与正确 score 观测 likelihood，不使用未来真实世界作 actor 输入。

## 4. Bellman 与资源 dual

令 \(P_i=50\) 对 required，其他为0。省去常数 \(-\sum_iP_i\)，终值为

\[
H_{W,i}(b,\pi)=w_i b+P_i\pi.
\]

fiber 秒价格 \(\mu_k\ge0\) 下，

\[
H_{k,i}^{\mu}(b,\pi)=\max\left\{
H_{k+1,i}^{\mu}(b,\pi),\;
\max_a\left[E_sH_{k+1,i}^{\mu}(b',\pi')-\mu_kd_{ka}\right]
\right\}.
\]

选择 a 在潜在 s 揭露之前。没有用 `E[max_a ...]` 让未来真实 weather 提前可见。公开 score 合并后才转状态，score 相同的 .45/.54 raw 两世界不会被 actor 区分。

把每夜 fiber 秒容量取为 \(C_k=16\times publicNightSeconds_k\)，有限插值 MDP 的资源放松为独立目标 occupation measures 及期望约束 \(\sum_iE D_{ik}\le C_k\)。

\[
D(\mu)=\sum_iH_{0,i}^{\mu}(b_i,\pi_i)+\sum_k\mu_kC_k.
\]

它对 \(\mu\) 凸、分段线性。跟随 DP 最佳 policy 前传，得到同一模型的 expected demand；\(C-demand\) 是一个合法 subgradient，包括固定 tie 选择。在代码中更新 \(\mu\leftarrow[\mu+\eta(demand-C)]_+\)。初始 public best/\(\pi\) 可以非零，不能在中季求价时重置全0。

全 stage 价格存在安全有界域：

\[
0\le\mu_k\le M=\max_i(1.2w_i+P_i)/d_{min}.
\]

若某 stage 价格超过 M，任何目标一次观测的最大终局收益都不足支付该 stage 的最短曝光，skip 支配全部服务动作；降低到 M 不改变 H，且降低 `mu*C`。本 frozen δ 模型 M=.05782222222222222 points/fiber-second。

**只有这个声明的有限、插值 MDP 有上述 dual 结论。** 原题还有 physical field、pathwise time、共享 belief、REQ gate、Jain、rank/loss；一夜一服务选择又删除了真实行动。该 dual 不是原题上界。它也不是实际季节得分：required 常数尚未减去，Jain/REQ/report 不在其中。

初版固定 step 的三次更新已经显示过冲，禁止把非零 price 数量称为有效求价。下一步可先做参数无关的 uniform scalar \(\mu\) 二分：总最优 demand 对统一价格非增，但同价时不同 tie 可能给出 demand 区间；scalar 不表达夜间异质拥塞，只作单位与梯度检查。38维价格可用 occupation-measure LP 或 Kelley/bundle master，保留每次真实 DP 的 `(D,subgradient)` cuts，在上述 cube 内求解凸 master；不得只救随机 step。root 已将这项工作交给独立 CUDA 后端。

## 5. 当前物理几何与 unequal-duration 的接法

对固定真实 `(t,d,program,pointing)`，预测目标结果仍按完整公共 belief 积分。把原即时目标增量替换为

\[
\Delta_i=E[H_i^{\mu}(t+d,b'_i,\pi'_i)-H_i^{\mu}(t+d,b_i,\pi_i)].
\]

在相同 d 的比较中，所有未指派目标和未来容量的基线项相同；固定 pointing 上每个真实 glass fiber 取最大正 \(\Delta_i\) 是正确的 separable 内层。native geometry 可使用 \(\Delta_i\) 生成当前 pointing，再用既有精算器重分类全部 sent assignments。保留原强策略候选，不能用新粗池替换它。

**不同 d 不能只比较 `sum Delta/d`。** 若未来 surrogate 为

\[
\widetilde V(t,s)=\sum_iH_i^{\mu}(t,s_i)+\sum_k\mu_k C_k(t),
\]

候选的变化包含

\[
\sum_{i\in assigned}\Delta_i
+\sum_{all\ i}[H_i(t+d,s_i)-H_i(t,s_i)]
-\int_t^{t+d}16\mu(u)\,du.
\]

第二项是所有目标在该时段失去的机会，第三项是流逝的公共容量。省略它们容易重复时间收费或免费消耗别人的好窗口。本 W38 模型没有任意 `(t+d)` 的同夜细粒度续局，**因此不能直接替换生产 `_evaluate` 的 duration 排名**。先用原 baseline duration 做 field/assignment 分叉，真正改变谁获得该窗口；duration 控制需要同夜 local event-time DAG，曝光弧跨时间节点，后接粗未来夜 suffix。局部 DAG 必须包含真实起点、night tail、altitude/threshold/program 边界，不能回到不可执行小时承诺。

Jain 的边际可以为负，不能无条件塞入所有目标同号 bonus。活动 REQ 继续原 exact quota/mask DP：仅替换科学 opportunity cost 的估计，不把 quorum reward 加到每个 target，也不把普通 \(\pi_i\) 当 request-window witness。未知未来请求保持未知。

本 target tail 暂未纳入新的 loss。原全 ledger、observe rank、窗口 witness、terrain/pointing belief 与 report 逻辑都保留；每次 resync 从有效公开记录重建 science best 与 threshold belief。最终 teacher/部署验收仍使用官方整体 fitness，不能用独立目标 surrogate 宣称总分改善。

## 6. 实际核验与公开全目录 pilot

### 短官方几何/score 机制核验

`run_checks.py` 创建两个真实16-fiber fields，duration1800秒，当前一东一西，四小时后西方 targets 已不合 altitude。未来 alt/az 网格 roll 改变，32个候选全部重新分类，最后只保留12个 distinct fibers 的实际 glass hits，没有假设未来仍16 hit。

| 有限合法两阶段问题 | 西方稀缺 field | 东方可重复 field |
|---|---:|---:|
| 当前官方 science | 10.806076369 | 18.445234101 |
| 对同一合法 future field 的续局边际 | 10.806076369 | 4.610992799 |
| 当前选该 field，再执行同一 future action 的 science | 24.980731115 | 18.785647544 |

science-only 当前排名反转，有限真实两步差6.195083570。它是给定 artificial deterministic future 的机制检查，既不是正式未知未来 actor 实分，也不是战胜当前生产策略的实验。当前32个 hit 和未来12个 hit 都按正式 geometry/filter/scorer 核验。

另两个人工官方 weather 世界在同一合法 target、同一 duration、声明 DARK 下给出同一个公开 score `.540000`：q-band .8、E .46875 得 g .45；q-band .5、E .9 得 g .54。先验各半时 observation 后 `tau=.5`，旧 completion prior .2 更新为 .6，不能变成1。这个碰撞实测检查防止把 score 当 raw factor。

100个两-stage有限模型与独立递归枚举最大误差4.44e-16；expected-demand 与有限差分价格导数最大差1.31e-7。这验证所声明算子，未验证完整天气 POMDP。记录在 `checks.json`。

### 公开 δ 全目录资源与复杂度

全目录9400 targets、564 required、38夜，仅读 public catalog/calendar 和评分/仪器配置。没有 future truth。

| 项 | 实测 |
|---|---:|
| 当前 tensor `[W,A,S,N]` | `[38,9,3,9400]` |
| CPU grid `[N,B,Pi]` | `[9400,13,5]` |
| public geometry 构建 | 5.028633秒 |
| geometry+3 Bellman/forward price iterations | 56.116722秒 |
| Mac peak RSS | 472,793,088 bytes |
| 零价 expected fiber-second demand | 36,044,994.353 |
| public total fiber-second capacity | 16,977,600 |
| 零价最大单夜 demand/capacity | 20.523711 |
| 三次有限 dual | 38279.293220 / 49912.823374 / 55869.970502 |
| 保留最低 dual 的价格 | 全0 |

价格把需求搬到其他夜，第二/三次峰值甚至升至24.79/25.60，证明这个随机固定步长未解决凸求价，不能采用。

“required 可达夜数”是**任意一个声明 latent 节点、任意该 target 独立选择的三个公共 starts，达到阈值的夜数**，不是被实际策略服务的概率。564个 required 中2个在所有节点都不达阈值，其余绝大多数38夜都存在可达节点。节点 probabilities 的逐夜相加也不是“真实可保证机会”。它忽略同期其他 targets 的共用 pointing/program/duration、未知效能变化和天气跨夜相关，恰好暴露为什么简单 future-nights/quality-max 不足。2个不可达也只针对这个有限 PMF/start 集合，不能证明原题不可行。

审计中的25个线上 missing 全为QSO、其中14个在其已实现最好 q 下3600秒仍不足阈值，这是选择过的历史诊断；本 pilot 没有借它补入未选择的真实好天气，更没有由 δ science 差739断言所有低flux目标必须加权。

## 7. 冻结算子、内存与 PRO6000 batch 计划

`window_control.py` 已冻结 SHA256：

`11c7092a99dcb407a6eaa33a18ee179381f810f2066d3bf948bc94798a7e1edd`

接口为

```python
OutcomeModel(normalized_score[W,A,S,N], raw_factor[W,A,S,N],
             probabilities[W,S], durations[W,A], weights[N],
             required_bonus[N], threshold=.5)
solve(model, prices[W], score_bins=B, probability_bins=Pi,
      keep_suffix=False, keep_policy=True)
expected_demand(model, solved, normalized_best=None, completed_probability=None)
query(value[N,B,Pi], normalized_best[N], completed_probability[N], b_grid, pi_grid)
```

原型使用 uniform grids、bilinear interpolation、四次 gather。它可精确解释成更新后按 bilinear weights 随机投影到相邻 grid state、且下一阶段可见投影结果的有限 MDP。它不是精确 continuous belief DP；真实 posterior 没有这枚随机币。相同插值用于 backward、初始 public state 和 forward demand，因此有限模型的 dual 与 demand 一致。不得把插值误差省略成原题最优证明。

Bellman 时间 O(W A S N B Pi)，public score-grouping O(W A S² N)，forward 按实际非零 state occupancy 稀疏 scatter。模型 score/raw tensors 为float32；weight/probability/rolling values 在 NumPy reference 中为float64。raw 临近 .5、program 临近 band boundary、six-decimal score 分组都要重点核验：GPU不能先用不同 precision 产生不同 observable groups，再把误差当普通 tolerances。float32 suffix 是部署缓存近似，不是本 CPU reference 的精确值。

首轮 PRO6000 全δ建议固定 `[W,A,S,N,B,Pi]=[38,9,3,9400,25,9]`。两份 outcome tensors共77,155,200 bytes；一个rolling float64 value16,920,000 bytes；uint8 policy80,370,000 bytes；全部 `(W+1)` float32 suffix329,940,000 bytes。torch 后端可 batch `(action,outcome,target)` gather/reduce 与前传 scatter；实现 rolling value 即可，不应先构造全部 action×state×time 六维大张量。full suffix只在需要 actor查询时保存。

`delta_public_model.npz` SHA：

`1d95a0a37b8ff88a9cb27768928773145d0cdb25b4f908555697e186e769c178`

128目标、完整38夜、B25/Pi9、非零 current public-state/非零 prices 的 CPU gate在 `delta_subset_cpu_reference.npz`，SHA：

`fc5539bb17ba37ba4b874ca51b2e777244ca7d987f70e8e1de3b406424f7de13`

保存完整 value、policy、expected demand、grids 和 selected indices。root 的独立 CUDA agent 收到 schema/冻结hash，先一致性核验再做全δ `mu=0` 与 convex-dual 诊断。本代理没有运行或声称GPU结果。

生产2CPU/2GB/900秒的关键限制是更新时间，不只是一次表大小。best-score变化只查询固定 tail，不要求重建 DP。新公开 forecast 若只影响接下来几夜，可以用缓存的更远 suffix，仅重算到最早受影响窗口；全季 terrain/E posterior变化会影响更远窗口，需明确刷新预算。不能每次观测重新做完整38夜全目录价格迭代。当前56秒Mac结果也不能当受限Linux的部署耗时。

## 8. 真正强基线的准入实验

当前控制源是 `/Users/kamico/Downloads/observer_request_exact_cache.zip`，SHA `e55becb74bbf2a707aeb893fb054a857610312c81d815181a28bfcf5e5ff092a`。本次逐项验证 integration `control_package` 的29个成员与 ZIP 全部相同；见 `FROZEN_MODEL_RECEIPT.json`。root 正在完成 native geometry + Terrain + REQ 强组合门检。本路线应对冻结后的真实强组合，而不是28目标玩具、coarse greedy或已经失败的预约策略。

预声明顺序：

1. **数据与算子 gate**：GPU/CPU latent grouping、π更新、value、policy、demand逐项匹配；uniform μ需求非增、finite-dual cut一致。完整公共初始化与 old source 至少保留一条 exact parity。只在 fixed workload/source 完全一致后解释效果。
2. **公共机会服务 gate**：保留 native强候选，固定baseline duration/program，比较真实 current geometry 的 field/assignment。未来必须由共同物理 exposure columns 或公开可执行的 local DAG联系目标，不能每target独立把最佳夜/最佳start全数领走。先证明至少一个真实public prefix发生稳定排名反转、且差不由未知 raw bit或重复时间价造成。没有合格点就停止，不开整季。
3. **真正重新规划分叉**：冻结L1/L2或公开练习源上的少量 early/mid/late prefixes，至少涵盖低flux required 尚未知完成、成熟best ledger与活动REQ。每分叉从相同公开历史，发出真实候选后重规划到终局；标签使用science/required/Jain/REQ/report/loss全项，保留负例与tie。不可用固定旧tape的删重叠差冒充重新规划，也不读取sealed L4救参数。
4. **通道消融与完整季节**：固定equal-duration的target机会重分配与额外duration控制分开核验机制，但最终组合的比较仍是相同源、相同2CPU/2GB/900秒预算的完整强策略。记录是否完整survey_complete、实际actor耗时、source hash、新作用动作数量与所有分项。当前online α/β已有wallclock截断，新增DP必须先满足预算，不能拿少跑季节的分差解释算法。
5. **正式采用**：在上述强对照与deploy gate成立后才评测真实新包，报告完整官方批次。synthetic +6.195、finite dual降低、CUDA速度和surrogate排序均不能提前称提分。

若先做学习，PRO6000应学习全catalog service竞争/价格或目标tail，保持真实 geometry精算及window-aware REQ。新标签必须来自重规划的公共前缀、多独立world和不同长期质量服务模式；不能重复已失败的同一critic教师只增加步数。

## 9. 本轮保留与拒绝

保留：双 score/threshold-belief 状态，按公开score分组的未来观测模型，有限Bellman+可核验expected-demand算子，严格当前/未来geometry关联的排名反转，以及完整公开全目录的尺寸/资源诊断。

拒绝直接使用：三步固定subgradient的价格、每target每夜独立best-start机会数、忽略completion/weather关联的posterior作为真实概率，以及只有 `sum tail_delta/d` 的跨duration控制。没有本轮真实季节增益；这不否定质量时间窗/dual/Bellman族。下一步已具体落到convex资源求价与共同物理future-service模型，root可在冻结算子上继续，而不是重新调urgency。

全部脚本和结果位于 `results/cold_quality_window_control_20261004/`：`window_control.py`、`public_pilot.py`、`run_checks.py`、`freeze_public_model.py`、`checks.json`、`delta_public_pilot.json`、`delta_public_targets.csv`、两份NPZ及`FROZEN_MODEL_RECEIPT.json`。
