# v4 数据生成规律、可辨识性与公开反馈估计

日期：2026-10-03。审计对象为官方公开仓库 commit `e01939d060f304c2a7cf04d9b3e46009b564fc23` 和 `examples-2026-10-02` 示例包中的 L1–L4。本文中的生成参数来自公开参考配置；实际卡片可以使用不同配置，不能把参考值当作隐藏真值。未访问非公开服务器数据、其他队伍数据或评分平台内部文件。

## 1. 结论与实施优先级

1. 目标几何、太阳/月亮和日历可准确计算。未来数值天气、故障和未来请求仍然未知；应分别计算确定性机会和环境条件分布。
2. 参考天气有很强的时间相关性：slot AR 系数 0.88、night AR 系数 0.82。一次未饱和有效曝光的反馈能估计下一轮有效质量，价值明显高于每晚固定一个天气系数。
3. 公告/预报是生成器对真实事件的确定性粗化，参考实现没有预报漏报或误报。未列出某个预测夜的可预报事件，可排除该类事件与那个夜晚相交；仍不能排除背景关闭、地震或仪器故障。
4. 事件不是独立泊松发生，而是在观测 slot 序列上分层布点并抖动。此规律可构成发生时段先验，不能直接确定隐藏卡事件次数或精确时刻。
5. catalog 与 weather 等使用 SHA-256 派生的独立随机流。恢复目录 MT 状态不能直接预测天气。master seed 的范围/熵未公开，现有证据不支持“已经能破解随机数”，也不能证明所有 seed 都高熵。本轮优先做可检验的统计状态估计。
6. `last_result.hits` 中的 score 不是 raw completion factor。程序倍率存在歧义，应联合反演 site base quality 和 instrument efficiency，不能恒定除以 1.20。

第一版可直接使用 [feedback_model.py](feedback_model.py)；它只读取公开反馈及几何模型。后续适合增加故障变化点检测、固定偏差的候选集合估计，以及事件条件采样。

## 2. 证据位置与随机流

主要源码：

- [contracts.py](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/contracts.py)：`derive_stream_seed`、`stream_seed`。
- [v4_bundle.py](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_bundle.py)：`build_card_bundle`、`build_spec_bundle`。
- [v4_catalog_generator.py](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_catalog_generator.py)：目录生成。
- [v4_weather_simulator.py](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_weather_simulator.py)：天气、事件、公告、预报。
- [v4_observation_requests.py](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_observation_requests.py)：请求生成。
- [v4_scorer.py](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_scorer.py)、[v4_runner.py](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_runner.py)：评分、几何命中、公开反馈。

派生方式：

```text
stream_seed(master, name)
    = integer(first 16 bytes of SHA256(str(master) + ":" + name))
```

每个派生种子创建独立 `random.Random`，即 Python 的 Mersenne Twister。命名流如下：

| 流 | 内容 |
|---|---|
| `v4.catalog` | footprint、目标类别洗牌、required 选择、坐标、flux |
| `v4.weather.slots` | 逐夜/逐 slot 连续天气、背景关闭、效率 jitter |
| `v4.weather.events` | rainy/cloudy/smoggy/cold_wave/tornado |
| `v4.rocket_launch` | 火箭事件 |
| `v4.earthquake` | 地震时刻与强度 |
| `v4.terrain` | 永久地形遮挡 |
| `v4.instrument_fault` | 故障时刻与效率乘子 |
| `v4.stress.data_loss` | 丢失历史区间 |
| `v4.stress.pointing_offset` | 固定指向偏差 |
| `v4.observation_requests` | 请求目标池洗牌 |

`build_card_bundle` 强制 `sha256-v1` 并执行 `require_hashed_seeds=True` 校验。`build_spec_bundle` 允许自包含开发配置保留默认方式；历史参考配置没有 `seed_derivation` 时使用 `seed + offset`。不能把开发参考的这一旧行为推断为云端正式卡的实际行为。

公开 catalog 的多个随机输出可能约束 catalog 流状态；目录中浮点输出被舍入到 6 位小数，采样存在拒绝、Gaussian 缓存、不同消费步数，且不是直接连续的 32-bit 输出。即便完整恢复 catalog 流状态，SHA-256 分流仍隔离其他流。若 master seed 只有 b 位且所有生成配置已知，理论上能通过重生成公开目录验证候选，候选空间是 `2^b`；但本次没有可靠的 b、完整卡片生成配置或低熵依据。单纯 GPU hash 吞吐也不是完整目录验证的吞吐。对于高熵 master seed，不应期待在当前时间预算内恢复。

