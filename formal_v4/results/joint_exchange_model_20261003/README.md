# 从缺失目标到补偿链：有限列交换模型

此处审计最新最好 α 的 1184 个历史列、192 个条件 coupon、120 个最新 joint GPU 列，共 **1496 列**。只读既有自己的研究输出与公开 target 表；不生成新比赛分数、不改变 production/ZIP/Git index。现有物理区间仍带其原条件，后续如官方公开完整 truth，可用精确系数替换这些条件系数，交换模型本身不变。

## 问题结构

列 c 占据半开时间区间 `[a_c,b_c)`，为一组目标提供因子 `g_ic`、科学贡献 `s_ic`、program 和 complete-window REQ 覆盖。选定列不能时间重叠。

时间冲突图 G 的边为区间相交；G 是 interval graph。但结算不是通常的加权独立集：科学对每目标取 max，mandatory 对因子阈值取 OR，REQ 对窗口内 distinct target 取 quorum，Jain 依赖所有 RA 桶 completion 数。正确模型是 **interval graph 加资源超边**。

- 时间边：`c 与 d 不可同时选`。
- completion 资源：目标 i 的所有达到阈值列组成 witness 集 `W_i`，完成变量 `y_i <= sum(c in W_i) x_c`。
- 科学资源：不同 score 层或 winner 变量，不能直接累加各列 science。
- REQ 资源：每请求的目标 witness OR，再接 distinct quorum。
- Jain：从最终目标完成变量计算；completion 的超集也可能使覆盖更不均匀，因此该项不是单调奖励。

若仅给每条时间弧一个固定加性价值，DAG 最长路/加权区间调度可精确求解；加入跨弧资源 OR/max/quorum 后，不能把问题宣称为一个普通最小费用流。网络流仍适合时间可行性和可计算上界松弛。

## 实际缺口不是更多原缺失目标列

baseline 500 个 mandatory 中完成 **497 个**，其中 338 个只靠 **一个**历史 witness，143 个有两个，15 个有三个，一个有五个。长新曝光一旦挤掉这些单 witness，就同时损失许多 50 分。

265 个新列可以保守补足至少一个原缺失目标：

| 原缺失目标 | coupon / GPU seed 数 | 最轻 seed 丢失的其他 mandatory | 对应历史曝光冲突数 | 当前 pool 中所有 seed 能否无退化补偿 |
|---|---:|---:|---:|---|
| 1295 | 64 / 0 | 21 | 11 | 均不能 |
| 5424 | 64 / 69 | 8 | 9 | 均不能 |
| 8897 | 64 / 4 | 8 | 7 | 均不能 |

这里“均不能”有明确限定：固定 seed、保持原 497 个 mandatory 全部完成、只用当前 1496 列，并使用保守 factor_lower。每个 seed 都至少失去一个没有任何不冲突恢复列的原完成目标。因此这 265 个 seed 都能在该**有限且 mandatory 不退化**子问题中严格剪掉；不能据此排除增加未枚举新列、牺牲部分旧 mandatory 或完整问题的更优解。

最轻的 5424 seed 为 new index 192（GPU batch index 0），占 3579 秒、冲突历史 `[152..160]` 九次曝光；需生成补偿列的目标为：

```text
1328 1825 2600 3239 5488 7935 8528 8610
```

它们在当前 pool 中均无与该 seed 不冲突的恢复列。最轻 8897 seed 为 new index 160（coupon），冲突七次曝光；补偿目标：

```text
1031 1352 3480 5564 6885 7565 7746 8112
```

最轻 1295 seed 为 new index 16（coupon），占 3600 秒、冲突历史 `[78..88]`，仍需补偿 21 个目标；列表与原时间在 JSON 中。所有 seed 合计涉及 **63 个**会被挤掉的旧 mandatory。下一轮应为这些具体资源在其他时段产生可保守完成的新列，而不是只继续给 1295/5424/8897 增加几乎相同的长列。

## 可执行的候选生成与补偿闭包

### 1. 固定 seed，精确计欠账

令原调度为 B，seed 为 c。

```text
R(c) = B 中与 c 时间冲突的列
D(c) = {原已完成mandatory i:
        W_i(B) 全部位于 R(c)，且 c 没有完成 i}
```

注意多个原 witness 全丢才欠一个目标；某个原 winner 丢失也未必丢 mandatory。另独立记录科学下降：`best_before_i - max(best_outside_R_i, seed_score_i)`，以及被破坏的 REQ quorum。不得把三种资源合成一个 score 标签。

### 2. 为欠账目标开新的定价任务

对 D 中每个 i，枚举全季可见/质量可用的 start/end pairs，而非只在 seed 相邻夜晚搜索。已占用时段也可作为补偿候选，但必须继续追踪其冲突欠账。

对一个 pair：

1. 必须显式要求该目标的 `factor_lower>=.5`、实际/条件玻璃可分配以及整曝光可见。把它作为一个 mandatory anchor，不能让 fiber 最优值筛选把它自动丢掉。
2. 在同一 pointing/duration/program 中，同时尽量装入其他欠账目标；其余 fiber 按科学的真实剩余贡献 `max(0, s_ic-best_fixed_outside_i)` 和 REQ 残量填充。
3. 记录该列的完整新欠账集合和恢复集合；至少按 `(时间区间, 恢复bitset, 新欠账bitset)` 保留 Pareto 候选，而非只取最大 reduced cost 的前若干列。
4. 对生成的物理列恢复官方几何/曝光/固定 report 校验。相同目标不可分配两次，fiber 共用同一个 program。

