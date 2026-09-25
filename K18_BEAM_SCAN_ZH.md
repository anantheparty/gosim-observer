# K18 投影上界的三种子 beam

K17 的 48 个单 key 扩块已穷尽，前三名新增 key 分别为 `T00045`、`T00001`、`T00043`。固定已认证 K16 集合，以这三种 K17 集合为种子，各自加入所有仍未在集合中的天区；按新增二元组的无序集合去重，恰好得到 **138** 个 K18 投影问题。对每个问题独立计算完整的两分支整数上界；多个有效上界的最小值仍是有效上界。这个 beam 是收紧公开固定实例上界的方法，不等于枚举原排程的全部解。

每个 worker 使用已审计的完整成功弧、天气中断弧、容量价格和 `theta=135` 个百分之一分，并用安全 mask 剪枝的滚动时间 DP。只有 RQ0004 两分支的全部 16 个 DP 参数逐项一致时才共享 DP；新增 key 含 `T00004` 或 `T00012` 时，两分支分别计算。每组有独立的 JSON 整数账本、输入 SHA256、源码 SHA256、原子检查点与超时/失败记录。

## 单组先导

18 位 bit17 的 full matrix、原 ring、剪枝 ring 在四个高位小图逐分相同；记录见 `results/projection_pruned_bit17_k18_test.json`。在 Rhodes1 新的独立源码快照上，`T00045+T00001` 的先导得到全 17 请求上界 **21,282.84**：两分支分别为 `2,128,184 / 2,128,284` 个百分之一分，其中外部项 `1,361,571 / 1,361,671`，共用 DP 根值 `368,403`，请求奖励 `392,000`，theta 常数 `6,210`。完整账本是 `results/practice_k18_t45_t1_pilot.json`；远端和本地文件 SHA256 均为 `adc45ccb4b71b6b86d65d954494ccee0e619bfe49f132fb386d207c43042e645`。单核耗时 `450.1s`，输入 SHA256 `92df02537c91b75db3de0bb8ba02f9185a34d097d2fc48ccb490fb9a310f478e`。

先导的必要状态数是 `3,419,185,641` 个 mask×time 单元；`parallel_k18_beam_scan.py` 在运行每组 DP 前，仅从成功弧的 `first_end`、`last_start` 计算同一安全剪枝条件下的状态数，先完成预计成本较低的组。这只决定调度次序，不参与上界数值。先导状态数已与 `mask_count_profile` 独立逐项核对相同。

## 长任务

Rhodes1 的独立目录是 `/home/shu/gosim-observer-research/key_projection_k18_20260925`。tmux `gosim_k18_beam_20260925` 中已启动 24 个 worker，单组 `7200s` 超时，总计 `32400s`（9 小时）截止；先导完成后立即启动。状态与每组账本目录：`/home/shu/gosim-observer-research/key_projection_k18_20260925/results/k18_beam_20260925`；实时状态 `status.json`，各组在 `cases/Txxxxx_Tyyyyy.json`，日志 `/home/shu/gosim-observer-research/key_projection_k18_20260925/k18_beam.log`。中断后以同一命令重启会核验并复用已完成检查点；失败组不计入有效上界。

计划复制在 `results/k18_beam_plan.json`，计划 SHA256 是 `13c28429344ce3cdca9c0d82d0d43f178505780641f40d21873c5567ae35cc0d`。远端 41 个场景、评分器、价格及 K17 总证书文件的 SHA256 清单已复制为 `results/k18_beam_input_files.sha256`，本地逐文件核验一致，清单本身 SHA256 `e6c85da570943702c4dbd76e487142d00286fb93fbd73aa24f9a1335c740159e`。K17 远端源码快照保持不变。
