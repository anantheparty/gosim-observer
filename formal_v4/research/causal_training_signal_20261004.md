# L1/L2 真实训练标签的可学性与新候选目标诊断

本轮只读取 `actual/fit_validation.tar.gz` 内 L1/L2 的32组训练 audit、control 公开 capture/NPZ、availability 以及两张公开 initialize。脚本白名单拒绝其他 payload；没有读取 L3 标签/公开 capture、sealed L4 或拟合模型。读取了 actual README 的已公开训练结论摘要，未使用其中验证数值作本轮统计或选参。所有实际读取的 archive member 与 SHA256 保存在 `results/causal_training_signal_20261004/report.json`。没有训练、SSH、GPU、新赛季、actor/教师或现有模型修改。

## 官方数学对象与数据单位

监督值是同一隐藏世界、同一公开前缀下 `a + π_native自然重规划` 的官方终局差 `Dω(H,a,a0;π_native)`。这是该行为策略的真实干预值；一般不等于公开历史下的条件期望，更不等于另一后续策略的价值。科学分是每目标的最大有效 `w*g*program_multiplier`；required 与 Jain 使用独立最大原始 factor；REQ 使用时间窗内完整曝光的完成 quota；report 为额外结算。

**标签学习的是“当前动作加行为策略的后续反应”，不是环境内在的最优Q。** 另一策略可能从同一个公开状态补回当前动作没有覆盖的目标，或将相同反馈变成不同的计划；当前数据没有观察这些反事实。

32个不同 state/prefix 不是32个独立世界。全部是 L1/L2 两条自然行为轨迹的嵌套前缀，同卡所有 capture public_history 经逐条 hash 比较确为最后一个 capture 的前缀。它们可作为32个决策组训练/诊断；泛化世界覆盖仍只有两张卡，组内候选以及同卡未来相关。

## 真实信号

以 `abs(delta)<=1e-6` 为 tie，127条非 control 分支中：正56、负69、tie2。只有一组缺 short，因为 control 已为60秒；未删除缺候选、负数或 tie。

| 分支家族 | 标签数 | 正/负/tie | 训练平均终局差 | 作为该组最好动作的次数 |
|---|---:|---:|---:|---:|
| field | 32 | 17/15/0 | +3.164715 | 10 |
| short | 31 | 14/17/0 | −3.266315 | 4 |
| long | 32 | 14/18/0 | −5.361329 | 5 |
| program | 32 | 11/19/2 | −3.061501 | 1 |
| control | 32 | 基准0 | 0 | 12 |

这批数据并非缺少正样本。卡间差异却很大：L1正49/负14，15/16组有更好候选；L2正7/负55/tie2，仅5/16组有更好候选。各组在现有家族上的 oracle 改善总和538.946148，其中L1为506.553919，占约94.0%；平均每个组16.842067。这个和来自32个互不兼容的单次干预未来，不能称为可累加的整季增益，也不能把这些训练 oracle 当验证结果。

训练 oracle 的五项组成是 science **538.665185**、Jain **0.280968**、required/REQ/report **0**。127标签中 required 和 report 差全部为0；REQ仅一个−100：L1/q00/rank106 long，science虽+22.537067，却使一个请求奖励丢失，终局−77.408239。其余主要变化是科学分。最大单组+62.139887为L1/rank419 field；前5组占oracle和44.913%，前8组65.296%，前16组98.853%。

因此这批标签能研究 science 续局敏感性和唯一已观察的 REQ 失败；不能学出有监督依据的 required/report 改善，也不足以训练 request 成功策略。公开 active request 仅4/32组，其中3组尚有缺口。前轮已证明的 request 成员关联信息丢失仍成立，但这批训练没有足够变化支持复杂 request 图模型。

## 行为与候选的覆盖

自然策略没有缩成少数完整动作：到最后训练 cut，L1/L2分别965/1073次曝光，完整动作 hash全部不同，整数时长分别698/769种；最常见五种时长仅占8.70%/7.08%。DARK占912/965（94.51%）与877/1073（81.73%），有程序偏好，但时长与物理指派都丰富。