## 3. 目录的确定性结构和随机分布

footprint 是多个不相交的星形球面多边形。参考组件中心候选固定，随机抽取中心；各顶点半径由少数平滑谐波系数和 phase 决定，再按球面实际面积缩放。

类别人数按配置比例确定，舍入修正后洗牌。因此类别人数不是 multinomial 波动。参考比例：ELG 0.34、BGS 0.24、LRG 0.20、QSO 0.14、Star 0.08。required 是随机选定恰好 `round(N * required_fraction)` 个序号，参考比例 0.05。

坐标是均匀背景与 Gaussian 星团的混合，参考 clustered_fraction 0.25、cluster_sigma 0.5°，簇中心也先从 footprint 中采样。所有目标须通过几何观测窗口检查；失败坐标重采样。所以接近季节/高度边缘的目标分布存在条件偏差，不能用简单“均匀球面点”模型解释。真实目标已经公开，优化时直接使用公开坐标和窗口，通常无需逆推出簇中心。

flux 服从各类别独立的 log-normal；science_weight 是各类别的固定值：

| 类别 | flux median | log sigma | science weight |
|---|---:|---:|---:|
| ELG | 0.55 | 0.40 | 1.00 |
| BGS | 1.25 | 0.30 | 0.45 |
| LRG | 0.35 | 0.35 | 1.00 |
| QSO | 0.18 | 0.50 | 1.70 |
| Star | 4.00 | 0.25 | 0.30 |

这些分布适合合成训练实例。运行时 flux 和 weight 已知，选目标时无需猜测。目标编号是生成序号，不表示天区、优先级或难度。

## 4. 连续天气的状态方程

令字段 `x∈{seeing, transparency, sky_quality}`。第 n 夜的季节均值为 μₙ：

```text
phase = 2π * (day_of_year - 210) / 365.2425
μ_seeing = 1.10 + 0.15 sin(phase)
μ_transparency = 0.88 - 0.07 sin(phase)
μ_sky = 1.00 - 0.12 sin(phase)

x_night[n] = clip(μₙ + .82 (x_night[n-1] - μₙ)
                  + Normal(0, night_sigma * sqrt(1-.82²)))
x_slot[k]  = clip(x_night[n] + .88 (x_slot[k-1] - x_night[n])
                  + Normal(0, slot_sigma * sqrt(1-.88²)))
```

每晚的 slot 初态是该夜 night_state。Gaussian 噪声字段独立，clip 保证范围。参考参数：

| 字段 | night sigma | slot sigma | 最小/最大 |
|---|---:|---:|---|
| seeing | 0.16 | 0.07 | 0.50/4.00 |
| transparency | 0.06 | 0.025 | 0.08/1.00 |
| sky_quality | 0.10 | 0.035 | 0.05/1.50 |

基础效率独立 `Uniform(.90,1.00)`，随后乘全局事件、地震和当前故障乘子并 clip。报告修复故障时 scorer 恢复相应故障乘子；没有重抽天气。

低维状态可用：

```text
C = transparency * sky_quality / (seeing * q0)
E = effective instrument efficiency
Z = C * E
```

它近似汇总三个天气字段，并且直接进入评分。参考第 305 日的季节先验约 `C=.83917, E=.95, Z=.79721`；忽略事件时不是恒定 C=1。`E[C]` 与将字段均值代入的比值也不严格相等，所以这个数是初始季节基线，不是总体精确期望。

短期预测可令 `log C` 向季节基线按 `.88^Δslot` 回归；跨夜用 .82。这是三个 clipped AR 字段的近似，不是生成器的完全充分状态。若要精细 posterior，应维护三个字段、背景开闭、效率/地震/故障的粒子，并按实际观测算似然。

## 5. 背景关闭和事件发生规律

背景开闭是每夜重置为 OPEN 的两状态 Markov chain：

```text
P(OPEN → CLOSED) = .008 + .006 max(0,sin(phase))
P(CLOSED → OPEN) = .32
```

一个天气 slot 是 900 秒。关闭持续 slot 数是参数 .32 的几何分布，平均约 3.125 slots，即 46.9 分钟；这只是背景关闭，公布的 rain/storm 会另外覆盖。平稳关闭概率 `p/(p+.32)`，参考范围约 2.44%～4.19%。观察到背景关闭后短时间再次曝光可能全零，跨到下一 slot 后再探测更有价值；不能因一次全零就报告故障。

其他事件按观测 slot 序列的索引安排，跳过白天时间：

