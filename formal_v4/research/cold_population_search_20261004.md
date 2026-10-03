# 跨曝光增广匹配：独立假设与最小门检

锁定时间：2026-10-04；源码先读正式 examples 的 v4_runner、v4_scorer、v4_fiber_map，再读固定 e01939d0 生成器的 catalog/weather/score/fiber 契约。未读隐藏 L4 标签，未从真实未来 weather 建立 actor 特征。

## 预声明机制

把一段已固定的曝光时刻、指向、duration、program 看作资源节点 `(exposure, fiber)`。对所有公开目标作正式几何分类及整段最低高度检查；合法目标与资源连边。边权为条件模型下的 science improvement，加首次 required factor 达标奖励。逐曝光最大边际会提前消耗一个目标，使较晚资源没有替代；增广路径可以同时把多个目标改派，捕捉 Hall 资源争用。

这里选择改变跨曝光 assignment，而非增大 pointing 池、GA 种群或训练步数。先用最小加权匹配原型判断，再决定是否值得在群体排程的内层使用。

预声明实验只用公开 L1/L2 的目录与夜历。在生成器公开 nominal 参数构成的明确条件世界中，由冻结强 native 原策略闭环生成固定时刻/视场/程序/时长。对同一完整资源图比较原指派、逐曝光贪心和跨曝光匹配；保留原指派，最终按正式 science、required、Jain 全项条件结算择优。两个首夜各四个预定 1800 秒区间（夜开始后 0、7200、14400、21600 秒），每个区间零历史起步；不调参、不使用 L3/L4。

条件模型只是机制门检：没有真实隐藏未来天气、REQ 或 loss，不能宣称真实整季提升、全局最优或上线收益。所有文件限于本报告与 `results/cold_population_search_20261004/`。

## 适用条件（待代码核验）

- 单纯 science max 的精确化简：在固定 surviving resource 集上，每个目标最多保留一条最高 score 边，其他边可删且资源释放不使 science 降低。已有 best score 只把边权改成正部。
- required 同 science 合并还需要 target 内 witness 对齐，或明确限制每目标最多一次未来指派。不同 program 的 multiplier 会使高 score 与高 factor 分离，不能无条件把 factor completion 写进同一容量 1 边权。
- Jain 是 RA 完成计数的非分离函数；线性匹配不精确包含。必须保留原解并用完整官方结算核对。
- REQ 需要曝光整个区间落在请求 window；k-of-n reward 是 quota gate。未到 quota 的单边不能分摊出等价奖励。本微实验没有请求，不对一般请求作 flow 等价声称。
- observe rank/data loss 只有在所有时刻、duration、observe 数和顺序固定，且 surviving rank 集已固定时才是常量。真实 online 未来触发 N 未知，匹配结果不能预知存活集。

## 查重记录

独立选定增广匹配机制后才阅读 `ALGORITHM_PORTFOLIO_ZH.md`。旧 required 预约改变一小时资源块与科学曝光时间；旧 horizon contention 在末夜固定 600 秒弧做单 fiber 替代与有限 beam。当前机制保留强原策略完整物理时序、对所有 fiber 联合形成显式跨曝光匹配。它仍属于有限前瞻 family，微实验若无胜点即停止，不凭名称宣称新策略家族。

## 形式化结果

令资源集合为 R，目标为 I，边 `(r,i)` 的条件 score、factor 分别为 `c_ri, g_ri`。公开历史 best score 为 `b_i`，raw factor 为 `h_i`。固定 surviving rank 集后，单独科学增量为

`Σ_i max(0, max_{r selected for i} c_ri - b_i)`。

每个目标留下达到最高 score 的一条边即可保留全部 science，且只释放资源。因此在完整固定 field 图上，science 精确等价于最大权二部匹配，边权 `max(0,c_ri-b_i)`；零收益边允许不选。此等价没有把曝光分成独立目标时间槽，所有 fiber 的 field、时刻、program 和 duration 已先固定。

如果某个尚未完成 required 的目标满足**所有** qualifying 边的 score 均不低于**所有** nonqualifying 边的 score，则任何已选边集都能留下同时保留 science max 和 required completion 的一条边。此时将该边权再加 `P_req * [g_ri>=threshold]` 精确包含 required；完成已知则 bonus 为零。否则容量 1 只是 restricted 下界，不能保留两个不同 witness。官方 BestLedger 的反例为 `(g,c)=(0.49,0.588)` 与 `(0.53,0.5618)`，分别采用 1.2 和 1.06 的 program multiplier：两次同时保留 science 0.588 与 completion，最好单次只有 0.5618，丢失 0.0262。不是每目标 best score 对应的 factor 都等于 max raw factor。

8 个冻结图对全部目标检查上述 score/factor 对齐，违例为零；因此本次 flow 精确最大化条件 science+required，而未精确最大化 Jain。REQ、报告与 loss 不存在于这 8 个声明条件世界。若放入真实 actor，必须按已发布请求逐 window 建 witness、保留 k-of-n gate，且只有固定 survive rank 才能复用这个等价；未知未来 loss 不能当已知常量。曝光 duration 若改变也会移动以后时刻，当前资源图随即失效。

## 最小原型与实际结果

原型只读公开 catalog、footprint、夜历、公开 config。用未修改的冻结 READY native 源在明确 nominal 世界闭环生成 1800 秒物理骨架：seeing=1.10、transparency=0.88、sky=1.00、efficiency=0.95；初始公告为空、无请求/事件/失效。这是合成条件公开局面，不是实际卡的真实夜间天气或真实前缀。强控制 actor 接收的仍然只有六位公开 score，未收到真实 factor；候选图的 factor 与 score 均由该声明模型下的官方 scorer 计算。

