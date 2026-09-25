# 滚动投影 DP 的安全状态剪枝

对固定的 key 集合、请求分支、容量价格和 `theta`，原滚动 DP 在状态 `(u, M)` 上求从时刻游标 `u` 开始的剩余最大约化得分；`M` 是已完成首次成功观测的 key 位集合。本实验**不改目标函数、弧、deadline 的起点判定或滚动时间窗**，只跳过不可能位于任何完整可行路径上的 `(u, M)`。

## 两条必要条件

对 key `i`，扫描与原 DP 完全相同的成功弧，并保留原规则 `start < key_deadline_unit[i]`。令：

- `first_end[i]` 为这些弧的最早结束游标，无弧则为 `n+1`；
- `last_start[i]` 为这些弧的最晚起始游标，无弧则为 `-1`。

若从初态到达 `(u, M)`，每个 `i∈M` 必有一次成功观测已经结束，所以必须有 `first_end[i] ≤ u`。若 `(u, M)` 后还能满足所有已承诺的请求，每个未进入 `M` 的强制 key `i` 必能在未来首次成功观测；其弧起点必须满足 `start ≥ u` 且 `start < deadline[i]`，所以必须有 `u ≤ last_start[i]`。弧的终点可以越过 deadline，和原 DP 一致。

令 `allowed(u)={i:first_end[i]≤u}`，`forced(u)={i:mandatory 且 u>last_start[i]}`，则只枚举满足 `forced(u)⊆M⊆allowed(u)` 的 mask。其余状态既不能出现在初态出发的有效前缀，或不能接上满足强制请求的后缀，不会影响根值。等待、天气中断与重复观测均不改变 `M`，因此同样适用。滚动缓存每行先清为 `NEG_INF`，防止已跳过状态的旧值被转移读取。

这是必要条件剪枝，不宣称枚举的每个 mask 都可达。它不把问题变为独立天区，也不改变上界的数学含义。

## 对拍与耗时

使用同一已完成标量审计的容量价格文件、`theta=135` 分，比较原 `conditional_projected_dp_ring` 和新 `conditional_projected_dp_pruned`。两个 RQ0004 分支均逐分相等；另有 200 个随机小型时间 DAG 根值逐分相等。机器上同时有别的计算任务，因此耗时只作实测参考。

| Key 数 | RQ0004 分支 | 原/新共同上界 | 原 ring | 剪枝 ring | 加速 | 保留的时间×mask 单元 |
|---:|---:|---:|---:|---:|---:|---:|
| 14 | 0 | 21,414.16 | 24.65s | 24.52s | 1.01× | 65.83% |
| 14 | 1 | 21,415.16 | 27.45s | 21.48s | 1.28× | 65.83% |
| 15 | 0 | 21,370.59 | 77.09s | 35.19s | 2.19× | 54.92% |
| 15 | 1 | 21,371.59 | 61.84s | 33.95s | 1.82× | 54.92% |

代码见 [`projection_ring_state_pruning.py`](projection_ring_state_pruning.py)，随机对拍见 [`test_projection_ring_state_pruning.py`](test_projection_ring_state_pruning.py)，逐次详细数据见 [`results/projection_ring_state_pruning.json`](results/projection_ring_state_pruning.json)。更大 key 集合可把新函数作为 `_conditional_bound(..., dp_function=...)` 传入；需要复核相应分支与旧 ring 的根值。
