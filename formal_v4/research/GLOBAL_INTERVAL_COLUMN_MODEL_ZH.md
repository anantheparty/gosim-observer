# 先知质量区间与全局有限列模型

研究时间：2026-10-03；只用公开配置/目标/夜历、自己的已完成输出、generation 的质量反演区间。没有读取隐藏天气，没有 GPU 或网络 choose，没有修改生产策略、服务或 Git index。

## 1. 小门检先回答了什么

第一轮云端漏掉的 required 数量是 α3、β9、γ3、δ19。用 `PublicQualityMatrix` 的官方 900 秒槽、最多 120 秒中点积分，检查公开槽起点、目标可见窗口边界、已知维修 cell 起点等有限整数秒起点，单次曝光最长 3600 秒。

| 卡 | 漏掉 | 有窄区间支持的条件单曝光见证 | 仍不能给下界达标见证 |
|---|---:|---:|---:|
| α | 3 | 3 | 0 |
| β | 9 | 5 | 4 |
| γ | 3 | 3 | 0 |
| δ | 19 | 19 | 0 |

30/34 个目标找到 factor 下界至少 .5 的曝光：全部触碰 cell 有观测支持、区间宽不超过 1e−4；整个轨迹避开参考生成域内所有可能方向遮挡；避开两轮已经发现的维修时间差窗口。这是**原有效效率/维修路径与参考几何域条件下的见证**，不保证未来改维修路径后仍成立，也不保证单独可行目标能同时放进望远镜排程。

β 的 `V4T001367 / V4T002036 / V4T004301 / V4T005798` 未找到下界 .5 见证；即便忽略方向遮挡，当前样本的最大下界 factor 也仅 .4655/.4245/.3264/.4168。已支持槽的乐观上界仍可能达到 1，因此不能说这些目标不可行：多槽量尚未识别、支持区间可能宽，有限起点采样也没有覆盖全部连续起点。没有对未支持槽插值或把 NNLS 点曲线当真值。

例如 δ 的 `V4T004230` 在 10/26 UTC 07:30 开始 3600 秒，窄区间条件质量下界约 1.3162，factor 下界 .5005；α 两个弱目标的质量下界约 1.06–1.11。**quality 不是 [0,1] 的量；只有 factor 封顶为 1。**

数值文件：`results/required_quality_interval_20261003/audit.json`。CPU 用时 3.75 秒。

## 2. 从逐目标机会进入共享时间排程

第二个 pilot 取上述每目标最强四个见证的起点/时长，枚举 16 个光纤格中心的指向，用官方球面 `FiberGrid` 精算。同一次曝光可以覆盖多个 required；同一 fiber 有冲突时只留一个目标。这里只研究原来漏掉目标的覆盖收益，不占用背景科学目标，也不包含 REQ。

| 卡 | 有限观测列 | 时间节点 | MIP 变量 | 一列最多完成 required | 联合覆盖 | MIP 值 = 此池 LP 上界 |
|---|---:|---:|---:|---:|---:|---:|
| α | 16 | 17 | 35 | 1 | 3/3 | 150 |
| β | 22 | 20 | 50 | 1 | 4/9 | 200 |
| γ | 16 | 22 | 40 | 1 | 3/3 | 150 |
| δ | 248 | 46 | 312 | 2 | 15/19 | 750 |

全部小 MIP optimal，gap=0，四次求解共约 .02 秒，含几何建列整个 pilot 小于 1 秒。δ 证明确实有一条曝光覆盖两个原漏掉目标的合法指向。

这是有限池的共享覆盖子问题：25/34 个目标可以联合安排，覆盖项毛收益 1250；它忽略这些曝光替代原排程产生的科学损失，所以**不能将 1250 当作完整分数提升**。β 的第五个独立见证在当前小池中有时间冲突；δ 未覆盖四个也可能通过其他起点解决。LP 上界只认证这个小池，不能认证完整问题。

代码：`required_quality_interval_audit.py`、`required_quality_column_pilot.py`。输出 `flow_pilot.json` 保存具体指向、分配、联合排程。

## 3. 质量与效率的正确变量

公开几何记为 \(H_i(t)=L_i(t)/X_i(t)^\beta\)。隐藏背景乘积记为 \(W_s=\tau_sK_s/seeing_s\)，有效仪器效率为 \(E_s(h)\)，其中 h 是此前 report 的历史。方向乘子/关闭记为 \(D_i(t)\)。

