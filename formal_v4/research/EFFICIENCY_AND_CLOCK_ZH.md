# 保守效率证据与观测日历时钟

2026-10-03。为第二版策略新增两个独立 helper，没有修改 policy。

## 效率证据

接口：

```python
from research.efficiency_bounds import infer_efficiency_upper

evidence = infer_efficiency_upper(
    hits, weights, flux, actual_duration, declared_program, scoring,
    normal_lower=.90,
)
```

hits 可为 score 数组或公开 `{target_id,score}` 数组；weights/flux 必须采用相同顺序。返回 `E_upper`（无证据为 None）、`per_target_upper`、`strong_count`、`witness_count` 和 `witness_target_ids`。

设 `y=score/weight`，声明程序匹配倍率 M，错误程序倍率 m。由于 factor≤1，`y_lower>m` 能确定声明程序匹配；`y_upper<M` 能确定未饱和。这里上下端点计入原始 score 的 ±0.500001e-6 舍入区间。只有同时满足这两个条件的 DARK 或 BRIGHT 目标才构成 witness。

对应真实完成因子和科学质量满足：

```text
g ≤ (score + rounding)/(weight*M)
Q ≤ g_upper*f0t0/(flux*actual_duration) = Q_upper
B ≥ band_lower_threshold
E_weighted = Q/B ≤ Q_upper/band_lower_threshold
```

程序档的下限由本次初始化评分参数读取：DARK 典型 0.65，BRIGHT 典型 0.40。BACKUP 没有正的下限，不能给出同样的 E 上界。饱和命中只给出 Q 下界，不能冒充效率异常上界证据。

即使天气随时间变化，如果所有正常效率片段都满足 E≥e₀，便有积分后的 Q≥e₀B。于是上界小于 e₀ 可排除“只有正常天气起伏”。不需要先验 C，也不需要精确反演三个天气字段。

以下前提必须分别核实：

- 没有方向天气衰减、地形零分或方向关闭；这些只影响 Q 而不影响程序 B，能完全伪装成低效率。
- 没有地震效率衰减；地震不可报告修复。
- 使用实际曝光时间；夜末被截断时不能使用原命令时间。
- 正常效率下界 e₀ 的依据明确。默认 .90 来自公开 reference 的 `jitter_minimum`，并不是每张正式卡初始化所公开的协议常数。

因此 `strong_count` 只表示相对于传入正常下界的异常证据，不能单独等同于可修复 fault。当前最稳妥的接入是首先限制免费报告，再用清洁诊断、发生时段先验及多个独立曝光累积概率。诊断曝光可选择高 flux 目标，让预估 factor 在 .9 左右并声明 DARK；直接全饱和反而无法形成上界。

合成验证结果：

| 情景 | E upper | strong_count | 解释 |
|---|---:|---:|---|
| 正常 B=1、E=.95 | 1.46154 | 0 | 不误报低效 |
| DARK 严重 fault E=.40 | .61538 | 1 | 形成效率异常上界 |
| BRIGHT 严重 fault B=.5、E=.40 | .50000 | 1 | 同样可检测 |
| DARK 饱和 | None | 0 | 排除不适用 witness |
| 程序错误 | None | 0 | 排除倍率不确定 |
| 正常效率但方向衰减 | .61538 | 1 | 展示必须排除方向伪证 |

另对 200 个随机正常 DARK/BRIGHT、未饱和且确定匹配的曝光验证，全部 strong_count=0。

## 日历时钟

接口：

```python
from research.belief_clock import BeliefClock

clock = BeliefClock(public_nights, slot_seconds=900, initial_time=survey_start)
clock.mark(feedback_belief_time)
elapsed = clock.elapsed(now)
C_prior, E_prior = clock.prior(C, E, now, seasonal_C)
```

public_nights 支持协议夜晚字典或 `(start,end)` 元组。mark 仅在更新储存的 belief 时调用；elapsed/prior 查询不改变锚点，因此连续等待不会丢掉应保留的跨夜项。

elapsed 用公开 night interval 的累计长度计算 `observing_seconds`，而不是 wall clock 秒数；同时计数锚点之后开始的观测夜。返回 `elapsed_slots`、`night_transitions`、`slot_retention=.88^elapsed_slots`、`night_retention=.82^night_transitions` 与二者乘积 `retention`。参考 AR 系数可通过构造参数调整。

验证：上一夜 08:00 收到反馈，下一夜 00:00 开始。中间 16 小时白天算 0 个观测槽、1 次跨夜，retention=.82。再等待 15 分钟，retention=.82×.88=.7216；重复查询仍是 .7216。此时 mark 新 belief 后，再经过 15 分钟，retention=.88。

这是 scalar C 的时间近似。真实生成器维护独立 night_state，每晚从 night_state 重置 slot_state；精确滤波需要同时维护 night 和 slot 潜状态。当前时钟解决把白天误算为几十个 slot，以及 `new_night` 只处理一轮后丢失的问题，不声称已经等价于完整三字段生成模型。
