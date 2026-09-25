# Rhodes1 异构首次完成顺序搜索（2026-09-25）

这次只处理公开 `scenarios/dev-reference` 固定实例，不向比赛网站提交。目标是在现有 21,119.494551 可行解之外，探索真正不同的 **64 次首次成功完成顺序**。`diverse_seed_search.py` 从已跟踪的训练顺序、冻结候选和当前解建立多起点种群，用八种重排与两温度链间交换提出顺序；每个候选由完整请求、天气及等待的固定首访顺序精确 DP 评分，每个新全局最高分都写 CSV 并由本地原评分器回放。它是可行解搜索，不提供全局上界。

代码快照是本地 Git 提交 `28c534c` 的 `git archive`，独立部署于 Rhodes1 的 `/home/shu/gosim-observer-research/diverse_20260925_0712`。部署后远端 `results/practice_best.csv` 的 SHA-256 为 `ce637a3d24c879d13a73e4001f8f06b0f05405cbf9df2e21264abfb9d564852c`；远端评分器回放为 **21,119.494551**、64 天区完成、请求奖励 3920。

## 短跑

会话 `gosim_diverse_pilot_20260925`，输出目录 `pilot/`，运行 212.13 秒，退出码 0，峰值 RSS 466,008 KiB。253 次迭代产生 229 个非空候选，其中 139 个可行、76 个被链状态接受。最高新候选为 21,117.407393，未超过基线；可行候选与基线首次成功顺序的最大 Spearman footrule 为 358。四个已由评分器回放的种子分数与相对 footrule：

| 来源 | 分数 | footrule |
| --- | ---: | ---: |
| 当前最佳 | 21,119.494551 | 0 |
| frozen_273956 | 21,106.201213 | 124 |
| frozen_273944 | 21,073.769828 | 134 |
| frozen_273967 | 21,072.968021 | 178 |

短跑最终 `pilot/best.csv` 与当前最佳逐字节相同，SHA-256 仍为 `ce637a...`。

## 三小时长跑

- 会话：`gosim_diverse_3h_20260925`。
- 输出目录：`/home/shu/gosim-observer-research/diverse_20260925_0712/long_3h`。
- 启动：2026-09-25 07:17 UTC；计划约 10:17 UTC 正常结束（日本时间约 19:17）。
- 随机种子：`20261003`，时限参数 `--seconds 10800`，四个种子由新运行独立评分并导出。
- 正在并存的任务：24-worker K17 扫描和单核 k11 冲突组搜索；本进程使用约一个 CPU 核。

远端查看：

```bash
ssh rhodes1 'tmux has-session -t gosim_diverse_3h_20260925 && echo running || echo stopped'
ssh rhodes1 'tail -8 /home/shu/gosim-observer-research/diverse_20260925_0712/long_3h.log'
ssh rhodes1 'ls -lh /home/shu/gosim-observer-research/diverse_20260925_0712/long_3h/best.csv'
```

正常结束会写 `long_3h/summary.json`；`best.csv` 在每次评分器核验改善后原子替换，`trace.jsonl` 记录可行性、分数、首访顺序与接受状态。收尾须将新最佳下载至本地，独立评分器回放并检查 CSV `reason` 为空，再决定是否提升仓库中的当前解。长跑进行中不能把 `summary.json` 尚未出现误判为失败。
