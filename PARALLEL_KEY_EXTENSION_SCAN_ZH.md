# K16 全候选扩块扫描

固定已认证的 16 个 key 和容量价格、`theta=135` 分，逐个把余下 48 个天区加入 key 集合，求公开 `dev-reference` 实例中所有 17 个可得请求都获奖时的严格投影上界。每个候选是一个独立有效的上界证书；扫描所有候选是选择下一层 key 集合的搜索，不是证明这些候选穷尽了原问题的排程。

扫描使用 `projection_ring_state_pruning.py` 的安全 mask 剪枝与 10 行滚动 DP。若新 key 不含 `T00004` 或 `T00012`，`projection_branch_merge.py` 在逐项核验 16 个 DP 输入参数后复用 RQ0004 两分支的 DP 根值；每一分支仍分别计算非 key 的外部约化得分，分别给出整数总分。若 key 含这两个备选天区之一，两分支各自运行 DP。

在并行运行前，`parallel_key_extension_scan.py verify` 用同一剪枝算法复算 K14、K15、K16 证书，逐字段核对两分支的整数分项、请求掩码与截止时间。2026-09-25 本机核对结果分别为 `2,141,516`、`2,137,159`、`2,133,124` 分（单位均为 **分值的百分之一**）；详见 `results/parallel_key_scan_local_verify/verification.json`。17 位高位也已用独立 Python 递归、完整矩阵 DP、旧 ring DP 和剪枝 ring DP 的小图对拍。

`scan` 模式默认 24 个 worker、单候选 7200 秒超时、总 28800 秒（8 小时）截止。每个候选的完整整数账本、16 参数 DP 输入 SHA256、分支输入 SHA256、源码 SHA256、运行成本和峰值内存写入独立原子 JSON；扫描状态保存在 `status.json`，中断后重新运行会验证并复用已完成候选。失败和超时会记录，不能当作上界结果。结果只在本地和 Rhodes1 计算，没有提交排行榜。

远端运行目录为 `/home/shu/gosim-observer-research/key_projection_20260925`，扫描状态目录为 `results/parallel_k17_scan_20260925`。先单独计算 `T00043`，必须与原 ring 的两分支 `2,130,317 / 2,130,417` 分完全一致；再启动全部候选。全扫后按照上界值和 key 集合差异选择少量种子考虑 K18 扩块；是否继续取决于实测的单位计算成本与上界下降量。
