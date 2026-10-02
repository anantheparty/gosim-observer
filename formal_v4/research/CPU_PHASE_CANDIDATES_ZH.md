# CPU 局部玻璃相位候选原型

实现：`cpu_phase_candidates.py`，冻结 SHA256
`3d3b20745eff3979a3954ffcbaca129373930d278825b6c895b83883c3bae67e`。
依赖只有 Python 标准库、NumPy、现有 `spatial_candidates.py`。运行阶段没有
CUDA、Numba、SciPy、HTTP 或远端依赖。未修改现有 SpatialPlanner、policy、GPU
模块；本原型阶段只做两时点微门检。

后续L1/L4完整同源回放已完成，8与24基础族的相位扩充均增加总分。24族总分6206.367823/6095.293215，比相同基础族旁路分别+110.182435/+174.894729，耗时311/374秒，每卡预算900秒，累计应急0。完整结果与分项见 `results/cpu_phase_pair_20261003/README.md`。

## 接口与固定工作量

```python
from cpu_phase_candidates import CPUPhaseSpatialPlanner

planner = CPUPhaseSpatialPlanner(initialize_payload)
action = planner.choose(snapshot, best_scores, best_factors, env_estimate, active_requests)
prediction = planner.last_prediction
stats = planner.stats
cumulative = planner.cpu_phase_summary
```

`choose` 与 `SpatialPlanner` 接口相同。先调用本次 CPU 基线 `super().choose`，
捕获其 `_evaluate` 的 frozen frame 和正值候选。只有新候选经过原 `_evaluate`
后精确 rate 严格增加 `>1e-12`，才替换基线动作与 prediction。

| env 参数 | 默认值 | 硬限/含义 |
|---|---:|---|
| `cpu_phase_mode` | `phase` | `bypass` 只执行相同配置的基线 |
| `GOSIM_CPU_PHASE_MODE` 环境变量 | `phase` | env 字典未指定 mode 时读取 |
| `cpu_phase_fixed_workload` | `True` | 正常候选循环按工作量完成 |
| `anchor_count` | 8 | 固定模式最多 24；显式 24 会保留 |
| `cpu_phase_top_count` | 4 | 最多 4 个基线高分种子 |
| `cpu_phase_local_target_count` | 50 | 每种子的粗排序池最多 64 目标 |
| `cpu_phase_boundary_target_count` | 24 | 最多 24 目标生成边界事件 |
| `cpu_phase_exact_count` | 16 | 最多 16 个排序候选调用原 `_evaluate` |
| `cpu_phase_batch_size` | 256 | 16–512 个中心一批 |
| `cpu_phase_durations` | 见下文 | 最多 16 个确定性粗时长 |

默认粗时长为 `{tmin,120,240,400,900,1800,seconds_left,baseline_duration}`，
裁到本夜剩余时间、去重。本次两个微门检均为 8 个粗时长，比较全部三个 program。
额外阶段没有按墙钟提前停止，也没有应急阶段，所以 emergency 计数恒为 0。

固定模式将内部基线 `planning_budget_seconds` 设为 `1e9`，完整执行有界循环。
8 anchors 的 L1 基线为 144 次 `_evaluate`，24 anchors 为 400 次。基线与 bypass
使用同一配置。生产原 policy 默认 24 anchors / 0.22 秒墙钟预算；动作保护的范围
是本模块本次基线动作。若需要保留原墙钟预算，设置 `cpu_phase_fixed_workload=False`。
原 SpatialPlanner 只细化最终胜出的一个初始中心，因此增加 anchors 可改变细化路径；
8 与 24 的精细结果不保证相互单调。

累计字典保存 `choose_calls`、`phase_calls`、`phase_candidates`、
`phase_exact_evaluations`、`phase_emergency_count`、`phase_improvements`。
同值也写入 `stats` 中对应的 `*_total` 项。每次的阶段候选、pool 大小、粗时长、
精解数、各 seed 精解数与 build/scan/exact 耗时另行记录，便于同源回放核对工作量。

## 几何与目标池

种子来自基线候选的 rate 降序排列，并要求间距至少 `0.35*pitch`。每个种子
的玻璃北/东边界事件构成两个一维排列，在每个平面排列区间取中点、加入零偏移，
以笛卡尔积生成局部平移。有限 FOV 边界也加入事件。平移幅度分别处于
`[-pitch/2,pitch/2]`，随后归一化为球面中心。平面排列只负责生成中心。

粗扫描与精解均采用现有球面 gnomonic 投影和 `margin >= 0.008°` 玻璃约束。
先把预期实际中心转换成保留七位小数的命令，再恢复预计实际中心评分，
因此 pointing offset 与命令舍入参与几何检查。

