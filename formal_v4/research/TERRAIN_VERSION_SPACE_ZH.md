# 地形：连续参数版本空间，而非永久方向折扣

## 官方模型与公开信息

来源固定到公开代码 commit `e01939d060f304c2a7cf04d9b3e46009b564fc23`：

- [生成器 terrain，604–622 行](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_weather_simulator.py#L604)：每个地形扇区的起始方位角均匀分布，宽度、高度从配置区间均匀采样。事件从季节首槽持续到末槽。
- [方向发布，162–175 行](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_weather_simulator.py#L162)：发布扇区中心最接近的八方位代码。因此 D 约束中心为 `[D−22.5°,D+22.5°)`，不是约束整个方位始终不可用。
- [公告，881–918 行](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_weather_simulator.py#L881)：地形只在 initial 公告发布一次，按 `(event_kind,direction)` 去重。同一个方向可能对应多个扇区，公告没有精确角度或事件编号。
- [公开参考配置](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/reference/v4/v4_weather_stress_config.json)：扇区数 1–3，宽度 30–70°，高度 35–50°。这是可选参考先验，不能当成 α–δ 未公开天气配置的已知范围。

参数写为中心 `c`、宽度 `w`、最大高度 `h`。地形的覆盖集合是

`B(c,w,h)={ (a,z): 0≤a≤h 且 circular_distance(z,c)≤w/2 }`。

被覆盖的样本贡献直接为零；地形 `force_close=false`，没有连续衰减倍率。比如采用上述参考范围时，**高度超过 50° 的方向全部不会被地形遮挡**。短时云、雨、火箭需要独立处理。

本地官方 `runner/challenge/v4_scorer.py:320–400` 的曝光积分按 slot 和事件起止时刻分段，每片最长 120 秒，在片中点重新计算目标 altitude/azimuth 并判断地形。`band_quality()` 不乘地形和仪器效率；地形只能进入 raw quality/factor，不能进入 program-band 判别。

## 正、零反馈的逻辑

设一条有正分反馈的曝光轨迹是 `x(t), t∈[s,e]`。真实模型满足：至少一个有正权重的官方积分样本未被所有地形覆盖。

所以不能将曝光中点当成确定 clear 点，更不能将整个轨迹都当成 clear。安全的必要条件是：**任何一个真实地形扇区都不可能覆盖整次连续曝光轨迹**。如果某个候选扇区覆盖整个连续轨迹，它必然覆盖所有官方积分样本，正分就不可能出现，可以排除它。此条件比精确积分判别保守，但无需知道隐藏事件引入的内部 cuts。

零反馈可能来自天气关闭、其他方向事件、仪器、极低质量及舍入。没有独立正质量证据时，零反馈不硬删除地形假设。数据丢失后，曾收到的正分仍是有效的物理反馈：丢失撤销计分记录，不改变当时的地形。

## 连续参数盒的保守排除证明

`terrain_version_space.py` 对每个发布方向建立连续盒：

`c∈[c_lo,c_hi], w∈[w_lo,w_hi], h∈[h_lo,h_hi]`。

盒覆盖整个先验参数域，不仅是离散中心点。每条曝光划成不超过 60 秒的几何片。高度正弦是 `A+B cos(H)`，端点与上、下中天给出全片高度极值。天球轨迹角速度不超过恒星时速度 Ω，水平坐标度量为

`ds²=da²+cos²(a) dz²`，因此 `|dz/dt|≤Ω/min cos(a)`。

片中点方位到任何时刻的圆周距离不超过 `r=Ω·piece_duration/(2·min cos(a))`；天顶经过时半径取 180°，不做有争议的排除。

若全片高度都在 `[0,h_lo]`，且每片中点到盒中心中值的距离加 `r`、中心半宽都不超过 `w_lo/2`，则**盒内每个参数**都覆盖整个轨迹。正分可排除整个盒。剩余盒是连续可行域的外包络，真实参数所在盒不会被删除。浮点计算留有 1e−7° 保护边界。

`certified_clear(a,z)` 只有在所有剩余盒都不能覆盖该点时返回 True。它是在显式参数域、完整 initial 公告的条件下的证书；False 表示未知，不表示一定 blocked。该 clear 证书允许同方向多个真实扇区。若先验被反馈否定导致方向族为空，模型标记 domain conflict，证书返回 False，预测不继续封锁该方向。

## 数值预测与未来几何

`expected_clear_fraction()` 对剩余连续盒以参数体积加权、盒中点求积，生成 altitude×azimuth 网格。方向之间暂按独立、每个去重方向一个扇区的近似模型合成。它是**外包络上的近似条件预测**，不是精确贝叶斯后验；多个同方向扇区、被保留盒内部分不一致参数都会带来近似误差。

官方 `start` 均匀时，中心 `c=(start+w/2)%360` 也均匀，且独立于 `w`；因此给定 D 后中心在对应 45° 箱内均匀，是参考先验的合理分解。若已知参考扇区数最多 3 且公告恰有 3 个方向，每个方向恰好一个；但未公开配置时不能使用该额外断言。

REQ 未来积分必须在每个未来时刻重算 `altaz(target,t)`，再乘这个地形场。不能把当前的 `.05` 方向折扣贴在目标上延续未来 32 小时；同一个赤经赤纬会随时间经过不同的水平位置。

接口：

```python
terrain = TerrainVersionSpace.reference_prior(directions, latitude, longitude)
# 默认 constructor 使用宽度0–360、高度0–90的宽泛域；reference_prior显式采用例子范围。
terrain.observe_positive(ra, dec, start_utc, actual_duration_seconds, score)
terrain.observe_zero()                       # 只计数，不硬推断
scale = terrain.terrain_scale(alt_array, az_array)
future = terrain.quality_model(times, ra_array, dec_array)  # shape[time,target]
clear_certificate = terrain.certified_clear(alt_array, az_array)
diagnostic = terrain.snapshot()
```

在线只输入已收到的反馈，不读下面的全季诊断。记录 actual duration，不用请求时长；正分对应实际命中的目标，不使用指令指向代替目标赤经赤纬。

## 验证与 δ 诊断

`terrain_version_space_checks.py` 用官方 scorer 构造 150 个随机曝光/真实扇区：149 条正反馈控制中，真实扇区对应连续盒全部保留；公开 altaz 与官方误差最大 `1.14e−13°`。零反馈不改版本空间，高空查询 clear，9400 目标热查询约 0.22 ms；三方向首次地图构建约 33 ms，参数发生排除时才重建。

δ 已完成本队回放共有 12739 条正反馈。只读重放这些反馈后，参考参数域下 NE/E/NW 剩余盒为 `528/392/367`，原来各 540；共排除 333 盒，无 domain conflict。耗时约 1.11 秒。此结果供事后诊断，不能成为重新运行生产策略的未来输入。

δ 初始公告 NE/E/NW 下有 618 条正反馈的曝光中点落在目前永久 `.05` 方位范围内，最高公开 quality 为 1.328205，且样例高度约 79°。这些轨迹证明“整方向始终低质量”不成立；长曝光的中点数据单独不构成精确地形边界。required 的 19 个缺失中，11 个从未分配但冻结质量的公开模型有大量完整达标机会。二者联合指向：应把地形建成时空几何场，再计算真正的单曝光 quota 期限。

## Policy 与 REQ 共用状态的可选接线

`terrain_policy.py` 提供 `CandidatePolicy=install_terrain_policy(BasePolicy)`。它返回独立子类，不改传入类或稳定入口。实例 `policy.terrain_model` 与 `policy.planner.terrain_model` 是同一个对象，`planner.terrain_empirical_blocks` 指向同一个短时账本。

`_ingest_result()` 在原方法清空 pending 前捕捉开始时刻、动作时长与本次 hits。官方 last_result 没有 duration 字段，所以使用 `min(requested_duration, snapshot.now−pending.start)` 得到实际曝光时长；按 observe_index 独立去重，仅命中正分反馈删盒。之后仍调用原反馈和计分账本实现。resync 不撤销物理几何证据。

`_messages()` 先运行原公告/请求账本逻辑，再将已经收到的 terrain directions 加入版本空间，不重置旧反馈。`_target_scale()` 用未来/当前实际 altaz 下的 expected clear 替代所有 `.05/.28` 地形固定折扣，再乘独立临时天气场、1200秒经验黑点场。临时天气的 `.55` 幅度是原有显式条件场景，没有把粗公告变成已知数值；黑点 TTL 也保持现有场景。

REQ 调用 `PublishedFutureField(planner,snapshot,planner.terrain_model, weather_scenario=temporary_weather_scale, empirical_blocks=planner.terrain_empirical_blocks)`，冻结的是已知后验，未来查询再计算几何，公告/预报生效时间由 future field 管理。program-band 不乘此场。

`terrain_policy_checks.py` 用公开δ目录与合成协议检查：原 Base 类未变，planner共享同一模型，全9400目标当前场与PublishedFutureField一致，3600秒请求实际60秒时使用60秒，pending清空前反馈被捕捉，重复feedback幂等。

独立 `agent_terrain_cpu_direct.py` 为CPUphase24候选入口。L1完整gate保存在 `results/terrain_cpu_phase_L1_20261003`；输入源码/配置按SHA256固定在 source_manifest.json，不修改既有phase24对照，不读取全季诊断。

L1完整gate得分6200.856777，对照6206.367823，降低5.511046（约0.089%）。首REQ完成目标数由3/8增至4/8，仍不到6，required仍缺2，官方完整结束wall278.929秒。线上剩SE71、SW324盒，无先验冲突。**单改地形没有通过提高分数的gate，不单独替换当前最佳**；未来REQ需要完整期限DP再验证。L4同一源候选另行验证。

不可变源快照已保存到本地Git `archive/terrain-gate-20261003`，commit `88fb71c351234d48e81e0d105fb571958bb9e345`；source_manifest包含68文件的SHA256、Git commit/ref及路径映射。这个归档不改当前main或共享index。测试完再删除重复agent源码，只保留结果、manifest及必要入口/配置。

同源L4完整结束343.802秒，6080.065472，对照6095.293215，降低15.227743。科学分5830.984582比对照增加33.431822，uniformity罚分少1.340433，REQ/report相同；多漏1个required扣50导致净负。新模型剩E88盒，无先验冲突，391条data-loss失效由原账本正常处理。

差异目标V4T005316（RA93.874940、Dec−60.556861、flux=.05927281）在新解只有562s和1042s两次valid曝光，max factor=.123177；无失效、不是擦线。原phase24在12月3日UTC03:28:31作3547s曝光，quality1.127438、factor.526740完成。**方向模型放开更多科学机会后，必须把这种微弱required的一小时单次quota与稀缺高质量窗口纳入资源规划**。完整对照证据保存于gate_summary.json。重复agent源码已删除，restore_candidate.py可按Git与SHA256重建。
