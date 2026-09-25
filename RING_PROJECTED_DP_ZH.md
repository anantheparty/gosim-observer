# 十行循环缓冲的精确关键天区 DP

本实例的 [条件关键天区投影](REQUEST_PROJECTION_K14_PILOT_ZH.md)在 47,568 个 150 秒游标上作逆时间 DP。原实现保存每个游标的全部 $2^{|K|}$ 个状态。逐弧审计发现：918,757 条完整曝光边跨度为 3–9 格，850 条天气中断边跨度为 1–8 格，等待到下一时隙末跨度为 1–6 格；所有边严格向前且终点不超过末游标。因此每个状态只读取未来最多 9 格的数据。

[新实现](bounds_request_projection_ring.py)将 DP 表换成 10 行循环缓冲，索引为 `u % 10`。倒序处理游标 $u$ 时，可能后继 $v$ 均满足 $u+1\le v\le u+9$，其模 10 的行与 $u$ 不同，尚未被覆盖。预置终点 $n$ 的终止行；当更早的 $u=n-10$ 覆盖该行时，$n$ 已不可能再是它的后继。提前终止直接读取独立 `terminal[mask]`，因此不受行覆盖影响。关键块首次成功、带标签复访、请求截止、等待 OR 掩码和天气边的递推值完全沿用原式。程序在运行时从所有完整与中断边重新计算最大跨度，若等待边超过缓冲宽度则报错。

内存从 $8(n+1)2^{|K|}$ 字节降为 $8(1+H)2^{|K|}$ 字节，本实例 $H=9$，时间维缩小约 **4,757 倍**。例如 $|K|=15$ 的数值 DP 表约由 11.6 GiB 降至 2.5 MiB；此外仍需场景、弧、评分器与中间数组。这个改变不调整目标函数，也不删除弧。

## 逐分对拍

同一审计价格 SHA-256 `a4c1b7f9904a1ec0ae9074c349197231274e492676098614fc81cf32888ae480`、统一 $\theta=135$ 个百分之一分，环形与全时域矩阵分别独立求以下两条全 17 请求分支：

| 关键块数 | `RQ0004=T00004` | `RQ0004=T00012` | 证书 |
| ---: | ---: | ---: | --- |
| 8 | 21,793.30 | 21,794.30 | [逐分对拍](results/practice_projection_ring_k8.json) |
| 14 | 21,414.16 | 21,415.16 | [逐分对拍](results/practice_projection_ring_k14.json) |
| 15，新增 `T00027` | 21,370.59 | 21,371.59 | [双实现对拍](results/practice_request_projection_k15_certified.json) |
| 15，新增 `T00062` | 21,373.81 | 21,374.81 | [双实现对拍](results/practice_request_projection_k15_certified.json) |

十五块的四个分支不仅总分相同，外部科学残值、容量价、请求奖励、$\theta$ 常数、关键块 DP、必需位掩码和截止时间单位也全部一致。本地 ring 两候选总耗时 284.4 秒、进程峰值 202.3 MiB；Rhodes1 上两个全时域独立进程分别约 413–431 秒、峰值约 12.1 GiB。机器不同，不能直接由这些总时间推断算法速度。八块和十四块在同一 Mac 上对拍时，ring 单分支略慢，节省的是内存。

十五块最佳全请求条件上界为 **21,371.59**。独立 [恰好 16 请求证书](SIXTEEN_REQUEST_RESIDUAL_ZH.md)给出 21,304.66，[至多 15 请求证书](FIFTEEN_REQUEST_RESIDUAL_ZH.md)给出 21,289.55。三类分支取最大，严格**无条件上界为 21,371.59**，距已验可行分数 21,119.494551 尚有 **252.095449 分**。此证明只用于公开 `dev-reference`、`mechanics=False` 实例。

复算：

```sh
python3 bounds_request_projection_ring.py --out results/practice_projection_ring_k8.json
python3 bounds_request_projection_ring.py --keys T00018,T00029,T00030,T00031,T00024,T00021,T00040,T00015,T00048,T00032,T00016,T00010,T00047,T00011 --out results/practice_projection_ring_k14.json
python3 scan_ring_key_extension.py --base-keys T00018,T00029,T00030,T00031,T00024,T00021,T00040,T00015,T00048,T00032,T00016,T00010,T00047,T00011 --extra T00027,T00062 --prior-certificate results/practice_request_projection_k14_pilot.json --expected-base-cents 2141516 --out results/practice_request_projection_k15_ring.json
```

远端全矩阵 K15 两个原始 JSON 保留在 Rhodes1 的 `/home/shu/gosim-observer-research/key_projection_20260925/results/`，其 SHA-256 和逐项对拍摘要并入本地证书；没有在线提交。