```text
nominal_index(j,k) = floor((j+1)*Nslots/(k+1))
actual_index = clip(nominal_index + integer_uniform(-M,M))
```

天气 M=80，火箭 M=120，地震/仪器故障 M=200。相同类型的发生次数 k 由配置决定。持续长度按配置整槽均匀抽取：

| 事件 | 参考持续槽数 | 作用 | 公告/预报 |
|---|---|---|---|
| rain | 8–40 | 全局强制关闭 | 当前+未来 |
| overcast | 8–32 | 全局或方向天气衰减 | 当前+未来 |
| haze | 24–96 | 全局或方向天气衰减 | 当前+未来 |
| cold_snap | 48–192 | 全局轻度衰减 | 当前+未来 |
| storm | 4–12 | 全局强制关闭 | 当前+未来 |
| rocket_launch | 2–5，截到当夜末 | 扇区强制关闭 | 当前+未来 |
| earthquake | 冲击后逐夜恢复 | 全局效率等衰减 | 仅当前 |
| terrain_obstruction | 整季 | 扇区零分 | 首条公告一次 |
| instrument_fault | 到下一故障或季末；可报告修复 | 全局效率衰减 | 完全隐藏 |

天气事件 severity `Uniform(.55,1)`；各字段乘子 `1+severity*(configured_multiplier-1)`。一般 cloudy/haze 可只影响一个方向，rain/cold_snap/storm 默认 ALL。不应把 cold_snap 当关闭，也不应对所有带方向的事件整夜停止工作。

事件次数未知时可维护小型 k 候选 posterior，将新预报/公告作为条件：例如已确认事件时刻、未见事件时段，对相应 stratified-index 模型计算 likelihood。无需猜 master seed。基于公开参考“均匀分层”模型的 hazard 有助于安排高收益任务，但实际卡可改事件次数/配置，应允许不匹配时退回经验模型。

## 6. 公告和预报的条件模型

方向是扇区中心方位的最近 8 方位量化；量化误差 ±22.5°。已知方向 d，并不意味着只有该 45°方位内受影响。

参考方向事件：

| 类型 | 扇区宽度 | 最高影响高度 |
|---|---|---|
| cloudy/haze | Uniform(40°,120°) | Uniform(40°,80°) |
| rocket_launch | Uniform(40°,80°) | Uniform(30°,60°) |
| terrain | Uniform(30°,70°) | Uniform(35°,50°) |

若未有额外观测，中心方位条件分布是在 `[d-22.5°,d+22.5°]` 均匀。给定目标方位 a、随机宽度 W，方位覆盖概率是：

```text
p_az(a | W,d) = length([d-22.5,d+22.5] ∩ [a-W/2,a+W/2]) / 45
p_alt(h) = clip((Amax-h)/(Amax-Amin),0,1)
p_covered = E_W[p_az] * p_alt
```

计算须处理 360°绕回。可对 W 用 8～16 个离散积分点。参考配置中 high-altitude 指向对地形/火箭比简单把一个方向全封锁更稳妥；但是高度上限属于参考先验，没有公告给出其精确值。

预报每 7 日发布，覆盖 7 日，包含与覆盖窗口相交事件及受影响的 observing night_date；事件可以从上一夜延续进入覆盖区。预报没有精确起止时刻/强度/边界。应对每个事件采样 slot 起点、持续槽数、扇区和 severity，并拒绝与已公布 affected-night 集合不一致的样本。在线新公告会进一步把当前活动状态约束为真；新公告没有事件时，活动状态为假，但同 kind+direction 的多个事件会去重，不能当一条公告对应唯一 event_id。

程序运行只使用当时已发布的数据。L1–L4 的完整预报、公告和 truth 用于离线测量以及先知对照；不能把其全部未来行直接注入在线策略。

## 7. 从 score 联合反演天气与程序倍率

对于有效命中目标 i：

```text
H_i = exposure_average(lunar_factor_i / airmass_i^beta)
B_i ≈ C H_i                       # 程序判档，不含 E 或方向效应
Q_i ≈ C E H_i                     # 科学收益质量，暂不含方向效应
g_i = min(flux_i * T * Q_i / (f0*t0),1)
y_i = score_i / weight_i
y_i = g_i * (M if band(B_i)==declared_program else m)
```

实际 scorer 做 ≤120 秒积分，且全局天气可跨槽变化，因此 scalar C/E 分解是近似；几何 H 应使用曝光中点分段积分，不能只用曝光起点高度。

设声明程序倍率 M、mismatch 倍率 m，有无条件区间：

