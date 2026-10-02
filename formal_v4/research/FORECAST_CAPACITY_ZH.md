# 正式 v4：预报能证明的覆盖与可用时间上界

2026-10-03。只使用已发布的公开消息和公开观测日历。新增独立 helper，没有修改 policy 或 spatial planner。

## 1. 首末触碰能够证明什么

对一个天气事件设实际区间为 `[s,e)`，首个预报触碰夜为 `[a₁,b₁)`，末个触碰夜为 `[aₖ,bₖ)`。公告中的每条 forecast notice 来自**一个**事件，该事件区间连续。

仅利用区间相交：

```text
s < b₁，e > aₖ
因此 [b₁,aₖ] 必定属于该事件。
```

任一严格位于首夜与末夜之间的观测夜完全落在这个区间内，故一定整夜受该事件覆盖。这一结论不需要概率，也不依赖事件随机长度的具体分布。白天不消耗 duration_slots，但生成器保存的是横跨白天的一个连续 UTC 区间；恢复到下一夜后事件仍持续。

公开生成器还有更强的槽边界约束：天气事件从一个 published slot 的起点开始，在一个 published slot 的终点结束。slot 长度为 Δ，因此：

```text
s ≤ b₁−Δ，e ≥ aₖ+Δ
确定覆盖核心 = [b₁−Δ,aₖ+Δ) ∩ 公开观测窗口。
```

故触碰至少两夜时，**首触夜最后一个 slot、末触夜第一个 slot，以及所有中间夜**均确定被该天气事件覆盖。一夜含多个 slot 时，单夜 notice 不能确定具体任何一个 slot；只有该夜恰好一个 slot 才能确定整槽覆盖。

这对所有符合当前公开 generator 的天气事件成立。模块把确定核心再裁剪至本条 forecast 的 coverage；此处理保守，避免扩大有效期。

## 2. “被 rain 覆盖”不等于无条件“关闭”

不能仅凭 rain/storm 的标签，把以上覆盖时间无条件剪为零容量。

公开 `validate_config` 不要求 `rainy.force_close` 或 `tornado.force_close` 为 true；天气事件直接读取 `bool(definition['force_close'])`。站点 slot 的关闭逻辑是：

```python
observable = background_open and not any(event.force_close for event in active)
```

因此合法配置可以生成一个覆盖三夜、direction=ALL 的 rain notice，同时中间夜完全可观测。已用官方函数复现这个反例：修改 reference rainy.force_close=false，关闭背景随机关闭，配置校验通过；官方 generate_forecasts 发出三夜 ALL rain notice，generate_weather 输出全部 6 个 slot 可观测。

公开 reference 配置确实把 rain/storm 设置为全场强制关闭。这可以作为明确的**参考模型假设**，不能冒充每张正式卡公开保证。参与者文档也使用“在受影响范围内，可使观测暂时关闭”的措辞。

模块默认 `closing_kinds=()`。此时任何 rain/storm 预报都不触发硬关闭剪枝；仍输出确定覆盖，让上层建立质量/关闭概率模型。如已确认某张任务卡的对应生成配置，或有意使用 reference 假设，可显式传 `('rain','storm')`；返回字段名保留 conditional，提醒该额外前提。

方向 notice 即使对应 force-close 事件也不剪除整夜：粗略方位没有公开精确 azimuth 边界或 altitude 上限。rocket_launch 确实恒定关闭其隐藏扇区，但它不延续到下一夜，也不能证明全场关闭。

## 3. 消息与覆盖语义

| 公开字段/情况 | 可以利用的事实 | 不能据此推出 |
|---|---|---|
| `nights` | 查 `survey.nights[].night_date` 对应的观测夜 | 不能按 UTC 日期截取一天；night_date 可早于首槽 UTC 日期 |
| 一条 notice 多夜 | 同一连续事件触碰所列各夜 | 不能将不同 notice 拼成同一事件 |
| 两条相同 kind/direction | 两个事件各自存在，可分别取确定区间并作并集 | 不能把首条第一夜到第二条末夜之间全部填满 |
| forecast coverage 内没有某类 notice | 无该类 forecastable 事件在对应覆盖窗口活动 | 不能推出没有背景关闭、地震、仪器故障 |
| 空 `notices` | 覆盖范围内无 forecastable 事件 | 不能推出天气好、仪器正常或站点始终开放 |
| `latest_forecast` 与 `new_messages` 重复 | 同一发布记录重复送达，应去重 | 不能重复累计概率或奖励 |
| 动作跨越多个发布时间 | `new_messages` 可携带多份 forecast | 不能仅保存最后一份而漏掉此前已公开约束 |
| 新 forecast 发布 | 新增一个覆盖区间内的真实约束 | v4 没有“新记录撤回旧记录”的修订协议 |
| latest_forecast 已过 coverage_end | 历史记录仍在字段里；对未来容量不再生效 | 不能让旧 notice 永久持续 |
| issued_at > now | 尚未发布，不可用于当前决策 | 不应把开发卡完整 JSONL 当作在线可见信息 |
| bulletin | 相关 slot 的粗略事件事实；重复 kind/direction 已合并 | 不能识别事件 ID，不能无依据与 forecast 同类事件合并 |

当前 forecast 没有误报/漏报概率；不确定性是时间粒度、方向边界和事件强度。所有完全覆盖的中间夜须出现在同一 notice 的 nights 中；模块拒绝缺失中间夜的格式，因为那不符合当前连续事件生成语义。

