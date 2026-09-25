# GPU 投影 DP 原型

`gpu_projection_dp.py` 将现有 16 参数整数投影 DP 的时间–掩码递推搬到 CUDA。行动弧、容量价格、请求分支和非关键天区外部项仍由现有审计代码构造；这个原型只替换 `_conditional_bound(..., dp_function=...)` 的 DP 函数。

## 依赖与运行

- 使用独立 Python 环境及可用 CUDA 驱动，避免改变 CPU 证书环境。本地模拟测试使用 `numpy==2.0.2`、`numba==0.60.0`；Windows 原生最小 CUDA 核已在 `numba-cuda==0.30.4`、`numba==0.67.0`、`cuda-core==0.6.0`、`numpy==2.2.6` 环境运行。
- Windows 没有 Unix `resource` 模块。GPU 原型入口仅为现有代码的峰值 RSS 读取补一个返回零的兼容模块，不影响评分或整数 DP 输入。
- 没有 GPU 时可运行小图模拟测试：

  ```bash
  NUMBA_ENABLE_CUDASIM=1 python3 gpu_projection_dp.py self-test
  ```

- GPU 能正常执行 CUDA kernel 后，逐分对照已保存的公开实例证书：

  ```bash
  python3 gpu_projection_dp.py verify --k 14 --k 15
  python3 gpu_projection_dp.py verify --k 16 --k 18
  ```

  `verify` 对每个 K 的两条 RQ0004 分支核对外部项、请求项、常数项、DP 项、掩码、期限和总界。两分支的完整 DP 参数由 `projection_branch_merge.py` 逐项比较；相同时只运行一次 GPU DP。期望的总上界（单位为百分之一分）为 K14 `2141516`、K15 `2137159`、K16 `2133124`、K18 `2128284`。模拟器逐线程执行，不能用于完整 K14 及以上实例的性能或耗时对拍。

## 递推与并行安全

每个 `(u, mask)` 只读取更晚时间的状态，故同一时间的掩码可并行。正式实例的最短完成弧为 3 个 150 秒格，天气中断与等待均跳至下一 6 格时隙边界。代码在运行时检查这些条件，然后每个时隙逆序发射两波 CUDA kernel：先算偏移 `3,4,5`，再算 `0,1,2`。不满足条件时自动退回逐时间格 kernel；强制 `wave3` 时会报错。

CPU 的滚动表高度是 `H=max_arc_span+1`。三时间格并行时，即使真实 DAG 没有同波依赖，某个未来状态也可能与同波另一个写入状态取模到同一行。因此 GPU 波次模式采用 `H=max_arc_span+3`。任何同波写入时间与另一线程所读未来时间之差至多 `max_arc_span+2`，小于 `H`，不会发生环形表别名。正式 K18 输入检查得到 CPU 高度 10、GPU 波次高度 12；`12×2^18×8 = 24 MiB`。DP、弧收益、罚分均采用整数分，GPU 状态表为 `int64`。

## 本地验证

`self-test` 将固定小图与随机小图的 CUDA 模拟结果同时对照 CPU 完整 ring DP 和剪枝 ring DP，并核对 `serial`、`wave3`、`auto` 三种发射方式。另有一条 1 格完成弧用来验证自动退回和强制波次拒绝。开发时还对 100 个额外随机小图逐分核对通过。正式 K18 的弧结构经本地只读检查满足波次条件；完整 K14/K15/K18 的真实 GPU 对拍须待 CUDA kernel 能在目标机器运行后执行。

本机还以保存的 DP 整数代入 `verify` 比较器，重新构建 K14/K15/K16/K18 的两条分支；四组外部项、请求项、掩码、期限与总界逐分一致。这项检查验证证书接线和分账，不能替代真实 GPU DP 对拍。