\[
q_{ic}(h)=\frac1{d_cq_0}\sum_{p\subset c}\Delta t_p\,H_i(t_p)W_{s(p)}E_{s(p)}(h)D_i(t_p),\qquad
g_{ic}=\min\{1,f_i d_cq_{ic}/(f_0t_0)\}.
\]

program band 另由无 E、无方向乘子的积分确定。整条列声明一个共同 program，不能为每个 target 独立挑倍率。科学贡献 \(s_{ic}=weight_i g_{ic} multiplier(program_c,band_{ic})\)。质量积分从自己的输出识别的是 \(Z_s=E_s(h_0)W_s\)，不是 W 与 E 各自。

因此有三种严格不同的模型：

1. **固定 report 历史 h₀**：使用已有 Z 区间，保留跨轮观察一致性的条件，不改变维修路径。
2. **已知有限情景**：每个情景含 W、外生故障状态和方向事件；时间 DAG 节点附仪器状态，report 是状态转换边，再按该边历史计算 E。
3. **未知新故障/天气**：不能把旧 Z 硬用于任意 report 路径。将旧曲线当先验，当前反馈更新；或做鲁棒/情景模型。不能通过任意除一个拟合 E 来宣称识别了 W。

参考 Z≤3 只在参考生成域成立；当前正式公开数据没有证明完整 hidden 域。没有合法有限 cap 时，未支持槽没有紧的质量上界，仍有 factor≤1 的无条件封顶。

## 4. 有限列的定义：模型范围先固定

列 c 包含开始/结束、实际指向、每 fiber 的唯一 target 分配、共同 program、对应状态/情景的质量积分与有效性。每列先通过官方球面玻璃几何、全曝光可见高度、时长和夜窗校验。每列最多 16 个科学 incidence。

列集不是枚举 64! 顺序：它是公开时间机会、曝光阈值、几何候选构成的 DAG 弧集。可同时放入历史整卡列（保留原解）、required 弱目标达标曝光、REQ mask 列、科学增益列。某个 column 内的 16 纤分配可以先用匹配/同纤竞争精解；不同 duration/program 形成不同列。

数据回溯失效独立于原始物理 quality。固定已知失效情景时，失效列的有效 science/required/REQ incidence 设零；不能从 valid=false 推断物理质量零。未知未来 data loss 要作为情景，不能对其确定性免责。

## 5. 时间 DAG + max 科学 + required + REQ 的整数模型

节点为列开始/结束以及 survey 边界；相邻节点加等待弧，观测列是从开始到结束的弧。令 \(x_c\in\{0,1\}\)，等待弧可用连续 [0,1] 流。单位流守恒 \(Bx=b\) 选择一条完整望远镜时间路径，自动排除重叠观测。没有其他耦合时这是可在线性时间 DAG 最长路求解的网络流。

**科学分不能简单将所有 exposure 收益相加。** 对每个目标 i，把已有 best score 和有限列可取得的不同分值排序成 \(v_{i0}<v_{i1}<\cdots<v_{iL}\)，增量为 \(\Delta v_{i\ell}\)。设二元层变量 \(z_{i\ell}\)，仅在至少一个已选有效列达到该层时开启：

\[
z_{i\ell}\le\sum_{c:s_{ic}\ge v_{i\ell}}x_c,\qquad
z_{i,\ell+1}\le z_{i\ell}.
\]

正增量目标函数使它精确表示 max，而不是累加重复曝光。已有分值作为常数与预开启层。列中没有目标 i 的 incidence 不计入。

required 完成变量 \(b_i\in\{0,1\}\) 满足

\[
b_i\le b_i^{old}+\sum_{c:g_{ic}\ge .5}x_c.
\]

REQ r 中每个 distinct target 的变量 \(u_{ri}\) 满足

\[
u_{ri}\le u_{ri}^{old}+\sum_{c:\ issued_r\le start_c,\ end_c\le deadline_r,\ g_{ic}\ge threshold_r}x_c,
\quad k_r h_r\le\sum_{i\in R_r}u_{ri},\quad h_r\in\{0,1\}.
\]

这是官方要求的**整个曝光包含在 REQ 窗口**，不是只看开始时刻。重复同 target 不能凑 quorum。

忽略/固定均匀度和 report 后，精确有限模型目标是

\[
S_{old}+\sum_{i\ell}\Delta v_{i\ell}z_{i\ell}
-50|Required|+50\sum_i b_i+\sum_r reward_r h_r+Report(h).
\]