种子到任意平移中心的球面距离不超过
`atan(pitch/sqrt(2) * DEG)`；有效 FOV 中目标到该中心的距离不超过
`atan(fov/sqrt(2) * DEG)`。球面三角不等式给出完整局部精解池的保守种子球冠：

```text
radius = atan(fov/sqrt(2)*DEG) + atan(pitch/sqrt(2)*DEG) + 1e-8 rad
```

先按现有有用目标 merit 在全目录计算每个种子的完整球冠池，粗扫描截取最多
50 个目标，并优先保留该种子基线已分配的目标。入选中心精解使用完整球冠池。
本次完整球冠池为 97–190 目标；粗扫描始终是 50。主计算量不再是
`phase_centres × full_catalogue`；全目录只用于少量种子的池提取。

## 评分与数学范围

给定中心、粗时长 `t` 与 program `p`，原 frozen frame 给出
`f_i=min(1,k_i*t)`、`r_i=min(1,k_i*t/safety)`。目标效用为

```text
u_ip = (max(0, weight_i*f_i*program_multiplier_pi - old_score_i)
        + terminal_i(t)) * urgency_i
```

只允许 `t <= up_i` 的目标，每个 fibre 取 `max(0,max_i u_ip)`，将 fibre 总和除以
`t`，再在粗时长和三个 program 上取最大 rate。这样每根 fibre 只分配一个目标。
focus request 的完整 quota regret 与不足 quota 的现有部分估价也逐项保留。
独立 REQ deadline DP 负责跨动作的完整 quorum 证明；本空间模块沿用原单动作请求估价。

粗评分在**给定局部池、固定时长、给定中心**上准确计算上述目标。近似发生在种子集合、
平面事件代表中心、50 目标截断和粗时长集合。最后调用原 `_evaluate`，使用原目标
时长断点、quota 选择与其原有最多 72 个时长断点上限。因此精细阶段的数学范围
与已有 SpatialPlanner 相同。只保证本次返回候选的 frozen rate 不低于本次基线；
没有全球面候选完备性、变化天气保证或整季分数单调保证。

令种子数 `S<=4`、局部池 `L<=64`、边界目标 `B<=24`、粗时长 `D<=16`。
每轴事件数最多 `4B+2`，中心总数最多 `S*(4B+2)^2 <= 38416`。
粗评分主要工作为 `O(P*D*3*(L+n_fibres))`，按最多 512 中心分批，
全目录池提取为 `O(S*N)`，其后最多 16 次原精解。没有将所有目标断点与所有中心展开。

## 2026-10-03 微门检结果

数据使用 `/tmp/gosim_v4_init_l1_math.json` 与同源 GPU bypass L1 的公开历史
`decisions.csv`、`observations.csv`，仅合并评估时点之前结束的 valid observation。
初始无历史；中期时点为 `2026-11-16T04:00:00Z`。未读取 truth 输入。
线程环境 `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`；本机测量不等于生产容器时限证明。

| 基线 anchors | 时点 | 基线 rate | phase rate | rate 增益 | 总耗时中位数 | phase 中心数 |
|---:|---|---:|---:|---:|---:|---:|
| 8 | initial | 0.806001381 | 0.809350270 | +0.4155% | 0.18484 s | 13673 |
| 8 | mid | 0.007641052 | 0.008085582 | +5.8177% | 0.15049 s | 11548 |
| 24 | initial | 0.766621157 | 0.767931212 | +0.1709% | 0.24888 s | 13279 |
| 24 | mid | 0.008595035 | 0.009119232 | +6.0988% | 0.23300 s | 13517 |

8-anchor 各时点重复五次，24-anchor 各重复三次，动作与工作量一致。另在每次
`SpatialPlanner._evaluate` 人工加入 2 ms 延迟，8-anchor 初始总耗时升至 0.77130 s，
动作、基线 144 次精解、phase 13673 候选、额外 16 次精解完全一致。

通过的交叉核验：

- bypass 动作和 prediction 等于相同固定预算配置的原 SpatialPlanner。
- 返回动作的全部目标通过球面玻璃命中、fibre 身份和曝光可见时长检查。
- 非零 pointing offsets 的舍入命令同样通过球面检查。
- 独立 Python 标量评分与批量 NumPy 评分比较：两时点各 32 中心、5 个粗时长、
  3 programs，focus quorum 为无/1/3/17（包括超过 fibre 数）均通过；最大绝对差
  `2.22e-16`。
- 进程峰值 RSS `95,420,416` bytes，包含微门检载入的公开历史和五次结果。

完整微门检数据在 `/tmp/cpu_phase_microbenchmark_l1_20261003.json`，包含动作、
每次统计、累计统计、源文件/payload SHA256、历史输入路径与软件版本。
L1/4 整卡同源门检由独立 paired runner 继续执行。
