# 请求DP的未来质量：可见信息与作用范围

CPU完整窗口DP只耗424秒，却与基础phase总分完全相同；70/92次预测不可行、零动作改变。由此需要修正未来质量模型，计算速度不是本次无收益的主因。

## 可见输入与时间语义

官方initialize给出完整night_calendar（night_id、night_date、UTC观察起止），每次snapshot给出已发布latest_bulletin/latest_forecast及new_messages。未来数值天气、事件真值、未来请求未提供。

- bulletin：issued_at_utc、night_id、slot_id、initial、类别和粗方向。没有有效截止时间。非静态事件只为当前槽提供证据，不能无条件延续32小时请求窗。
- forecast：coverage_start_utc/coverage_end_utc及notices，每项给出event_kind、direction和nights。只在已发布forecast覆盖内匹配night_date，不能匹配UTC观察开始日期。例如N20261110在11/11UTC开始，但forecast nights=11/10指这个窗口。
- 初始terrain提示：永久地形方向，实际评分有alt/az矩形覆盖边界。坐标必须逐未来时间重算，不能把当前目标衰减固定在目标ID上。具体几何边界未知时，需要注明推断/保守范围，粗方向不能证明该方向全部高度不可观测。
- 经验blocked_spot：过去0分反馈的短时方向证据，现模型有1200秒到期。必须按未来时刻计算到期，不能永久冻结。
- 当前全局C/E：过去反馈识别的天气与仪器比例；冻结到未来只能作为条件场景估计。E若代表故障会持续至修复，而C天气可能变化，二者不能混为一个永久乘数。

## 条件场模型

未来raw质量可写作 `H_i(t)/q0 × global_scale_s(t) × terrain_field(alt_i(t),az_i(t)) × temporary_field_s(t,alt_i(t),az_i(t))`，s表示条件情景。terrain场由静态模型提供；当前bulletin临时场只作用当前已发布槽；窗口以后的临时场由已发布forecast的夜级条件与不确定幅度构造，没有forecast证据时回到相应先验。相同事件不能同时作为bulletin和forecast重复相乘。

公开H随时间的积分仍按官方900秒槽边界、≤120秒中点采样。静态/方向场也应在这些样本坐标上评价。未来天气为未知，因此输出可为期望或明确的保守场景，不能把它称为未来真值或可完成证书。

官方band_quality函数只用SlotTruth的全局transparency、sky_quality、seeing与公共H，未接收方向ScoreEvent，也不乘仪器E。方向地形/临时事件只乘raw factor侧。规划接口必须保留raw质量与program band质量的分离。

有限列DP在给定情景/列费用下仍然精确；真实全局最优性仍受未来未知质量、空间时间离散和科学账本共享饱和限制。应先验证新场能解释CPU首REQ预测不可行，再做完整同源整卡，随后才考虑正式评测。
