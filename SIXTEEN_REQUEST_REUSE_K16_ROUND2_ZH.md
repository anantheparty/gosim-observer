# 恰好 16 个请求奖励：第二轮定向复用

[上一轮证书](SIXTEEN_REQUEST_REUSE_K16_ZH.md)已将恰好 16 奖励的严格上界压至 21,238.47。[本轮机器证书](results/practice_sixteen_request_reuse_k16_round2.json)以 21,200.00 为目标，再审旧界超过目标的分支。33 支完整分割中仅有两支：未获 `RQ0010`，`RQ0004` 分别由 `T00004` 或 `T00012` 见证。

这两支与已经认证的全 17 奖励 K16 DP 拥有完全相同的输入签名，包括关键集合、非负容量价格、弧图、θ、最早终止单元 `42738`、必需/强制掩码和每个关键天区的截止单元。K17 已认证案例的签名也相同；本轮选择复用较早且充分的 K16 DP 整数值 **325,074 百分之一分**。两支仍分别重算非关键天区科学包络、奖励和必罚。

| 未获请求 | `RQ0004` 见证 | 原有效界 | 新 K16 界 |
| --- | --- | ---: | ---: |
| `RQ0010` | `T00004` | 21,237.47 | 21,103.09 |
| `RQ0010` | `T00012` | 21,238.47 | 21,104.09 |

其余 31 支保留旧有效界。合并后**恰好 16 奖励 ≤21,185.62**，由未获 `RQ0018`、`RQ0004=T00012` 的旧界决定。至多 15 奖励有独立界；不能把本证书的 21,185.62 用作全问题上界。没有在线提交。

```sh
python3 bounds_sixteen_request_reuse_k16.py \
  --prior-sixteen results/practice_sixteen_request_reuse_k16.json \
  --prior-fifteen results/practice_fifteen_request_reuse_k16.json \
  --target-upper-cents 2120000 \
  --out results/practice_sixteen_request_reuse_k16_round2.json
```
