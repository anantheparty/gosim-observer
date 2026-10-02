# 关闭天气的诊断曝光：动作语义、反例与信息价值

2026-10-03。只读官方runner/scorer和公开配置；没有修改稳定Policy。这里提出一个独立CPU候选，尚未声称它已提高完整卡片得分。7个最小官方函数检验已通过：[closure_probe_checks.py](closure_probe_checks.py)、[closure_probe_checks_result.json](closure_probe_checks_result.json)。

## 1. 闭槽观察合法，反馈也确实可用于诊断

官方 [`normalize_action`](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_runner.py#L942) 检查动作结构、duration、pointing、fiber/target合法性，没有要求站点当前开放。scorer对closed slot积分贡献零。runner仍将合法observe记为 `valid=true`，正常推进observe_index和模拟时间，没有单独的“闭槽曝光扣分”。

若目标在正确纤维玻璃内且整个曝光满足最低高度，它仍进入hit列表，区别在于score=0。下一次snapshot的实际字段为：

```json
{
  "action": "observe",
  "observe_index": 0,
  "assigned_count": 1,
  "hit_count": 1,
  "hits": [{"target_id": "T", "score": 0.0}]
}
```

没有 `is_observable`、raw factor、天气质量、实际fiber、实际program band字段。例子由官方runner在自建900秒closed slot执行60秒observe得到；hit_count=1、score=0、动作valid=true。

因此：

- 非空hits中有严格大于舍入噪声的正分，证明至少该目标在曝光的一段时间得到有效积分；若曝光完整位于同一site slot，该slot不是全局关闭。
- `hit_count=0` 只说明assignment/几何/高度没有命中，不能判断天气。
- 非空hits全0不单独证明全局关闭。可能是方向遮挡、terrain、极差效率、极低质量或六位小数舍入。C/E分解也不能据此作为真值。
- 反馈中的score是本次贡献，不是最高历史分；即使目标已完成且没有新增最高分，仍可以充当诊断目标。

源码：[observe执行与feedback](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_runner.py#L709)、[quality积分](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_scorer.py#L319)。

## 2. “60秒probe+剩余wait”何时有弱支配保证

比较从t到B原本整段wait与以下替代：在 `[t,t+τ)` 诊断曝光，之后仍可wait到B，未来物理曝光轨迹完全保持。若满足：

1. 新增曝光不会改变任何数据丢失失效窗，且不改变触发时刻；
2. 新增曝光不改变Jain观测比例；
3. 不增加report动作，不触发额外时间预算终止；
4. diagnostic合法，能够在B以前结束；

则替代的最终总分不小于原方案。证明：每个target的best是max，新增非负贡献不能减小；required的最大有效factor不能下降；request在窗口内的最大factor不能下降；Jain比例和report settlement按前提不变。闭槽时新增贡献为零，分数相等；开放时可能新增分数或有用信息。

可实施的充分条件：公开确认stress disabled，或该单次data_loss已公开触发；诊断assignment仅使用目前有效factor下界已达到uniformity阈值的targets。新增曝光于是不会新增“已观测target”计数。root现有factor_lower/权威request proof可提供这个条件。全局最优后续决策保留原来的wait选项，所以额外信息不会强制选择更差路径；启发式Policy若过度反应后验，仍可能变差，需要独立回放。

公开α/β `config/v4_scenario.json` 的stress.enabled=false，γ/δ=true。initialize没有直接发送该标志；使用α/β这个保证必须来自已公开card metadata，不能默认为所有新正式卡都关闭stress。当前runner只建立一个data_loss计划，收到该state_resync后可以排除未来第二次同类失效；这个保证依赖当前公开版本。

## 3. 无条件支配为什么不成立

### 3.1 零分probe也会改变回溯失效

官方data_loss在触发后第一个decision冻结已执行observe总数N，删除索引区间 `[floor(aN),floor(bN))`。wait不计入N；闭槽observe计入N。插入一次observe会改变N和后来曝光索引，也可能更早送达触发。

最小账本反例：原来20次observe，其中原索引4有100分，其余0。a=.25、b=.30，原失效窗 `[5,6)`，100分保留。开头插入一个零分probe后N=21，窗仍为 `[5,6)`，但原索引4变成5，100分被删除。已用官方BestLedger复现。这一窗宽.05符合公开generator允许的窗口模型。

不能把“无直接扣分”推成“没有后效性”。来源：[data-loss触发与窗口](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_runner.py#L526)。

### 3.2 Jain罚分非单调

两个RA band原观测比例(.5,.5)，Jain=1、罚分0。额外完成第一band一个target后比例(1,.5)，Jain=.9，公开权重U=200时罚分增加20。若新增科学分小于20，总分下降。官方uniformity_penalty验证完全相同。

设s=Σr、q=Σr²、K为band数，则 `J=s²/(Kq)`；连续导数为：

```text
dJ/dr_k = 2s(q−s*r_k)/(K*q²)
```

在过度覆盖的band增加完成率会降低Jain。使用已完成targets作纯诊断可以避开这个外部性。

### 3.3 本题曝光不累计

同一target的60秒probe和840秒续曝，不等于900秒曝光：只取两次贡献中的最大值。官方scorer在固定开槽、flux=.1、其他质量常数条件下：900秒得.29411765；60+840的best只有.27450980。探针消耗的是后续长曝光可用时间；不能把前60秒加回后840秒。

因此与整槽wait比较时probe可能有价值，但与直接整槽observe比较时不能忽略这项机会成本。

## 4. 槽边界、夜末与方向反例

诊断曝光必须完整落在要判定的site slot内。设B为下一公开slot边界、夜末、survey末三者最早者。若 `B−t<tmin`，选择wait_until(B)，不要用60秒跨槽probe来判断当前槽。

例：从slot尾部850秒处probe60秒，前50秒closed、后10秒open；得正分不能证明原slot开放。已用官方quality积分复现。

合法observe的输入duration必须达到tmin；runner会在夜末裁剪实际duration。自建20秒夜末输入60秒，实际执行20秒，仍valid=true。若这已是survey末端，不会再有snapshot，因此拿不到该probe反馈。候选避免这种没有后续决策价值的probe。

ALL site closure在同一slot的truth状态不变；方向事件的作用随target的alt/az改变。一个target前60秒在rocket扇区内全0，随后840秒已离开扇区可以正分。官方scorer检验也已复现。零分只能作为观测方向的积分证据，不能清除全槽其它方向机会。

时间切分、气团、Moon、program band也随时间变化；probe估计的Z是曝光平均有效质量，不能直接当成未来840秒的精确常量。

## 5. 独立CPU候选：比较三个分支

候选名为 `closure_probe_safe`。不直接删除或覆盖稳定Policy的闭槽分支，先作为单独candidate回放。

在current bulletin出现ALL rain/storm、本来会wait到B时：

1. 从公开metadata/已收到state_resync确定上述stress条件。
2. 确定B和最短合法τ=tmin；若没有完整τ或剩余wallclock不足，保留原wait。
3. 产生两个物理候选：正常planner的整段/整槽曝光；以及一个短诊断曝光。诊断只给已达到uniformity阈值的target分配纤维，使用已有指向校准结果，避开公开terrain/方向风险。
4. 在同一后验天气分布下比较 **wait、direct-full、probe→adaptive-follow**。probe分支必须正确使用max-per-target并计算Jain变化，不能把两段曝光相加。
5. probe结束时有正分，确认本slot站点开放，再用实际公开score与AR prior估计Z，对剩余时间重新选择动作。非空全0只更新“该方向质量接近0”的概率，并保留wait选项；空hits不更新关闭概率。
6. 一个slot最多一项纯诊断，结论只有效到B；下一slot重新预测，不能把上一槽0分延续整夜。
7. 无stress保证的γ/δ前期，pure probe分支默认不执行；另行研究包含失效窗口风险的期望版本，不能声称支配。

纯诊断的目标选择可用 `信噪比/预计计算成本`，而非新增科学收益：优先已完成、足够亮但60秒不饱和、位置和assignment可靠的targets。只需一部分稳健命中；额外纤维用于分辨局部遮挡，不必为每次probe运行昂贵全局重规划。所有分支均由公开信息构造。

## 6. 信息价值与计算预算公式

令b为“site开放/有效质量/方向遮挡/仪器”的联合belief。不可把非唯一C/E fit当真值。记Y为公开probe分数，B为固定比较终点，π为B之后固定策略；把required、request、Jain和失效全部放入收益R。

```text
Q_wait(b) = E_b[V_π(state at B)]
Q_full(b) = E_b[R(full exposure) + V_π(state at B)]
Q_probe(b) = E_{b,Y}[ R(probe)
                   + max_{a∈A(B−t−τ)} { R(a|Y) + V_π(state at B|Y,a) } ]
             − λ_wall * extra_CPU_seconds
```

选三者最大的可行分支。A必须包含wait到B。λ_wall是当前剩余求解时间的影子价格，可由后续平均每CPU秒可保住的分数估计；并保留wallclock硬门槛。官网900秒预算下，额外observe会增加runner几何/scorer时间和一次agent往返，不只是agent自己的planning时间。

当状态和行动集合相同，纯信息的标准价值满足：

```text
E_Y[max_a Q(a|Y)] − max_a E_Y[Q(a|Y)] ≥ 0
```

但probe还消耗τ、改变账本/observe_count，上式不能单独证明总收益。probe最可能有用的情况是：关闭概率不确定、剩余槽有紧急request/required价值，或正确program/方向选择的收益足以覆盖短曝时间损失。预计肯定关闭且没有不确定性时，wait更省计算；预计开放且同一批target需长曝光时，direct-full可能更好。

### 6.1 如需进一步纳入失效风险

公开generator的窗口先验是两个独立Uniform(0,1)排序，条件窗口宽≤x。令D=x−x²/2。某observe action的索引k（0-based）失效等价于窗口覆盖位置 `p=(k+1)/N`，不是k/N。

连续先验下：

```text
P(p covered) = [x² − max(x−p,0)² − max(x−1+p,0)²] / (2D)
```

若同一target的多次贡献中，要检查全部高分曝光同时失效，设这些曝光的最小/最大位置为l,r，则：

```text
P(all covered) = [max(x−(r−l),0)²
                  − max(x−r,0)² − max(x−1+l,0)²] / (2D)
```

按贡献分数从高到低排列v₁..vₘ，vₘ₊₁=0，则：

```text
E[best valid score] = Σ_j (v_j−v_{j+1}) * [1−P(top j exposures all invalid)]
```

这给出一个真正依赖动作历史的期望账本模型，可以比较新增probe改变索引后的影响，而非把所有target独立乘固定失效率。生成器把a/b写为六位小数；精确评估可将索引边界p替换为 `(ceil(p*1e6)−.5)/1e6` 并裁至[0,1]，这是rounding bins的对应边界。未知x、trigger和N还需联合先验；reference值只能作为明示模型假设。

来源：[stress generator](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_weather_simulator.py#L667)。当前候选尚未实现此更复杂分支，先使用有条件保证的safe版本。

## 7. 应如何验证候选

先在公开α/β以及γ/δ的state_resync后做独立CPU完整回放，记录：新增diagnostic数、正分/全0/空hit数、额外wallclock、整槽实际收益、required/REQ/Jain/报告分项、最终分。再看新增信息是否真的改变了后续有效选择。不能只比较新增science或把validity回溯忽略。

当前最小检验的7项全部通过，但这些只能验证协议与反例；它们不替代完整策略得分验证。