监督候选家族则有明确限制：每组只有两个不同 pointing。short≈0.6倍、long≈1.5倍和program分支完整复制control的所有目标/纤维指派；它们无法改变 fiber 内目标竞争，也没有表示多次观测承诺、撤销、恢复或后续策略参数。field的 pointing 距离中位0.593547°，但目标集合Jaccard中位仅0.447222，不能称为同指派的重复。两个最高field改善分别只改变4/5、6/7个新增/移除目标，几何改动0.376975°/0.551760°，完整续局science却+62.150201/+56.242239。

calendar cut大致覆盖季节3%到97%/99%；它没有提供另外的行为轨迹、另一种自然后续策略、hard loss 世界，或围绕 required/REQ 瓶颈专门生成的动作。现在的 NN 只能重排这一族，无法凭空产生具有新指派或新续局承诺的物理动作。public native utility只对32个field替代有值，其余变体没有经过native的相同效用排序。

## 一个可严格证明的续局效应

以训练标签总体平方离差分解，同组非control分支平均值的“共同偏移”占72.469%方差；这是描述性分解，不能将这一项宣称为噪声或不因果。L1有6组所有替代正、L2有11组所有替代非正，说明数据很容易混合“当前动作家族差异”和“该前缀下后续策略整体向哪个轨迹移动”。

program分支能更精确隔离这一点。32组均逐字满足：只换 program，pointing、duration、assignments 不变。官方原始factor与实际program band不受声明program改变，因此该曝光的原始factor完全相同。若后续全部物理动作/声明/report时刻固定，那么所有有效 max factor、required、REQ、Jain也相同。只有本次得分倍率改变。

令 `d_b=m(program_alt,b)-m(program_control,b)`，`W=Σ assigned science_weight`。固定后续时每目标科学best的变化，由 max函数的单调性与1-Lipschitz性质满足

`W*min_b(d_b) <= Δscience_fixed_suffix <= W*max_b(d_b)`。

原始factor≤1，当前未能命中或已有更好的历史/未来分数只会缩小这个幅度。该界不需要隐藏天气、原始factor、真实band或曝光质量。

真实32个program续局中，**22个science差突破这个固定续局界，23个Jain差非零**。例如L1/rank419，science+42.673327，而公开权重给界 `[−3.15,+1.89]`，至少40.783327的科学变化来自后续动作/环境修复等响应；L2/rank425，science−63.535657，界 `[−2.67,+1.602]`，至少60.865657来自续局。32条的这种可证明最小后续幅度平均16.683325。

这证明当前目标不是即时program判档。它没有证明响应来自天气校准错误、RNG搜索变化、贪心吸引轨迹或合理的新信息：fit archive缺少各反事实逐决策公开反馈与per-target终局科学差，不能辨别这些原因。audit中的 aligned action divergences中位311、最大1115（计数包括首个动作及对齐变化），与明显续局响应一致，但不是独立机制证明。

即时公开 coarse 增量与终局差的非tie符号反转有59条；例如short即时coarse通常下降，却14/31终局为正。`terminal delta - predicted immediate delta` 混合预测物理误差与真正机会成本，不能把它直接标注为精确机会成本。

## 下一步应改变教师对象和提案对象

当前证据没有证明某个新图、群体或 NN 已经优于native；也没有否定这些算法族。它给出一个具体的下一研究对象：**改变持续后续策略的科学目标层价格，而不是继续学习五动作的更大标量critic**。

科学 max-only 目标有精确的层覆盖表达：`best_i=∫[0,1.2*w_i] 1{至少一条有效曝光score_i>=x} dx`，当前已得的 `[0,B_i]` 是常数。未来目标—机会图应关联剩余科学层与可执行曝光机会，表达“另一个夜晚/field还能补回这个层”的共享容量。当前短/长/程序变体固定所有指派，没有对此结构做干预；127个总标签又无法给每目标层分配信用。前轮request adapter只补 quota成员关系，这个科学对象不能由request节点替代。

一个有边界、可以由root调度的原型是 **短期科学层价格策略 πG**：

