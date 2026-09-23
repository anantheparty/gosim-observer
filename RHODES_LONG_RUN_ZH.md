# Rhodes1 九小时事件层搜索

本次只搜索公开的 `scenarios/dev-reference` 固定实例，不向比赛网站提交。起点是本地评分器已验证的 `results/practice_best.csv`，得分 **21,119.494551**，SHA-256 为 `ce637a3d24c879d13a73e4001f8f06b0f05405cbf9df2e21264abfb9d564852c`。Rhodes1 上的代码快照为 Git 提交 `10eb6793ae3a536f9da3a4bfd277765f89cedfea`；启动前在远端重放起点，得分和 SHA-256 均与本机一致。

- 运行 ID：`20260923T203237Z`。
- 远端会话：`gosim_lns_20260923T203237Z`。
- 工作目录：`/home/shu/gosim-observer-research/long_runs/20260923T203237Z`。
- 启动：2026-09-23 20:33 UTC（日本时间 2026-09-24 05:33）；搜索预算 9 小时，预计 2026-09-24 05:33 UTC（日本时间 14:33）停止，再进行本地评分器汇总。
- 四个独立流：两个释放 10 块，两个释放 6/8 块；各规模一条先做一轮完整结构候选扫描，再搜索随机尾部，另一条直接用不同随机种子搜索尾部。全部使用 `--release-witnesses`，所有改善立即由本地评分器重放。

每个流的 `phase1`/`phase2` 目录保存 `best.csv`、逐组 `trace.jsonl` 和已接受的 `incumbent_*.csv`。九小时后，`collect_rhodes_long_search.py` 会重放各流最后一个有效检查点，写出 `outputs/best.csv` 和 `outputs/summary.json`。如果远端中断，仍可从这些检查点恢复；`outputs/seed.csv` 始终保留原始起点。

查看状态：

```bash
ssh rhodes1 'tmux has-session -t gosim_lns_20260923T203237Z && echo running || echo stopped'
ssh rhodes1 'find /home/shu/gosim-observer-research/long_runs/20260923T203237Z/outputs -name trace.jsonl -print'
```

结束后先将 `outputs/best.csv` 复制到本地 `runs/`，独立用 `ChallengeScorer` 重放并对比 `results/practice_best.csv`。若确有改进，再更新版本化的最佳路径与研究记录；不做网站提交。