旧 forecasts 保存在对象中，不随 latest 覆盖而丢弃；查询时按发布时间和 coverage 裁剪。未发布记录不会先排队保存。无 revision 语义的同 issue/coverage 冲突记录会产生 warning 并保留第一条，避免静默改变已确认事实。

## 4. 可运行接口与接入建议

```python
from research.forecast_capacity import ForecastCapacity

forecast = ForecastCapacity(
    initial['survey']['nights'],
    initial['survey'].get('slot_seconds', 900),
    closing_kinds=(),
)

# 每轮 bookkeeping 时，先接入本轮所有公开消息。
forecast.ingest(snapshot)
info = forecast.summary(snapshot['now_utc'])

# geometric_windows 为目标的公开天文可见窗口，datetime/ISO 时间均可。
seconds_by_night = forecast.capacity_in_windows(
    geometric_windows, snapshot['now_utc'], end=request_deadline,
)
windows = forecast.future_windows(
    snapshot['now_utc'], end=request_deadline,
    visibility_windows=geometric_windows,
)
```

`summary` 每夜给出：

- `remaining_observing_seconds`：当前时刻以后、查询截止时刻以前的公开夜间时间。
- `forecast_covered_seconds`：已发布完整 forecasts 的覆盖秒数并集。
- `guaranteed_all_event_seconds`：按天气种类分别计算的确定 ALL 事件覆盖。
- `possible_event_seconds`：按种类给出可能覆盖的夜间区间；方向事件也计入此风险字段。
- `no_forecastable_event_seconds`：至少一份完整已发布预报能排除所有 forecastable 事件的时间。
- `conditional_closed_seconds`：在显式 closing_kinds 假设下确定关闭的秒数并集，重叠不重复相加。
- `unexcluded_seconds`：公开夜间时间减 conditional_closed，是潜在可用容量**上界**，不是可用时间保证。
- `fully_excluded_remaining_window`：本夜剩余查询窗口是否全部被条件关闭排除。

顶层有 `guaranteed_all_event_nights`、`conditional_closed_nights`、`guaranteed_closing_windows_utc` 和 warning。night_date 用于索引原日历，UTC 窗口用于与目标可见性、请求 deadline 相交。

最小落地顺序：先按 reference 假设与无条件默认分别回放，比较请求损失、required 缺失和最终分；soft urgency 用未来几何容量及确定天气覆盖风险，避免直接用“剩余夜数”。若请求有 deadline，必须用截止时刻前容量。仅 forecast 的缺失事件信息应更新天气风险先验，不应让 instrument E 自动复位。

当前 helper 不包含目标运动/方向扇区或质量数值预测，也不承诺全局最优。它提供时间约束，上层仍须把 fiber 几何、曝光时长、抢占收益与请求条件放进决策。

## 5. 可选期望模型

`uniform_boundary_occupancy(slot_count, position=...)` 提供可检查的**假设模型**，不是官方生成概率：假设完整看到了事件的首/末夜，且边界 slot 均匀。

若首触夜有 n 槽，第 j 槽（0-based）被事件覆盖的概率为 `(j+1)/n`；末触夜为 `(n−j)/n`；中间夜为 1。单夜事件假设所有合法有序边界对 `(s,e)` 等概率，其槽覆盖概率为：

```text
P(j covered) = (j+1)(n−j) / [n(n+1)/2]
```

实际官方 start 来自分层 nominal 加整数 jitter，duration_slots 来自配置区间的均匀整数抽样；两者条件分布未必等于均匀边界模型。被 forecast horizon 截断的首/末夜尤其不能直接应用该模型。更准确模型需要公开/拟合的 occurrence count、duration 范围与 start hazard，并对“触碰且恰好列出这些夜”的条件归一化；这些隐藏配置不可由标签直接恢复。

期望容量可以把逐槽关闭概率/质量先验与目标可见性相乘积分，再用于 urgency；不能把小概率当成数学上确定关闭。

## 6. 验证与源码证据

运行 `python3 formal_v4/research/forecast_capacity_checks.py`：6 项检查通过，包含官方字段格式、UTC/night_date 差异、默认与条件关闭区别、首末槽、分离 notices、方向事件、未来/过期/重复消息、coverage 裁剪、缺失中间夜拒绝，以及 4 夜×2槽的全部 36 个合法事件跨度穷举，确定核心无超出真事件区间。

另在官方公开 L1–L4 开发卡上，仅用各卡 public calendar/forecast 建模，再以公开开发 truth 作独立验证：23 份 forecasts、52 条 notices 全部合法；55 个确定 ALL 核心区间全部落在对应真事件并集内，reference 条件雨/风暴关闭区间均落在 true force_close 并集内。summary 查询耗时约 .56–.59 ms（本机，每卡重复100次）。开发 truth 仅用于这次检验，不进入在线 helper。

源码固定 commit `e01939d060f304c2a7cf04d9b3e46009b564fc23`：

- [天气生成器](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_weather_simulator.py)：V4Event.overlaps（198）、validate_config（288）、槽时长计数/连续结束时刻（484）、weather events（491–536）、rocket 截止当夜（539–569）、observable（819）、bulletin 去重（887–898）、forecast 单事件与 nights 裁剪（931–983）。
- [配置交叉校验](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_config_check.py)：并未补充 rainy/tornado force_close 必须为 true 的约束。
- [参与者说明](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/docs/v4-participant-guide-zh.md)：night_date（271）、消息与最新记录（345–347）、七日节奏（371）、无命中率/误报率（403）、nights 仅交集（411）、天气作用与按观测槽持续（427）、火箭当夜结束（493）。
- [reference 天气配置](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/reference/v4/v4_weather_config.json)：雨/风暴 force_close=true 是参考配置的值。
