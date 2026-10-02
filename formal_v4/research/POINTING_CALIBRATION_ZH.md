# 固定指向偏差：从公开命中反馈进行二维辨识

实现：`pointing_calibration.py`。输入只有公开 `initialize.payload`、实际发出的观测动作、曝光起点 UTC 和该次完整 `last_result.hits`。运行模块不读取任务卡文件、天气真值、压力事件真值或随机种子。

## 模型与辨识信号

未知量为整季固定的两个角度（单位为度）：

\[
\theta=(\delta_h,\delta_A),\qquad
h_{\rm actual}=h_{\rm command}+\delta_h,\quad
A_{\rm actual}=(A_{\rm command}+\delta_A)\bmod360^\circ.
\]

给定曝光起点和公开目标 RA/Dec，先计算目标高度角/方位角，再以候选实际指向为中心进行精确 gnomonic 投影。官方按曝光**起点**一次性判定目标所在光纤，后续按恒星时跟踪，曝光期间不存在额外的光纤漂移。

每个已指派目标产生一个布尔观测：目标 ID 在 `hits` 中则为 1，否则为 0。返回的 hit 不含光纤编号，但本次 assignment 唯一，因此能够恢复“命中所指派光纤”的约束。**hit 的 score 为 0 仍为几何命中**：雨、遮挡、零透过率等降低得分，并不删除已经通过几何判定的 hit。

miss 有一个关键例外：官方在几何分类前，排除了整次执行曝光期间最低高度低于公开高度限制的目标。因此不能把这类 miss 当作偏差证据。模块计算端点和曝光期间可能经过的下中天，从而得到精确最低高度；如果低于限制且未命中，就跳过该条负证据。已出现的 hit 始终能提供正证据。执行终点按公开夜晚终点、survey 终点截断。

光纤的 `fiber_area_deg2` 和 `gap_deg` 足以重建精确边长、pitch 和视场范围。模块优先使用这些未舍入的数值，避免公开 `glass_side_deg` 的六位小数在边界附近造成错判。零 gap 的共享边界按照官方 floor 规则唯一归属。

## 公开生成器 prior

官方仓库版本 `e01939d060f304c2a7cf04d9b3e46009b564fc23`：

- [生成器](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/v4_weather_simulator.py)，第 722–738 行：高度、方位两轴各独立均匀采样，写入真值时保留 8 位 rad 小数。
- [参考配置](https://github.com/gosimfoundation/hackathon-survey26/blob/e01939d060f304c2a7cf04d9b3e46009b564fc23/challenge/reference/v4/v4_weather_stress_config.json)，第 79–80 行：两轴最大绝对偏差均为 `0.002 rad`，即 `0.114591559026°`。

这支持默认的二维均匀 prior，但不能证明正式任务卡沿用相同范围。构造器允许配置 prior；当前网格无法匹配所有已知反馈时，模块会扩大范围，默认最多到每轴 ±1°。若仍不一致，输出 confidence=0。普通卡偏差为 0，该点包含在初始网格中。

已审查文件 SHA-256：

```text
v4_weather_simulator.py
b4675ead09e8cf333c12841ac051786c523394d4fb3cfb0b52397ad75dcc753a
v4_weather_stress_config.json
d13006552dd4d2984ad702c28cda1065d8f071e3cdcf5d68c234510f1a59e98e
```

## 求解与不确定性

对第 j 个有效指派，设官方几何谓词为 `H_j(theta)`，反馈为 `y_j`。最大似然问题化为：

\[
\min_\theta M(\theta),\qquad
M(\theta)=\sum_j\mathbf1[H_j(\theta)\ne y_j].
\]

在精确、无噪声模型中，所有 `M=0` 的偏差构成可行域：hit 约束是所指派光纤覆盖区域，miss 约束是其补集，交集可以不连通。全部真值一致时，一个点附近得到相同反馈并不意味着已经唯一恢复偏差。

实现用 NumPy 评估默认 `81×81` 网格。新观测只增加新约束的 mismatch 数；候选支持收缩后细化网格，保留旧候选外两格，再重新检查全部历史。最终选取最优网格点中最接近其均值的一个**真实候选点**，避免直接返回不连通可行域的均值。

返回 `(delta_alt, delta_az, confidence)`。confidence 是支持区域集中程度的启发式指标：

\[
c=\begin{cases}
e^{-r_{95}/(\text{glass}/4)}\min(1,N/24),&\min M=0,\\
0,&\min M>0.
\end{cases}
\]

其中 `r95` 是当前最优候选相对返回点的 95% 最大坐标半径，再加半个网格步长。它不是后验概率，也不是连续偏差的严格置信区间。完整的步长、支持包围盒、约束数、最低 mismatch 和范围扩展次数通过 `diagnostics` 返回。**该实现是数值网格辨识，不提供连续可行域的完整覆盖证明。**

若一次曝光有 m 个有效指派、网格有 G 个点，新反馈更新需要 O(mG)；重新构建网格时需要 O(NG)，N 为累计有效指派数。存储为 O(N+G)。本地 synthetic 测试中，80 次曝光、1280 条约束的整个辨识过程约 0.2–0.7 秒，远低于每卡 900 秒预算。

## 接入方式

```python
calibrator = PointingCalibrator(init_payload)

# 使用上一次实际发出的动作及其曝光起点；不能传本轮结果到达时刻。
delta_alt, delta_az, confidence = calibrator.update(
    previous_action, previous_start_utc, last_result["hits"]
)

# 规划器得到的是希望实现的实际指向，发送时减去估计偏差。
command_alt = desired_alt - delta_alt
command_az = (desired_az - delta_az) % 360.0
```

也可给 update 第四参数传入 `{target_id: (ra_deg, dec_deg)}` 或目标元数据映射。没有完整结果时传 `None`；空列表则表示实际已知“没有任何命中”，两者不同。

指向偏差在报告修复后仍固定；data-loss 状态重同步撤销的是科学分记录，不能撤销已经取得的几何反馈。因此这两种事件不应清空校准历史。调用方必须保证传入动作确实已执行，并保留曝光起点。

## 验证

`python3 formal_v4/research/test_pointing_calibration.py -v`：6 项测试全部通过。

- 使用官方 `v4_fiber_map.FiberGrid` 独立检查 1200 个随机候选的精确几何分类，覆盖 az 环绕及 88° 高度。
- 同一组 hit 使用正常分数或全部零分，得到完全相同的校准结果。
- 全程低于高度限制的 16 条 miss 被跳过，不产生虚假偏差约束。
- 缺失结果不会被误当作 16 条 miss。
- 四组参考范围内偏差，在 80 次 synthetic 曝光后最大坐标误差小于 0.003°。
- 范围外 `(0.31°, -0.22°)` 偏差触发扩大 prior，120 次曝光后误差小于 0.005°。

可复核数值、runtime、种子和源码 hash 保存于 `../results/pointing_calibration_synthetic.json`。synthetic 真值仅用于测试生成布尔 hit；校准器自身只收到公开坐标、动作及 hit。