```text
g_lower = min(y_i / max(M,m), 1)
g_upper = min(y_i / min(M,m), 1)
```

若 `y_i > m` 且 M>m，则必然匹配，可以得到 g=`y_i/M`。若 `y_i≈M`，g 饱和，只能给出 Q 的下界。`y_i<m` 的未饱和目标可能匹配也可能不匹配，单目标无法直接判断。

联合多个目标可以枚举 C/E 候选，并用精确 capped reward 与程序判档预测 y。C 的有效判档只在 `0.65/H_i` 和 `0.4/H_i` 发生变化，最多 O(n) 个区间；因此后续可以将二维网格化简为若干程序模式，再对 Z=C*E 做一维分段二次优化。当前实现采用 NumPy 网格加判档边界节点，带上一轮的 C/E 先验，避免 narrow band 被网格遗漏。多数未饱和目标给出相同模式下的 Z 点估计，使用中位数精细校正以消除网格精度损失；方向受损目标对全局状态拟合的损失有上限。

API：

```python
fit_feedback(hits_or_scores, weights, flux, duration, geometric_H,
             declared_program, scoring_dict, prior_C=1.0, prior_E=.95,
             *, grid_c=129, grid_e=65)
```

hits 为 `[{'target_id':..., 'score':...}, ...]` 或 score 数组；其他数组与 hits 采用相同顺序。scoring_dict 为初始化的 scoring。返回：

- `C,E,observed_Z`：site 状态估计；
- `factor_estimates`、`factor_lower`、`factor_upper`：各 hit 的 raw completion 估计和无条件上下界；
- `quality_estimates`、`program_matches`：拟合出的质量和声明程序匹配判断；
- `loss,saturated_count,unsaturated_count,outlier_count`：诊断；
- `closed_evidence`：所有几何有效 hits 都为零；
- `informative`：是否存在可用于质量点估计的未饱和 hit。

`factor_estimates` 的倍率判断属于模型估计。required、uniformity 或 request 门槛附近用 `factor_lower` 保守处理，或结合下一轮已公布的 completed request 状态纠正。保存原始 score/程序/曝光历史，不能仅保存 estimated factor。

本地验证：100 个随机合成的 16-hit 曝光，固定非真值 `prior_C=1,E=.95`，覆盖天气、效率下降、三类声明程序和饱和；90/100 的 factor 全部精确到浮点精度，p90 的单曝光最大 factor 误差为 0.000256、最坏 0.01695；Z 最坏相对误差 1.38%。全部无条件 factor bounds 包含构造真值。Mac 本地单次中位耗时约 2.23 ms。这只验证简化反演模型，不是 L1–L4 策略得分或线上成绩。

可辨识性限制：如果所有目标都饱和，通常只有质量下界；如果全部目标落在同一程序区且未饱和，通常仅有 Z=C*E 可辨识，C 与 E 受 prior 支配。C/E 的输出不能直接作为“已确认仪器故障”。

## 8. 隐藏故障、关闭与固定偏差应分别诊断

### 故障

故障只下降 E，不直接改变 B 的程序档。参考普通卡效率乘子 .4–.7，stress .3–.5。它持续到修复/下一故障，不像正常天气 AR 一样迅速回归。可以对 `log E` 做有持续跳变的变化点检测，并将地震公告作为另一个 E 跳变原因。报告返回 correct/repaired，具有直接信息价值。

一个可计算的报告阈值：若故障 posterior 为 p，正确奖励 R，后续修复能保住 V，错报代价 F，则当 `p(R+V) > (1-p)F` 时报告。实际 false-report free allowance 从初始化读取；L1–L4 为 2 次，正确报告才清零 false count。免费机会不宜无条件一次性用完，尤其 early survey 故障 onset prior 很低时。fault detection 不应要求 60 条独立目标样本才响应，因为同曝光 hits 高度相关，迟几个夜可能损失很多科学分。

诊断曝光可混合高 flux 已饱和目标和低 flux 未饱和目标。饱和目标的得分倍率可以判档，低 flux 目标测 Z；若能确认 B 仍高但 Z 大幅下降，支持效率异常。该信息与 earthquake 当前公告一起判别。

### 关闭

`hit_count` 是几何命中数，与天气是否可观测分开。几何有效 hit 在天气关闭/地形遮挡时仍出现在 hits 中，score 可以是 0。仪器故障效率不会降到 0，所以单纯零分不是故障证据。

- 有多个高空、分散方位 hits 且全部 0：背景关闭或 ALL 关闭；结合公告，短等待到后续 slot 探测。
- 只有一部分方向 hits 为 0，别处 positive：更新方向遮挡 posterior。
- 未出现在 hits 中：高度或光纤几何失败，检查 fixed pointing offset。

