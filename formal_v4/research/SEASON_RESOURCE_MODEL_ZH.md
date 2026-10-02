# 剩余全季独立光纤资源 LP

实现：`season_resource_lp.py`。输入仅public初始化和可选当前公开得分状态；不读取truth。目的首先是检查全季资源瓶颈与继续价格是否存在，尚未注入stable路线。

## 数学模型

令t_in为未来夜n分给目标i的独立光纤秒，x_in=t_in/900。公共最低高度给可见时长V_in；解析计算赤经时角可见区间与夜窗口的交集，不使用SpatialPlanner的+.04度安全边界。保留0≤t_in≤V_in，Σ_i t_in≤nfib·night_seconds。共享指向、光纤格子、同曝光统一时长等冲突全部放宽。

固定C,E与质量几何系数H_in，a_in=flux_i·C·E·H_in/(F0T0)。允许多曝光因子累加作为放宽；但仍保留真正单曝光时长tmax产生的因子上限U_i=min(1,flux_i·C·E·max_n H_in·tmax/(F0T0))。

当前科学分b_i，最高程序乘数M，变量g_i为科学增长的归一化因子：

    0≤g_i≤max(0,U_i−b_i/(w_i M))
    g_i≤Σ_n a_in t_in

最大化科学增长Σ_i w_i M g_i。这个不等式是放宽：允许已得分b_i加上累积新因子，但真实问题只取单曝光最大得分。当前b_i大于未来单曝光上限时不允许虚构科学增长。

未确认完成required的目标引入0≤y_i≤1，阈值θ：

    y_i≤(baseline_factor_i+Σ_n a_in t_in)/θ

目标增加P·y_i，允许fractional required credit。若当前baseline<θ且U_i<θ，真实单曝光不能完成required，因此强制y_i=0，不能通过多次累加达到required。阈值数值比较向外留1e−12，避免浮点边界排除可能的完成。

`factor_mode=upper`用b_i/(w_i·min_program_multiplier)给当前最大因子上界。由于best score≥任一有效曝光w·factor·min_multiplier，这是有效的历史上界。`estimated`则使用调用者当前因子估计，仅做继续价值模型。零权重目标的上界取1。

### 质量与上界

`physical_ce`用H≤1（最低高度≥0时normalized airmass≥1，lunar≤1），仅在**指定C/E未来恒定**模型内给science+required资源松弛数值上界。C/E不是隐藏未来天气的已证明上界，因此该数值不是比赛全局总分上界。

`sampled_geom_max`以900秒公共几何采样取每target-night的H最大值，没有证明连续最大值，属于冻结/预期继续价值surrogate。所有版本均删去均匀性、报告、请求及data loss，不能冒充完整total上界；本pilot也没有有理数精确证书。

## 对偶输出的含义

science覆盖行的价格α_i针对归一化因子g_i；对应科学分单位价格λ_i=α_i/(w_iM)。required行价格ρ_i对应threshold fraction，原始factor单位价格ρ_i/θ。每夜时间价格β_n/900为每光纤秒机会成本。输出分别为`target_prices.json`和`night_prices.json`。

零lower bound处对偶可能不唯一，solver可返回α_i>w_iM。这不是一个目标科学分比总奖励还大的实际价值；将α压至w_iM、ρ压至P只降低时间列的对偶需求，保留其可行方向，raw marginal仍保存。需要正式证书时还须重新检查全部对偶/浮点容差，当前只输出数值继续价格。

这些价格属于资源LP，**不是前文精确max覆盖master的相同层价格**。可供丰富CPU/GPU候选的science增益权重与时间机会成本参考；required以连续raw-factor增量定价，不应直接把真实quorum/threshold结算改为部分支付。当所有资源价格为0时，应报告松弛没有识别瓶颈，不能将stable价值全部归零。

## 全 L1 可计算量及结果

| 项目 | 正常质量固定模型 | 低效率几何surrogate |
|---|---:|---:|
| C / E | 1 / .95 | .9 / .37 |
| targets / nights / target-night连接 | 7800 / 32 / 249600 | 相同 |
| variables / constraints / nonzeros | 257790 / 8222 / 519870 | 相同 |
| CSR storage | 6.27MB | 6.27MB |
| solver秒 | 1.049 | 30.567 |
| science LP | 8368.251673 | 6229.850067 |
| science单曝光ceiling | 8368.251673 | 7048.177294 |
| 模型required不可达 | 2 | 25 |
| science+required模型值 | 8268.251673 | 4979.850067 |
| science / required / night正价格数 | 0 / 0 / 0 | 7800 / 17 / 32 |

低效率case一次采样进程RSS约370MB，本机CPU即可，无需Rhodes1/GPU。正常质量下只用8346992个fiber秒，容量14068800，最紧夜利用率77.49%，没有一个夜资源绑定；得到零对偶价是数学结果。这说明单独总fiber资源放宽太松，共享指向与统一曝光时长等耦合才是不能删除的主要约束。不能借此宣称真实巡天没有瓶颈。

低效率模型资源全饱和，science单位价截至[0,1]；17个required的fraction层价格为约.025至.308；night每fiber秒价格约.000252至.000258。原始1115个science marginal因lower-bound退化超过全部奖励，已压至1并保留raw值。

### 使用已有公开状态的晚季小试

从独立rolling回放读取截至2026-11-28 04:00 UTC的公开hit score，不使用CSV factor/quality或未来hit；因子采用score/(weight·M)保守下界，C=.697715、E=.155228来自同时间的公开预测。六夜剩余窗口35364连接、43167变量、78549非零元；求解.225秒。当前science2870.3145，资源LPscience3502.3137，science+required3352.3137，4994 science/6 night正价格；三个未完成required在此冻结质量下不可达。

这是当时弱估计质量下的继续模型，不能解释成真实未来最优值。它展示晚季重建资源LP成本很小，也展示局部滚动路线即便在自己的冻结模型内仍没有达到较宽松的继续能力。

## 验证及结论

四项测试通过：共享时间同时检查单曝光science ceiling；低于单曝光required阈值不得通过累计完成；历史science floor保留；解析visibility与细网格公开几何相符。矩阵规模2GB/900秒内可行；低效率全季case需要约31秒，不适合每个observe重解，可在质量或夜历阶段改变时周期重建。

此LP没有直接改善/替换任何stable行动。下一步要保留空间/同期曝光耦合：例如按有限公共几何pointing候选建立列，使用全季资源prices定价并补列；或在资源LP加入field/time同步的额外不等式，再检查松弛是否仍全零。该结论来自先化简、算界、检查对偶，不能靠增加搜索时长消除正常质量下松弛过弱的问题。
