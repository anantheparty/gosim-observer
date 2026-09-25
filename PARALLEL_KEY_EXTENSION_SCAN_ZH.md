# K16 全候选扩块扫描

固定已认证的 16 个 key 和容量价格、`theta=135` 个百分之一分，逐个把余下 48 个天区加入 key 集合，求公开 `dev-reference` 实例中所有 17 个可得请求都获奖时的严格投影上界。每个候选是一个独立有效的上界证书；扫描所有候选是选择下一层 key 集合的搜索，不是证明这些候选穷尽了原问题的排程。

扫描使用 `projection_ring_state_pruning.py` 的安全 mask 剪枝与 10 行滚动 DP。若新 key 不含 `T00004` 或 `T00012`，`projection_branch_merge.py` 在逐项核验 16 个 DP 输入参数后复用 RQ0004 两分支的 DP 根值；每一分支仍分别计算非 key 的外部约化得分，分别给出整数总分。若 key 含这两个备选天区之一，两分支各自运行 DP。

在并行运行前，`parallel_key_extension_scan.py verify` 用同一剪枝算法复算 K14、K15、K16 证书，逐字段核对两分支的整数分项、请求掩码与截止时间。2026-09-25 本机核对结果分别为 `2,141,516`、`2,137,159`、`2,133,124` 分（单位均为 **分值的百分之一**）；详见 `results/parallel_key_scan_local_verify/verification.json`。17 位高位也已用独立 Python 递归、完整矩阵 DP、旧 ring DP 和剪枝 ring DP 的小图对拍。

`scan` 模式默认 24 个 worker、单候选 7200 秒超时、总 28800 秒（8 小时）截止。每个候选的完整整数账本、16 参数 DP 输入 SHA256、分支输入 SHA256、源码 SHA256、运行成本和峰值内存写入独立原子 JSON；扫描状态保存在 `status.json`，中断后重新运行会验证并复用已完成候选。失败和超时会记录，不能当作上界结果。结果只在本地和 Rhodes1 计算，没有提交排行榜。

远端运行目录为 `/home/shu/gosim-observer-research/key_projection_20260925`，扫描状态目录为 `results/parallel_k17_scan_20260925`。先单独计算 `T00043`，必须与原 ring 的两分支 `2,130,317 / 2,130,417` 分完全一致；再启动全部候选。全扫后按照上界值和 key 集合差异选择少量种子考虑 K18 扩块；是否继续取决于实测的单位计算成本与上界下降量。

远端运行快照的 40 个场景、评分器、价格和基线证书文件的 SHA256 清单保存在 `results/parallel_key_scan_local_verify/input_files.sha256`，已在本地逐项 `sha256sum -c` 核验一致。它与各候选结果内的完整 DP 参数 SHA256、源码 SHA256 一起固定本轮复算输入。

## 2026-09-25 远端长任务

单 worker 先导 `T00043` 已完成，与独立原 ring 的两分支结果逐项相同：整数上界 `2,130,317 / 2,130,417`，外部约化得分 `1,382,109 / 1,382,209`，共用 DP 根值 `349,863`，请求奖励 `392,000`，theta 常数 `6,345`。候选输入 SHA256 为 `d316554faf2ea525e1a632c5952beb36fb722a858a4766abe23595631c90272d`，worker 耗时 `268.8s`。单独原子检查点在远端 `results/parallel_k17_scan_20260925/cases/T00043.json`。

48 个候选的全扫已在 Rhodes1 的 tmux `gosim_k17_scan_20260925` 启动；24 个 worker，每候选 `7200s` 超时，preflight 通过后总搜索截止 `32400s`（9 小时）。它会复用上述先导检查点。远端绝对目录：

- 状态与逐候选账本：`/home/shu/gosim-observer-research/key_projection_20260925/results/parallel_k17_scan_20260925`，其中 `status.json` 实时汇总、`cases/Txxxxx.json` 各自原子落盘；
- 日志：`/home/shu/gosim-observer-research/key_projection_20260925/k17_scan.log`；
- 输入快照 SHA 清单：同一状态目录的 `input_files.sha256`，文件本身 SHA256 为 `564c31b4ae49e3c37af58ba7036b9494054f98e58147eb8e5b1ce9252e7e6f30`。

若部分 worker 失败或超时，`status.json` 标为 incomplete 并保留失败详情；再次运行相同命令会校验并复用成功的检查点。扫描中各候选只是全 17 请求分支的上界；与已有恰 16、至多 15 请求证书取最大值，才是无条件上界。

远端 preflight 已复算 K14/K15/K16，整数结果和每个 DP 输入 SHA256 均与本地完全相同。远端核验账本、48 候选计划分别复制为 `results/parallel_key_scan_remote_verify.json`、`results/parallel_key_scan_remote_plan.json`；计划 SHA256 是 `892619e30eeffcb8cce7fe9fbde014a80ad3a2b5ac1fd78b81340cc36aadbc0b`。24 个 worker 已全部实际启动。

## 全候选结果

扫描已 **48/48 完成、0 失败**。用 `aggregate_parallel_key_scan.py` 对每个原子结果重新核验整数分项、输入哈希、分支共享条件、候选覆盖及最终排序后，汇成 `results/practice_parallel_k17_all_candidates.json`（SHA256 `edbaa0aca6f28ad18238ef059539b0099489b8293ab6ccf3196bef0358c81f7b`），其中包含 48 条候选的完整整数摘要及每个远端 case 文件的 SHA256。最佳完整账本单独保存为 `results/practice_parallel_k17_best_t45.json`（SHA256 `1e599c6cdcc4eee11d55864df4e63e21ff1576330b16b9c9188e9eb5596985bc`）。

最佳新增 key 是 `T00045`，全 17 请求上界为 **21,301.92**；两分支整数分项分别是 `1,381,835 / 1,381,935` 外部项、同一个 `349,912` 投影 DP 根值、`392,000` 请求奖励及 `6,345` theta 常数，合计 `2,130,092 / 2,130,192` 个百分之一分。紧随其后的是 `T00001=21,302.26`、`T00043=21,304.17`。结合恰 16 请求上界 `21,238.47` 与至多 15 请求上界 `21,236.70`，当前无条件严格上界是 **21,301.92**；与已有可行分数 `21,119.494551` 的间隙是 `182.425449`。
