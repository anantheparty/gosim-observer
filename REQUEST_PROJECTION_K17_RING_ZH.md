# 十七关键天区条件上界

从 [K16 证书](REQUEST_PROJECTION_K16_RING_ZH.md)的关键集合加入 `T00043`。固定同一份 `dev-reference` 数据、非负容量价格 SHA-256 `a4c1b7f9904a1ec0ae9074c349197231274e492676098614fc81cf32888ae480`、统一 θ=135 百分之一分、全部 918,757 条完整观测弧及 850 条天气中断弧。十行循环 DP 仍逐一计算两种 `RQ0004` 请求选择，没有合并分支。

| 关键块数 | `RQ0004=T00004` | `RQ0004=T00012` | 全 17 请求条件界 |
| ---: | ---: | ---: | ---: |
| 16 | 21,330.24 | 21,331.24 | 21,331.24 |
| 17，增加 `T00043` | 21,303.17 | **21,304.17** | **21,304.17** |

最松分支的整数账本（百分之一分）为：外部残差与容量价格 1,382,209，请求奖励 392,000，无标签常数 6,345，精确投影 DP 349,863，总计 **2,130,417**。K17 比 K16 收紧 27.07 分。已认证的至多 16 奖励界为 21,283.23，故当前合成的严格全局上界为 **21,304.17**，与可行解 21,119.494551 相差 **184.675449** 分。

新关键块的位值是 `65536`。`_conditional_bound` 为超过 16 位的行动掩码使用 `uint32`；[独立高位小图审计](test_projection_k17_mask_audit.py)覆盖该位的首次成功、复访、等待和截止时间，另有 [逐位小图测试](test_projection_bit16.py)。DP 完整转移与 [环形缓冲证明](RING_PROJECTED_DP_ZH.md)相同。证书逐分重算 K16 基线，绑定其 SHA-256、容量价、弧数与环形跨度；[结果](results/practice_request_projection_k17_ring.json)再次核对两个分支的每项整数和。

本机完整运行 **783.60 秒**，进程峰值 **199.33 MiB**。这只是所选 K17 集合给出的严格上界；其他新增关键块正在独立扫描。没有在线提交。

```sh
python3 scan_ring_key_extension.py --base-keys T00018,T00029,T00030,T00031,T00024,T00021,T00040,T00015,T00048,T00032,T00016,T00010,T00047,T00011,T00027,T00062 --extra T00043 --prior-certificate results/practice_request_projection_k16_ring.json --expected-base-cents 2133124 --theta-cents 135 --out results/practice_request_projection_k17_ring.json
```
