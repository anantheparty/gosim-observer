# 十六关键天区条件上界

固定 [十五块双实现证书](RING_PROJECTED_DP_ZH.md) 的最佳关键集合（原十四块加 `T00027`），加入前轮次优候选 `T00062`。使用相同的 `dev-reference`、`mechanics=False` 评分器、非负容量价 SHA-256 `a4c1b7f9904a1ec0ae9074c349197231274e492676098614fc81cf32888ae480`、统一 $\theta=135$ 个百分之一分和全部 918,757 条完整弧及 850 条天气中断弧。严格的 [十行循环缓冲 DP](bounds_request_projection_ring.py)没有改变放松图或转移，只把时间维存储从 47,569 行降到 10 行。

| 关键块数 | `RQ0004=T00004` | `RQ0004=T00012` | 全 17 请求条件界 |
| ---: | ---: | ---: | ---: |
| 15 | 21,370.59 | 21,371.59 | 21,371.59 |
| 16，增加 `T00062` | 21,330.24 | **21,331.24** | **21,331.24** |

十六块最松分支的账本以百分之一分为单位：外部科学与容量价 1,409,570、无标签常数 6,480、请求奖励 392,000、投影 DP 325,074，和为 **2,133,124**。该条件界比十五块降低 40.35 分。独立 [恰好 16 奖励证书](SIXTEEN_REQUEST_GROUPED_K13_ZH.md)至多 21,283.23，[至多 15 奖励证书](FIFTEEN_REQUEST_GROUPED_K13_ZH.md)至多 21,255.71；所以严格**无条件上界是 21,331.24**，距已验可行解 21,119.494551 尚有 **211.745449 分**。

新增块占第 15 位（从零起），其位值为 `32768`，恰好是 `uint16` 最高位。[高位小图](test_projection_high_bit.py)在 `mask=0,32768,65535` 核验等待 OR 谓词，并将首次成功、带请求标签复访、无标签复访禁行、截止时间及 REQUIRED 终端罚分与完整矩阵 DP 逐分对拍；[输出](results/projection_highbit_k16_test.json)全部一致。环形证书本身还逐分复算前轮十五块基线；新增关键块的评分与全部状态仍使用同一个已审计转移。

[程序](scan_ring_key_extension.py)在本机完成这组扩展，[数值证书](results/practice_request_projection_k16_ring.json)绑定十五块证书 SHA-256、价格证书、弧数与 10 行跨度。总耗时 **325.23 秒**，进程峰值 **191.6 MiB**；十六块每个请求选择分支的 DP 约 91 秒。下一步若增加第十七块，行动掩码须扩成 `uint32`；否则高位会被截断。没有在线提交。

```sh
python3 test_projection_high_bit.py
python3 scan_ring_key_extension.py --base-keys T00018,T00029,T00030,T00031,T00024,T00021,T00040,T00015,T00048,T00032,T00016,T00010,T00047,T00011,T00027 --extra T00062 --prior-certificate results/practice_request_projection_k15_ring.json --expected-base-cents 2137159 --out results/practice_request_projection_k16_ring.json
```