### 3. 形成闭包并联合求解

固定 seed 不允许其他选列与它冲突。新恢复列可能再删除历史列、产生新资源欠账，重复上述流程。把所有涉及的历史列加入可重排集合，固定外部原列；外部目标 best/factor/REQ 状态作为本次局部 master 的常量。对闭包内**整个**列集合求 DAG flow + 科学 max + mandatory OR + REQ quorum 的 MILP，求解后完整重算 Jain、report、舍入误差，净得分未改善则保留原解。

实用首轮可以将“原 497 个 mandatory 不退化”设为硬约束，以便直接面向补偿链；得到不足时，再允许有成本地牺牲旧 mandatory，由完整净分 objective 决定。硬约束模式与允许牺牲模式不能共享同一个“无解即剪枝”结论。

### 4. 哪些闭包是完备的

对当前有限 pool，审计用一个保守的 union 闭包：收集全部替代候选的历史冲突并集；只要某个原 mandatory 的全部 witnesses 都落在此并集中且 seed 不保证它，就加入全部不冲突 seed 的新完成列，直到不再增加。

这个闭包故意忽略不同恢复候选之间的互斥，会多收集某些实际上不能一起发生的欠账，所以是候选邻域的**超集**，不是一个可执行调度。随后用 MILP 排除互斥；不能把并集的资源缺口当实际同时丢失量。

当前 pool 的闭包规模：

| seed 目标 | 历史闭包列数范围 | 新列闭包数范围 |
|---|---:|---:|
| 1295 | 11–34 | 1–117 |
| 5424 | 9–20 | 1–48 |
| 8897 | 6–11 | 1 |

这些规模支持对 seed 建小型精确 master。8897 的闭包只有 seed，本质上是当前 pool 根本没有恢复候选，不能靠更长时间 MILP 解出不存在的补偿列。

这个 completion 闭包只对“固定 seed、原 mandatory 不退化、有限 pool”的候选集合有意义；要宣称更一般局部完备性，还要收集科学 winner/REQ 资源依赖。只按时间 component 切块不是全局分解，Jain 更会连接所有 RA completion 桶。

## 有证明的剪枝与仅为启发式的截断

1. **物理/状态不合法**：曝光时间、整段可见、玻璃、重复 fiber/target、固定 report 被穿越、错误 repair/rank 状态，立即拒绝。α 没有 rank loss，但 report/E 时序依然固定。
2. **恢复 witness 空集**：在原 mandatory 不退化的有限 pool 中，seed 丢 i，而任何合法且不冲突 seed 的剩余列都不能完成 i，则 `x_seed=0`。若生成新列后该空集变非空，必须撤销剪枝。
3. **条件 Hall/容量界**：欠账目标集合 T 必须匹配到兼容列/时间资源。对能被证明互斥的 clique，一次最多选一列；若这些资源的最大 distinct completion 容量不足以覆盖 T，则该 preservation 分支无解。把一个 geometry column 当“16 个任意目标容量”只有松弛意义，不能给可实现的恢复方案。
4. **上界不足**：固定 seed/partial choices 后，解该有限池的 optimistic LP，保留科学上界、mandatory/REQ 奖励、report，删除非正 Jain 罚项。若其总 upper 小于已验证 incumbent 的 lower（含舍入裕量），可剪掉该分支。该证明仅覆盖所列出的列与物理假设。
5. **严格支配**：在同 start/end、相同状态效果下，一个列对每目标科学不劣、completion 与 REQ incidence 不劣，可支配另一个代理目标列。但实际 Jain 非单调；若想对实际总分安全剪枝，还需 completion/最终 RA count 向量相同或证明 Jain 不更差。不能用“多完成目标”自动宣称严格支配。
6. **全增广池对偶证书**：正确且可行的 LP dual 对所有允许新列都给 nonpositive reduced profit，才可认证当前有限 LP 无改善。只对 GPU 网格前 150 名或者五个时间案例检查，不能认证未定价区域；正 reduced cost 也不保证整数可实现改善。

Beam 的固定宽度、闭包最大深度、只取新列 top-k、仅近邻夜晚、只补最大欠账目标，均是可执行的启发式截断，需要明确记录遗漏的范围，不属于上述安全剪枝。

## 图规模证据与输出

1496 列的 interval graph 有 **21813 边、1141 个 component**，三个非平凡 component 大小为 **226、76、56**。加入 mandatory completion incidence 后，最大 component 为 **407 列**，component 数降至 **968**。这证明 resource 会跨时间 component 传播；这些统计尚未加入科学 max、REQ 和 Jain，因此不能据此拆成独立子问题或声称只需搜索 407 列。

`summary.json` 保存输入 SHA、逐 seed 的初始删除列/欠账/不冲突恢复候选、闭包大小、各原缺失目标的最轻 seed 与所有剪枝 scope。new indices 0–191 为 coupon，192–311 为 joint GPU batch；原历史 indices 为 0–1183。所有数据来自当前固定有限池，后续扩池需重新计算。

没有新可行分数或全局最优结论。下一步具体优先项是给 5424 和 8897 的两组八个补偿目标生成跨夜替代列，再联合精确求解，而不是继续孤立排名原 seed 的 reduced cost。
