# 练习场可复算结果

这里保留用于复算和继续搜索的决策序列，而非每轮搜索的回放目录：

- `practice_reference.csv`：92 次观测的参考计划，用于分析等待费用与固定顺序计时。
- `practice_core.csv`：89 个必需事件，作为全游标路径 DP 与块内排列 DP 的输入。
- `practice_best.csv`：当前最好的**离线练习场**计划，5,782 次合法观测，其中 5,723 次完整成功、59 次合法天气中断，回放得 21,113.710660。它使用公开的 `dev-reference` 天气真值，不能视作正式赛场可执行的在线策略。

`practice_manifest.json` 保存得分分解、决策文件 SHA-256、所用受限求解器配置和独立上界。[EVENT_LNS_ZH.md](../EVENT_LNS_ZH.md) 记录当前可行路径算法，[GLOBAL_INTERVAL_BOUND_ZH.md](../GLOBAL_INTERVAL_BOUND_ZH.md) 证明最新全局上界。官方评分器可直接复算：

```sh
python3 score_decisions.py --scenario scenarios/dev-reference --decisions results/practice_reference.csv --out runs/practice_reference_score.json
python3 score_decisions.py --scenario scenarios/dev-reference --decisions results/practice_best.csv --out runs/practice_best_score.json
```

`runs/` 中除小型价格证书等明确纳入 Git 的文件外，均为可再生的临时结果。网站未收到这些离线计划。
