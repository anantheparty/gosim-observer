# 独立机制推导（先于 portfolio 查重）

这是保留的独立初稿。末动作与间隔的绝对存活表述随后被六位CSV舍入反例修正；最终数学与适用范围见 survival_hedging_REPORT_ZH.md，不应把初稿未舍入结论当作正式CSV保证。

任务启动 2026-10-04。先读正式 runner/scorer/fiber、公开 participant guide、官方生成器，再查已有路线。

## 正式终局状态

每个 hit witness 是 (target, observe index, factor g, contribution c, start, end, valid)。科学分取有效 c 的最大；required 与 Jain 取有效 g 的最大，且最大 c 与最大 g 可以来自不同 witness。REQ 仅使用完全落在其 issued/deadline 窗口内的有效 witness。有效性丢失后所有这些量重算，已过期的 REQ 奖励也能撤回。

低于已有 best 的再次曝光并非总为零：

1. 即便没有 data_loss，新 g 可跨越 required/Jain 阈值而 c 因 program mismatch 低于旧 best；新的 REQ 窗口亦独立于季节 best。REQ 至少 k 个目标达标的奖励是联合事件。
2. 有尚未触发的 data_loss 时，新低 c witness 可以在旧较高 c witness 失效后成为 best；required/Jain/REQ 的冗余达标 witness 也有存活价值。
3. 无新 factor/REQ 状态、无未来失效时，低 c 的直接终局增量恰为零；若赋正分必须另行证明观测信息价值或行动计数的外部性。

## data_loss 与随机几何

生成器仅 stress_tests.enabled 时产生一个 data_loss（可能因 after_earthquake 且无震跳过），i,j 独立 U[0,1]，排序后拒绝 j-i>x。runner 触发前冻结已执行 observe 数 N，删除 [floor(iN), floor(jN))。wait/report 不计数；跨触发时刻的进行中曝光先完成。

定义 witness 切点 t_a=(a+1)/N。动作 a 失效等价 i<t_a<=j（连续分布边界无测度）。合法 (i,j) 域 0<=i<=j<=1,j-i<=x，面积 Z=x-x²/2。

集合 A 全失效概率只依赖最早/最晚切点 u,v：

p_loss(A|N,x)=Z^-1 integral from max(0,v-x) to u of max(0,min(1,i+x)-v) di。

若 v-u>=x 则该概率为零。最后一行动 a=N-1 的 t=1，永不失效（j<1 几乎必然）；这来自半开区间与 floor，不是事件预知。保持一串紧邻重复与分散重复的价值不同。

给目标按 c 降序不同值 c1>...>cm>0，A_k 为 c>=c_k 的 witness 集，则 E[best]=sum_k (c_k-c_{k+1}) (1-p_loss(A_k)), c_{m+1}=0。达标存活概率 =1-p_loss(所有 g>=阈值的 witness)。科学、required 可解析按目标求和；Jain 及 REQ k-of-n 必须共享同一(i,j)场景联合结算，不可拿独立存活概率代入。

追加 observe 会改变 N，进而改变所有历史 t_a；即便新 witness 自身无价值也会改变全 ledger 的损失风险。这种外部性可能正或负，不能仅计算新目标局部保底。trigger time 与 N 的不确定性须按公开历史、未来可执行行动场景积分，不能用隐藏真值。

已触发一次 data_loss 后，正式该 scenario 不再有后续 data_loss；存活冗余价值回到零，只保留 factor 与 REQ 特例。一般比赛文档允许的更广事件机制需重新证明。

## 初始可用性核对

官方 L1/L2 scenario stress.enabled=false；公开 guide 明确 ordinary cards 无两类 stress。仅 L3/L4 开启。public initialize 字段未承诺 stress flag/window x/未来 trigger time；赛事卡文档才可作为 Hard-mode 授权依据。因此不能默认 L1/L2 有存活价值，也不能将样例 stress x=.05 视为全部卡公开参数。

## 待做小审计

从真实已到达消息与 hit history 重建 L1/L2 prefix，计数低 c witness 带来 factor/REQ 变化；从公开 Hard 卡文档与 resync 核验机制有真实触发。用小 ledger 解析概率与完整共同场景终局结算反例验证，成本记录。先查 portfolio；若无公开 Hard 触发/可识别 prior 与动作排序差异，不启动完整 replanning。
