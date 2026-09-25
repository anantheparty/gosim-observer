# 恰好 16 个请求奖励：按可行分筛选余支

承接[未获 `RQ0018` 的新 K16 证书](SIXTEEN_REQUEST_RQ18_K16_ZH.md)，恰好 16 奖励的 33 支中，有 **16 支**旧有效界高于当前可行分 **21,119.494551**。[本轮程序](bounds_sixteen_request_reuse_k16.py)逐支核对完整 K16 时间 DP 输入签名；这 16 支均与已认证的全 17 奖励 K16 案例相同，故直接复用已算出的 **325,074 百分之一分**。非关键天区科学包络、请求奖励及必罚仍逐支重算。

其中 14 支新界至多 **21,001.24**，已经低于当前可行分；另外两支未获 `RQ0002` 的新 K16 界仍是 **21,147.85 / 21,148.85**，成为剩余瓶颈。其他 17 支保留原有上界，均低于当前可行分。因此本轮**恰好 16 奖励 ≤21,148.85**。结合[至多 15 奖励证书](FIFTEEN_REQUEST_REUSE_K16_ROUND3_ZH.md) 21,107.16，**至多 16 奖励 ≤21,148.85**；全 17 奖励需另行约束。

[机器证书](results/practice_sixteen_request_reuse_k16_round3.json)包含全部 33 支的整数合并表。没有在线提交。

```sh
python3 bounds_sixteen_request_reuse_k16.py \
  --prior-sixteen results/practice_sixteen_request_rq18_k16.json \
  --prior-fifteen results/practice_fifteen_request_reuse_k16_round3.json \
  --target-upper-cents 2111949 \
  --out results/practice_sixteen_request_reuse_k16_round3.json
```
