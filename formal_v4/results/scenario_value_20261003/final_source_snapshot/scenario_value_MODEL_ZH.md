# 随机曝光完成价值：独立推导与锁定实验

2026-10-03。先阅读官方 v4 runner/scorer/fiber/workflow、L1–L4 公开卡与官方生成器，独立推导后才查已有研究。本文件只声明待测策略，不声明收益。

对历史最佳科学分 b_i 与源 factor_lower 不足阈值的保守 required 集合 R，候选曝光 a=(c,d,p,A) 的基础边际价值为

    E_s[sum_{i in A} (w_i m_{i,s} min(f_i d q_{i,s}/450,1)-b_i)_+
        + 50 sum_{i in A∩R} 1{f_i d q_{i,s}/450 >= .5}]

一般常数读取 initialize.scoring，不在策略中绑定卡真值。实际排序把每目标边际价值乘源 urgency，再除曝光时长 d；focus request 的 quota 奖励在这个加权目标和之外加入。RA uniformity 沿用源策略的 Jain 导数价格与同一完成阈值；请求完成用路径内剩余 quota，不能当场完成时沿用 capped progress continuation price。重新指派先最大化可加部分，然后加入 quota 价值，同时比较源指派；没有联合优化所有 quota。因此这不是精确有限时域 Bellman 值，也不是请求最优指派。

每条路径先将整个曝光按 900 秒槽边界及 ≤120 秒子段切开；段中点计算公开 lunar/airmass 几何 h_i(t)。q_exp 为 E_s(t)W_s(t)h_i(t) 的时长加权积分，q_band 为 W_s(t)h_i(t) 的积分，后者排除 efficiency 与方向损失。随后才做 program_band、program_multiplier、min(raw,1)、与历史 best 的正部、required 的 .5 阈值，最后取路径期望。不是 m(E[W])，也不是对各槽独立得分后相加。观测追踪与高度限制沿用强源策略，反馈只读公开 score。

已有 cold_probabilistic_model 只测固定 900 秒字段的联合 program 期望，未使用 best ledger、required 与真实完整季节。本模型增加了随机 required 完成概率、best 正部价值、曝光时长和指派决策。generator_forecast 改的是均值 clock；本模型保留其源均值。hidden_learning 是固定续策终分教师的 NN critic，本模型是明确有限路径积分，没有 NN 或 runtime LLM。

源固定为 runs/cold_neural_value_20261003/production_frozen；baseline/scenario 同一入口和 source hashes，CPUPhase 固定 24 anchor、4 seed、50 local、24 boundary、16 exact probe，避免 .22 秒候选截断混杂。捕获的 8 个不同中心包括原强基线动作，每中心保留原时长并加入由正态 75%/90% 节点构造的近似时长，不能将其称为路径模型下已校准的完成概率。每格从期望边际收益最高目标重新指派，同时保留源指派作为备选。

锁定路径数 16，用 seed 909817 生成 antithetic 标准正态，种子仅构造积分节点，不是任何卡的生成种子。C 的 slot log sigma .08 来自 reference 三字段 slot 相对标准差的 delta-method，night log sigma .19 类似，slot correlation .88。新近公开反馈条件下当前 sigma .06，随无反馈的槽间隔增加 slot 过程方差，跨夜加入 night 方差。E log sigma .0304 对应 reference [.90,1.00] 均匀 jitter。每槽分别将 C、E 的有限样本均值归一化为1，有限节点相关仍使 mean(C*E) 有微小漂移；integrated消融把C/E都置1，因此不是严格variance-only对照。初版漂移最大约0.32%。初版节点矩阵形状随最大跨槽数变化，短候选节点分布随候选集最大时长变化（sigma=.20时1/3/5槽首槽C方差为.045225/.019754/.050765），这是模型实现一致性缺陷，初版不得据此采用。prefix_fixed16x8 机械修正为覆盖 initialize 最大合法曝光的固定(path,slot,latent) bank；同一短候选只截共同前缀，1/3/5槽分布与共同曝光积分逐位一致门检通过。未来未知背景 closure 与新故障未纳入路径，这个分布是近似条件模型，不是完整生成器后验；当前闭天等待及报告策略仍由冻结源处理。隐藏卡可以改配置，须以留出完整终分判断迁移。

数据划分预先固定：L1 开发门检，L2 验证，L3/L4 锁定留出；所有参数只取官方公开参考生成器，未用 L1 真值拟合。先 official scorer crossing-slot checks，再完整 900 秒同源强 CPUPhase 配对；若超时则原规模失败并保留证据，缩减规模后重新锁源。只有 survey_complete 全季终分能进入采用判断。

实现审查保留两个版本修正：原始重新排序遗漏源的平坦rate区间优先更大gain规则，补回后L1动作文件字节完全相同；原始局部指派遗漏起始最小高度visible过滤，独立公开几何审查发现L1四个below-min目标（官方不hit），physical16x8补回源过滤并重跑。所有完整初版结果均保留，不把它们删除或冒充修正版成绩。

最终 prefix_fixed16x8 完整协议实验：L1 6206.367823→6232.156101（+25.788278），L2 6808.597984→6749.276565（−59.321419），required 缺失分别保持2/3，REQ奖励不变。L2验证失败，停止并拒绝采用；未用L3/L4救参。初版更大收益不能拼入最终成绩。两卡平均−16.766571，损失主要是科学分，说明当前近似瞬时边际收益仍不足以表达全季科学机会成本。
