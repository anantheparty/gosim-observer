# 有限全局列定价：PRO 6000 实机基准

## 测试范围

只使用公开 alpha 的 10,000 个目标、site 和首夜夜历，在 2026-10-05 01:00 UTC 计算公开几何与整曝光可见性。20 种时长（60–3600 秒）、3 种 program，values 是明确 synthetic 的非负 science/quota/request dual-incidence 权重，**不是实际科学分或比赛成绩**。32,768 个候选指向来自公开目标附近的有限网格，零仪器指向偏差。

使用 root 的 `interval_column_pricing.py`，固定输入/源码 SHA，owned `elevatia-wsl` → Windows Python 3.13.6 / NumPy 2.2.6 / Numba CUDA 0.67.0，在独立 `ownedbenchmark/global_pricing_20261003` 目录执行。没有 API choose、服务导入/重启、隐藏产品读取或功率限制变更。

## 同批 CPU / CUDA 全量核验

热 GPU 时间包含输入检查、分配、host→device、计算与结果回传；每规模连续三次完全相同输出，表中为中位数。CPU 用同一保存的 NPZ 批次，单线程 BLAS；表中 CPU 时间为实际定价函数时间，不含子进程启动。

| 指向数 | 时长×program 列数 | target×pointing 对 | CPU | GPU 热运行 | 同比加速 |
|---|---:|---:|---:|---:|---:|
| 128 | 7,680 | 1,280,000 | 205.36 ms | 27.94 ms | 7.35× |
| 512 | 30,720 | 5,120,000 | 773.70 ms | 32.14 ms | 24.07× |
| 4,096 | 245,760 | 40,960,000 | 7.2366 s | 47.81 ms | 151.35× |

所有三个规模全量 CPU/CUDA 对照通过，最大 absolute error 分别 1.14e−13、1.14e−13、1.71e−13。另恢复 9 个抽样列的 121 条 assignment，使用独立官方 `FiberGrid.tangent_offsets/classify_offset` 和 `min_altitude_during` 检查，全部通过，恢复总价最大误差 5.68e−14。

首次 GPU 执行采用新时间戳 NumPy/Numba benchmark 缓存目录：128 指向首次调用含 context/JIT/传输/计算/返回为 **696.94 ms**，模块导入 **1.2456 s**。它是新 NumPy/Numba 进程的首次调用测量，没有声称重置整台机器或驱动缓存。

整个 benchmark 16.07 秒；CPU 核验子进程累计 wall time 9.98 秒，小于 30 秒限额。

## 大批 GPU-only 扩展

32,768 指向、1,966,080 个有限列：**155.37 ms**，实际执行，低于 10 秒限额。此规模没有全量 CPU 同比，所以不填写加速倍数。

每个指向扫描 10,000 个公开目标，327,680,000 个 target×pointing 对；方向不落入 field 的对提前返回，不能把 20×3 的理论上限检查次数说成实际 atomic 更新次数。

CUDA workspace 上限参数 256 MiB；该批 cells 为 32,768×20×3×16×8 = **240 MiB**，只回传 totals **15 MiB**。values 本身 4.8 MB，另有 vectors、visible、basis 与主机数组。该测试没有遇到显存不足。

## 功率、显存与采样限制

`nvidia-smi` 全部 86 条有效采样都显示 power limit **600 W**；观察到功耗 103.31–107.50 W，GPU utilization 最大 6%，temperature 41°C。整机 GPU 已用显存基线 11,005 MiB，采样峰值 11,794 MiB，总显存 97,887 MiB；这是设备 aggregate，不全部归于该 benchmark。

这里 GPU 热调用只有约 28–155 ms，CPU 同比核验在调用之间占大部分时间。功耗/利用率采样是设备窗口平均值；观察范围不能当作短 kernel 的峰值，也不能据此推断被低功率限制。没有为了拉高功耗额外跑持续负载，也没有改任何设置。

## 含义与限制

GPU 对**给定 values 的大量有限指向定价**有很大实际加速，最有价值的是跨夜 master 的大批列定价。它没有加速完整 NP-hard 全局排程的所有步骤，也没有证明有限网格外的连续全局上界。真实 profile/科学增益/required/REQ incidences 的构造和 master 求解仍要另计。

小批主要受准备/传输影响；4,096 指向的实测 151×只适用于这份相同 synthetic 工作量，不泛化为整个比赛算法加速倍数。

## 文件

- `benchmark_result.json`：未经摘要替代的完整实机时间、CPU/CUDA误差、oracle、power 采样。
- `prepared/workload.npz` / `workload_metadata.json`：固定公共几何与 synthetic 输入、种子和来源 SHA。
- `hardware_manifest.json`：测试源/输入/输出与当前仓库源 SHA。
- 生成与执行脚本位于 `research/global_pricing_hardware_benchmark.py`；prepare 会在独立目录复制固定公开 oracle 和 pricing 源，不导入任何 production service。