1. 从公开best score、science weight与合法几何机会构建剩余层；可先取 `{B_i,w_i,1.06w_i,1.12w_i,1.2w_i}` 内的有效区间，保留层宽，避免把重复曝光当累积signal。未来机会是公开时刻上经同一物理解码器合法生成的field/fiber动作；天气仅使用已公开belief/forecast估计，不能输入terminal标签或未来请求成员。
2. 机会图中同一时刻的不同field共享时间容量，同一field的同一fiber共享容量。给稀少可替代机会的科学层一个固定、公开可解释的软价格，例如层宽除以 `1+estimated_degree`。这是提案启发式，不是真实期望值/上界或已求出的最优影子价。
3. 在当前夜的一个固定短epoch内，用这些价格持续重生field与逐fiber指派，原几何/曝光精算器裁决合法动作；下一公开夜边界恢复πnative。该policy可改变多个后续field/assignment，真正超出现有五动作族。可以把它作为现有闭环群体策略的一个新成员；不需要先训练GNN。
4. NN的后续候选目标若值得做，应预测这些目标层的未来可补回支持或提案价格，并由物理解码器形成动作。应保留per-target反事实最终best差、第一曝光反馈与后续public状态，才能监督这个对象。当前127个总分差不能凭空变成16,400个独立目标层标签。

最先应采用一个 **2×2因果教师设计**：同一公开H、同一相容世界，两个冻结合法当前动作 `a0,aG`，分别接 `πnative,πG`；保存四个完整结算。这样能区分当前动作效应、后续policy效应与interaction：

`I = S(aG,πG)-S(a0,πG)-S(aG,πnative)+S(a0,πnative)`。

πG参数、epoch、候选预算及公众状态选择在新标签出现前固定。状态按公开calendar/geometry的规则选择，不能选择本报告最大+62的cut作为泛化证据。先做很小的可执行新提案/轨迹差异准入：若产生的action哈希全部仍在旧五动作族，或改变的仅是名字/程序，则失败；若公开图只重复几何日数、没有shared capacity关系，则属于旧汇总特征，失败。若预算固定后造成完整赛季超时、真实required/REQ损失掩盖science增量，或新的相容世界中效果符号不稳定，则停止该版本，不救参。

2×2的新训练机制才为策略群体/NN提案提供目标；单卡训练上改善、图中启发式值更高、或重复现有fixed-suffix critic都不构成采用证据。最终仍需隔新世界的完整受限赛季与实际强native比较。本轮没有运行这个原型；root可据已完成诊断决定预算与路线。

扩充数据应明确增加两个维度，而非继续增加同世界state数量。一个可预声明的小批设计是8个独立生成器world/seed-bundle（分开保留catalog/weather/request流来源），按world事先分4训练/2验证/2测试；每world跑πnative和πG两个行为轨迹，再各取一个由公开calendar/hash选出的cut，执行上述2×2分叉，最多64条分叉加16条自然控制完整季节。整个world、所有policy/cut/pair必须保持同一划分。该数量仍不足以宣称广泛泛化，意义在于开始区分world与policy effects。

新world必须在参考生成器支持的公开契约范围内；生成器world分布的期望不等于正式隐藏实例的精确条件期望。若需要估计同一个已有H的条件期望，必须另有与全部已收到bulletin/forecast/score舍入/hit反馈相容的隐藏后验采样器；未经核验的重新随机天气会破坏前缀条件，不能当作相容世界。目标关系上的新增标签应包括新field/逐fiber替换、剩余科学层的竞争支持和受public quota约束的动作，而非只重复0.6/1.5时长或program切换。本轮仅提出设计，没有启动这些季节。

## 可复现与限制

源码：`results/causal_training_signal_20261004/diagnose_train_only.py`；报告和每组/每分支训练数据统计分别为 `report.json`、`training_state_rows.json`、`training_branch_rows.json`。脚本核对public候选哈希、官方五项重构、capture NPZ hash、全部audit gate与源锁未变；原数据没有解压或编辑。只读取了130个L1/L2 payload（2初始化+32×4），没有读取manifest/outcome中的L3内容。微小pointing误差约1e−6°来自 arccos数值，未将相同pointing误判为独立field。

所有结论是训练分布/表示/标签定义诊断。没有采用NN、修改actor、开放L4、评价新策略或声称新的验证收益。
