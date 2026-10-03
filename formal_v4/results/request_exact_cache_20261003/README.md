# CPU 预算与严格等价缓存研究

## 线上成本证据

来自 `cloud_request_gpu_batch_20261003.json` 的正式输出摘要：

| 卡 | CPU baseline | REQ 列构建 | mask DP | 总规划 | 完整情况 |
|---|---:|---:|---:|---:|---|
| γ | 503.454531s | 216.738870s | 1.234067s | 721.469s | 完成 |
| δ | 300.910315s | 84.262577s | 0.756549s | 385.965s | 完成 |
| α、β | 无摘要 | 无摘要 | 无摘要 | 无摘要 | 900s 中断 |

这四卡 GPU health 均超时约 60s，实际 remote 规划为 0。α、β没有独立的构建计时，不能把它们的超时唯一归因于 REQ。DP本身小于1.3s；主要研究目标应是构建和CPU基线，而不是替换这段mask DP。

## 两项补丁

实现只在 `research/request_exact_cache.py`，未修改 stable policy、生产入口、打包入口或策略参数。

1. 同一次 REQ 构建、同一 start，多个 duration 会重复采样相同的120秒中点。缓存各中点的完整 public quality 数组与同一 frozen future field 的 raw quality 数组。保留原先900秒slot切分、120秒小段切分、末段中点、浮点运算顺序、逐段累加顺序。没有用 prefix sum 改变舍入，也没有缩小候选集合。
2. 同一个 start 的 science opportunity price 会执行多个固定 duration 搜索。缓存同一 sidereal time 的 `_altaz` 输出和同一 now 的 `_public_quality` 输出。`_public_quality` 源码仅读取固定catalog、site、scoring与时间；不读取forecast、weather/E、ledger或repair。缓存在每次 `_build_pool` 前后清空。

中点缓存每个start独立，最多增加16 MiB数组存储，并在构建结束或异常时清空。build serial隔离不同build，避免对象id复用带来的污染。缓存数组只由内部只读代码使用：乘法生成新数组，`total += ...`只写入自己的累加器；不会返回给外部调用者。索引不等于全catalog时调用原始路径。

## 正确性与计时

`request_exact_cache_checks.py` 仅从六个public文件重建initial与本队下载的公开输出恢复ledger/messages，不创建官方engine、不读取truth。

对每个完整REQ窗口，将所有 `RequestColumn` 序列转为严格JSON比较。检查涵盖每列start/end/mask/opportunity_cost、所有目标/fiber/program/duration、science/tie utility、prediction、列顺序与所有额外pool字段，唯一排除计时字段。同时比较完整mask DP结果与各条选中的执行动作。

| 场景 | 完整列数 | 原版 | 缓存 | 相同输入下结果 |
|---|---:|---:|---:|---|
| δ REQ1 frozen | 290 | 8.890s | 8.330s | 逐列、DP、6动作完全相同 |
| δ REQ1 published | 282 | 13.123s | 9.038s | 逐列、DP、6动作完全相同 |
| γ REQ1 published | 357 | 16.033s（有cProfile） | 9.989s | 逐列、DP、6动作完全相同 |
| δ REQ2 published | 453 | 13.625s | 9.156s | 逐列、DP、6动作完全相同 |

δ published 的单次同机器实测比值为1.452×，不是云端结果或稳定中位数。γ原版有cProfile，不能把该比值当性能结论。γ profile 中 fixed_value 5.23s、初始price 1.84s、integration 4.61s、fill 4.00s；调用关系存在嵌套，不能将这些数直接相加。

另一阶段 δ REQ2 的453列也通过，单次1.488×。在同一planner、同一now二次完整重建中，把quality/E从0.55改为0.79、band scale相应变化、ledger science统一加0.07、factor下限改为0.21、terrain posterior替换为已知clear；两版本重建逐列完全相同，且相对于第一次确实改变列内容。中点数组peak最多6.3168 MB。详细哈希、profile、gate结果以 `checks.json` 为准。

本研究没有新线上评分，没有改变当前上传包，也不声称全季动作必然相同：缩短耗时可能改变上层剩余wallclock门槛，但每个相同输入的有限候选集合及结果保持一致。
