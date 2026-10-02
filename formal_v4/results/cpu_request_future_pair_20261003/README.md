# 共享 terrain 后验 + 公开未来场请求 DP：CPU 同源整卡

2026-10-02 22:15:23 UTC 同时启动 L1 两模式。NumPy CPU、无网络、本地官方 runner、每路 900 秒上限。冻结 `/tmp/gosim-v4-request-future-pair-20261003`，220 文件逐项 SHA256 复查零差异。

共同配置：CPUphase24固定工作量；共享 reference terrain prior/正反馈版本空间；raw 方向因子按未来 alt/az 重算；临时 bulletin 仅当前 900 秒槽，随后只采用已发布 forecast 的时间/夜晚支持；global raw/band 质量冻结。两路代码相同，config 只有 request_dp_mode=bypass/deadline 不同。

主要源码 SHA256：

- Policy e7ab68f3b647eb8c57c5e06b354c0e5ee480ca0501ee6d3891617dcd2d803531。
- CPU phase 3d3b20745eff3979a3954ffcbaca129373930d278825b6c895b83883c3bae67e。
- REQ common 517f9a9efe72343e36b5aa913f8cb0749c8be9c0c444af5a16bf2d707099bf16。
- Published future field 5a9531c854b1541a0f56bcd62031281dcdba1c355c2eabd58758a7eef5d23489。
- 独立 entry 4747e19568f0647bb739f2961ce127e828e3355b5ba4dc28b284a1ce8057798a。

## L1 完整结果

| 模式 | 总分 | 科学 | REQ | required缺失 | accounted墙钟 |
|---|---:|---:|---:|---:|---:|
| bypass | 6200.856777 | 6101.222991 | 1/2 | 2 | 363.83秒 |
| deadline | 6285.945725 | 6086.403602 | 2/2 | 2 | 408.73秒 |

deadline提高85.088948分，首REQ从4/8变成6/8；第二REQ仍6/8完成。科学减少14.819389，均匀惩罚再减少0.091664，REQ增加100。两路均report100、survey_complete、0失效、0错误报告、0phase紧急截断。分数统一使用官方report；Policy结束时尚未收到最后动作反馈的ledger缓存不作为最终分项。

REQ侧累计：4次建列62.7448秒，47次精确maskDP0.551秒，2次请求曝光、3次裁剪背景曝光、1次边界等待、0预测不可行/执行失败。该结果明显区别于旧模型冻结当前SE衰减后70次预测不可行、零动作改变的控制。

baseline精确复现独立terrain-only gate的6200.856777；并行CPU竞争令墙钟比单跑长，固定候选/精解工作量没有改变。原始config字节、全部轨迹/官方报告、public gate、source manifest均保留于本目录。

## 数学范围

事件时间×8目标mask DP对给定有限列和冻结regret费用精确；没有宣称整个连续时空巡天问题全局最优。价格为同开始/同曝光时长的固定科学候选最大值 B 减该REQ列的科学收益 S，取非负值，DP不累加科学收益来避免重复饱和奖励。B候选族有限；跨列饱和、未来质量变化、天气数值幅度及terrain参考域仍是近似/条件假设。

GPU版本另行独立门检；本目录得分不能当成线上/GPU结果。

## L2 完整正控

已启动的 L2 两路在22:29/22:30 UTC自然完成；后续L3/L4未启动，优先GPU组合门检。

两路完整轨迹及官方分数完全相同：6702.860859（科学6554.143429、REQ200、report100、required缺3、uniformity−1.282569）。REQ本来均完成，DP零override/裁剪/等待，0不可行/执行预测失败，0phase紧急截断。

accounted墙钟318.641 / 377.189秒；deadline5建池62.9661秒、23DP0.3417秒。表明新模型在这张卡保持已有可行路径，新增成本主要来自建列，没有制造虚假的科学收益。

L2 summary从官方报告独立归档；调度器在两个L2子进程自然结束后清理，没有启动L3/L4。