固定同一物理骨架，枚举全部公开目标的 fiber 合法边，比较：强 native 原指派、同图逐曝光贪心、容量 1 最大权匹配、匹配后的空资源 refill。原指派始终保留；最终按官方 science、required、Jain 全项条件结算选择。不是同一完整赛季的 online 对照：改变 assignment 后没有让未来强策略再次规划。

|卡/夜开始后秒|曝光数|合法边数|flow 比同图贪心的 science 差|flow 比同图贪心的完整条件差|首曝光新指派|
|---|---:|---:|---:|---:|---:|
|L1/0|11|906|+0.140095|+0.140095|0|
|L1/7200|13|1010|+0.024293|+0.024293|0|
|L1/14400|14|1210|0|0|0|
|L1/21600|13|862|0|0|0|
|L2/0|9|565|+0.229600|+0.229600|0|
|L2/7200|8|575|0|0|0|
|L2/14400|11|817|+0.196098|−0.816150|0|
|L2/21600|12|989|0|0|0|

L2/14400 多完成一个普通目标，science 增 0.196098，却使 Jain penalty 增 1.012248；完整分下降 0.816150。该 flow 没有被采用，selector 保留强控制。这个真实官方结算例子直接证明不能只看匹配权重。对强原指派的条件候选提升为 0–49.483157，其中绝大部分也由同图贪心取得，主要来自与声明质量模型相符的即时指派；不得把这部分归给增广机制。原强指派有 5 条正式 geometry miss，按 runner 的零贡献规则处理并归档，不把这些 miss 当作本机制收益证明。

### 公开目录上的最小增广 witness

L2/0 冻结图中，两个资源的三条边为：

|资源|目标|factor|score|
|---|---|---:|---:|
|exposure 2 / fiber 12，00:35:27Z|V4T005687|0.093806|0.112567|
|同一资源|V4T005098|0.273581|0.098489|
|exposure 4 / fiber 3|V4T005687|0.683496|0.820195|

逐曝光贪心先拿较高的 0.112567，后来又拿同目标 0.820195，终局早期贡献被 max 覆盖。flow 把早期纤维留给只有这一条边的 V4T005098，后来仍观测 V4T005687，净科学增量 0.098489；早期目标没有达到普通/required 阈值，Jain 与 required 不变。其余两个类似替代合计得到 0.229600。这个跨曝光互换是真实公开坐标和官方条件 scorer 构造出的机制 witness，不是人为抽象随机图；也只是有限固定图上的条件结果。

## 检查、成本和停止条件

- 100 个固定随机稀疏匹配图与独立全穷举核对，最大权值误差 0。
- `audit.py` 从固定 8 条骨架重建全部合法边，复算每种指派的官方全项值，最大误差 0；重新匹配的 target assignment 与原输出逐项相同。图、边的 score/factor 和每条改派都已保存。
- 8 组各 8–14 曝光、128–224 个 fiber 资源、565–1210 条合法边。匹配本体约 1.8–3.9 毫秒，整组约 2.3–4.7 秒，主要是 native 物理骨架生成；独立重建审核约 0.90 秒。没有 GPU、SSH、整季或网上提交。
- 首版把 native assignment 必须正式 hit 作为 assert，因边界 target 落到相邻 fiber 而失败；已保留 `failed_attempt_01.log`，按官方 miss=零分语义修正。点积改为逐行求和，避免本机窄矩阵 BLAS warning。隔离 witness 检查的 0.53×1.06 由四舍五入 0.562 改成精确 0.5618；初次完成源码和 manifest 均保留，8 个图结果未变。
- 8 个预声明起点，flow 对同图贪心均未改变首曝光；新增收益仅在冻结未来骨架上。没有得到可立即执行的真实公开 action gate，停止本轮，不扩候选、调时域或使用 L3/L4救参数。

本机制能低成本改进某些全局固定排程的指派，也能作为 population/LNS 的精确内层。但冻结未来骨架依赖未来选择与反馈，未知天气、program、completion witness、REQ gate、Jain 与 rank loss 都可能改变它的价值。当前证据不足以启动真实整季、训练或部署。

停止范围严格限于这 8 个固定强时序的联合 assignment 微域。遗传/群体的闭环政策构造、改变 exposure time/duration、改变 field 或以真正续局 fitness 选择个体均未被本轮实测，不能由首曝光无改派来否定这些路线。跨曝光目标拥有者表示可供未来群体设计参考：一个 target 的 science owner 是提供最高 surviving score 的 action，completion owner 可以是另一个 action；交叉若按这些 owner 的冲突连通块交换，而不是独立按夜交换，能显式携带被 max 隐藏的重复与稀缺 fiber 关系。本轮没有实现此算子，也没有证明它优于既有夜块交叉；只把它作为明确不同的结构变量供 root 判断。

复现：在工作区执行 `PYTHONDONTWRITEBYTECODE=1 python3 formal_v4/results/cold_population_search_20261004/probe.py`，再执行同目录 `audit.py`。依赖 NumPy、冻结 native 库和未修改的官方 runner 模块；不要求 SciPy。结果总目录：`formal_v4/results/cold_population_search_20261004/`，含 `MANIFEST.json`、`AUDIT.json`、8 条条件骨架、8 张全部边图、随机匹配与 witness sanity、日志及源快照。
