# 阶段2：公开信息下的同槽约束

2026-10-04 JST。阶段1的4个文件与MANIFEST冻结。阶段2全部新输出放在 `results/band_identification_20261004/stage2/`。

## 在审计前冻结的最小差异

initialize公开`survey.slot_seconds`、每night start/end/slot_count与scoring常数。slot通过公开night anchor计算，并核对曝光开始时保存的bulletin `issued_at_utc==slot_start`、night_id/slot_id。不读取truth或未来公告。

**严格清洁替代**：仅实际duration<=120秒、完全处于一个slot、slot当前公告中没有非terrain事件的曝光；仅接收score舍入区间下端>0的hit。官方scorer这时只有一个midpoint，永久terrain只能给全0或全通，因此positive hit可排除terrain，完全不使用65°或隐藏terrain范围。报告、跨slot混合、缺/矛盾公告、slot expiry和空可行集合均清空或拒绝约束。至少3个positive hit才接收。

该单midpoint证明依赖两条已核对的官方生成器机制：`generate_bulletins`对每个slot公布全部与其重叠的非terrain/非fault事件（quake由effect表公布），故筛无其他notice排除了raw scorer的额外event切分；fault onset在slot起点、slot效率固定，且runner串行执行action，报告不会在一个observe中发生。fault故障本身可以存在，其未知E与C一样是该slot共同常数。terrain首尾覆盖整个survey，不在合格曝光内部切分。不能把此证明推广至改变公告完整性或slot内连续效率的其他模拟器。

阈值、program倍率、mismatch和flux0*t0由initialize.scoring读取。联合枚举C区间、Z=C*E区间，保留score六位舍入误差。有效来源只能为同槽已接收短曝光。

计划最小runtime行为：只有至少两条已接收曝光且自然出现不同声明program、原point C落在单条最新短曝光的可行C集合中却不落在联合可行C集合中时，才将当前planner的C/E按log空间距离投影到最近联合可行状态。只修改该slot当前planning env，不改持久pointfit、raw-factor安全账本、report规则、geometry/native source。slot过期后自然失效。不添加probe。

## 门检顺序与停止条件

1. Public-only窗口筛选与公式先在既有强native L2轨迹审计；离线truth只作之后的保真标签。记录新集合保留真值、natural multiprogram次数、状态冲突及具体变化。
2. 若没有冲突/实际候选动作变化，则停止，不运行完整赛季。
3. 若有变化，冻结runtime源与完整participant source lock，向root报告，再在Rhodes1 cores4–7运行同源control/constraint两个2CPU/2GiB/900秒完整官方protocol季节。participant只能挂participant与依赖，不能挂卡truth。旧nativeL2=6823.661561仅在control动作与分数重现时作参考。
4. 只有整季总分及science/required/REQ/report组件比较能决定采用；不以band准确率或RMSE宣布提分，不扫触发参数，不用其他卡救参。

数学补充：若允许任意未知方向损失rho_i∈[0,1]，低score仅给Z下界，不能给Z上界或排除高C/E别名；`score_lower/weight>mismatch`仍严格证明program匹配，因为官方对每target只乘一次program multiplier且factor<=1。阶段2选择单midpointpositive筛选，获得更强的公开clean证书。