### 固定指向偏差

参考 stress offset 在 alt/az 上各为 `Uniform(-.002,.002)` rad，最大约 ±0.1146°，整季固定。runner 在曝光起点把偏差加到命令指向，之后跟踪固定 RA/Dec；目标要在整次曝光中满足最低高度。

虽然反馈不返回 fiber_id，但每个 target 一次只分配到一个 fiber；我们记录上一轮 assignments，因此能从 target_id 找回它原先被指派的 fiber。使用该 fiber 的矩形 gnomonic 区域和 hit/miss 布尔值，可维护偏差候选集合：

```text
hit  ⇒ classify(target | command + delta) == assigned_fiber
miss ⇒ classify(target | command + delta) != assigned_fiber
```

先排除曝光末段降到高度门槛导致的 miss。41×41 或 81×81 的偏差网格仅几千候选，对每轮 assignments 批量计算后过滤；多个不同时刻/方位的观测会逐渐收紧 delta。若没有 miss，通常只得到包含 0 的区域，无法确认偏差为 0。更安全的指派使用剩余 delta 区域下仍在同格的目标；必要时用少量靠格边界的目标获得信息。对于目标密集区，也可选择 offset posterior 下期望 hit 数最大的指向。

## 9. 请求及压力事件分布

请求未来 target pool 是公开目录经独立请求流 shuffle 后的池。每个请求取尚未使用、在窗口内几何可达的目标；默认排除 required，并排除 flux 过低且在理想条件下也达不到门槛的目标。它不检查未来天气。

默认请求数量是 `min(6,max(1,n_nights//14))`，窗口 2 夜，每次 8 个目标、完成至少 6 个、奖励 100；实际设置可覆盖。issue nights 由季长和请求数量确定，首夜无请求，末 deadline 后留一夜。若目标不确定，提前保留可用时间比刻意预观测某些目标有用，因为请求必须由窗口内的曝光完成，历史最高分不能直接领请求奖励。

data-loss 在参考 stress 模式由第一场地震触发。独立随机 i,j∈[0,1] 排序后拒绝 `j-i > x`，删除 observe-action 索引 `[floor(iN),floor(jN))`，wait 不计入 N。这个删除区间不是“最近 x%”，可能落在任意历史位置；曝光次数随策略改变 N，因此用当前一套策略的丢失 action 绝对编号硬编码会失效。状态重同步是公开事实，应重放账本后优先修复损失的 required/有时限目标。

## 10. L1–L4 已公布 truth 的描述统计

下表仅供离线开发，不用于在线策略读取。site Z 是未乘月光/airmass、包含未修复原始故障/全局事件/地震的 `eff*trans*sky/(seeing*.68)`，不是最终每目标 Q。

| 卡 | 目标/required | slots/关闭 | 请求 | site Z 中位数 | P10–P90 |
|---|---|---|---:|---:|---|
| L1 | 7800/390 | 977/71 | 2 | .6197 | .4262–.9986 |
| L2 | 8600/430 | 1076/97 | 2 | .3819 | .2670–.7719 |
| L3 | 8700/435 | 1091/118 | 2 | .4688 | .2131–1.0465 |
| L4 | 8800/440 | 1106/112 | 2 | .4169 | .2474–1.0469 |

这些中位数明显受故障影响，不能作为修复后的长期天气 prior；也说明低效故障识别可能比进一步精调一个固定曝光时长收益更大。

## 11. 进一步优化的合理实验

短期先比较：固定质量 / feedback scalar Z / C-E 联合反演；固定余量 / 偏差候选过滤；单步收益率 / 考虑目标截止和请求窗口的 Beam 或滚动整数规划。每种改动使用相同卡和相同 wallclock 测量完成分、required 缺失、请求奖励和报告罚分。

更大的 GPU 适合在独立生成的多 seed 环境上训练预测 Z、fault posterior 或有限前瞻动作价值，也适合批量情景搜索。训练输入必须包含可在线获得的历史、公告、预报和几何；禁止把未来 truth 当特征。训练标签可以用完整真值生成，因为部署只运行预测模型。应以留出生成配置/season/seed 的成绩验证，防止学习 L1–L4 这四条轨迹的 id 或时间表。

目前 AR 和条件事件分布已经给出强的显式模型；先验证传统滤波+情景规划的收益，再判断神经网络能否改善建模残差，避免只增加计算量而没有实际分数增益。