同列覆盖多个 required、REQ、背景科学 incidence，自然只耗一次望远镜时间。绝不能为每个 REQ 列收整台望远镜的科学影子成本，也不能把该列背景科学跨列重复加分。

均匀度由所有目标的 factor≥.5 完成位形成 RA band 比例，扣 \(200(1-Jain)\)。可对完整候选排程精算；要严格 LP 上界，可将这项非负罚分直接去掉，获得明确的松弛。要纳入主问题，可对 band 完成数做分段外包/枚举可达计数，再 branch-and-bound。不能简单当作每目标固定权重而声称原模型精确。

## 6. 可计算上界与拉格朗日分解

把 x、z、b、u、h 放松到 [0,1]，上述线性模型给出**固定列集、固定/乐观情景**的 LP 上界。SciPy/HiGHS 可给 MIP 的 primal/dual gap。粗分 scientific levels 时必须向上舍入分值才能保持 upper；向下舍入可构造保守 feasible objective。

另一条不依赖巨大通用 MIP 的路线：把 target 层覆盖、required 覆盖、REQ target 覆盖约束分别加非负乘子 μ、ν、η，取拉格朗日上界。它分成：

- 一个加权时间 DAG 最长路：每列权重为其所有科学层/required/REQ incidence 的对应乘子之和；可附报告状态。
- 每目标科学层小问题：挑一个合法前缀，最大化 \(\sum_\ell(\Delta v_{i\ell}-\mu_{i\ell})z_{i\ell}\)。
- 每 required：贡献 \(\max(0,50-\nu_i)\)。
- 每 REQ：贡献 \(\max(0,reward_r-\sum_{k_r\text{ smallest}}\eta_{ri})\)，distinct 目标选 k 个最小价格。

四部分加常数即是一个可计算 upper U(μ,ν,η)。用次梯度/束方法最小化 U；保留最佳可行 primal 做 lower。重复 science 饱和已经由层变量处理，REQ quorum 有离散门槛，几何共享体现于列 incidence；这与局部排序不同，是全局耦合约束的对偶分解。

每次迭代成本约 \(O(|E|+\text{incidences}+\text{science levels}+\sum_r|R_r|\log|R_r|)\)。可先用 50k 列、最多 800k 物理 target incidence，100 次对偶迭代；不枚举所有时间顺序。science 层完全精确时可能增加覆盖 incidence，实际应压缩相同值、相邻阈值前缀并用稀疏累积实现；不能把逐层逐列全展开成平方矩阵。

## 7. 列生成与全局证明的边界

受限列池 LP upper **不是完整连续问题 upper**；历史最优 primal 是候选 lower。扩充列必须做 pricing：找 reduced cost 最大的新合法指向/时长/分配列。如果 pricing 本身只用 Phase/Beam，则只有启发式下界，不能声称遗漏列全无正 reduced cost。

要证明完整问题 upper，必须给所有未列出的连续空间/时间区域提供 reduced-cost 上界并剪枝，或建立确实覆盖所有物理动作的乐观外包列集。几何可用球面块的 fiber 可达 target 上包络，时间用质量/可见区间包络；允许 fiber 冲突或独立择 program 可给松弛 upper，但不能将它伪装成合法列。直到每个 pricing 分支 upper≤0，才能把列生成 dual 当全局证书。

无需假装有紧的完整 upper：当前 pilot 的有限 LP=MIP 明确证明了这一小池 coverage 最优，同时暴露时间冲突；它没有证明 δ 四个未覆盖目标不存在其他排程，也没有证明科学分已到顶。

## 8. 下一步优先级

1. 原 baseline 全列入池，保留可复现 incumbent；把30个条件机会目标的其他可行起点补入，先解 shared coverage+science regret，而不是单个最强质量排序。
2. REQ 全窗口 columns 与 required 列共用一张时间 DAG，同列背景科学用 max 层记账；由对偶价格反馈到几何/时长 pricing。
3. 窄区间先采用固定 report 路径模型；改变 report 的候选另外标作情景/当前 E 校准模型，不混用旧Z保证。
4. 持续记录 primal、finite LP/dual upper、遗漏列 pricing上界的区别。只在预算内增加有正 reduced-cost可能的列。

上述研究与小门检共用普通 CPU 完成。研究结果未接入现上传策略，避免在云端当前组合评测期间引入未验证变化。
