# Rhodes1：冲突超图引导的 11 天区精确邻域

## 模型与选择

固定当前评分器认可的 64 个首次完成事件。对一个潜在的高分合法首访弧 `a=(i,u,v)`，把 `i` 和当前首访中与 `[u,v)` 相交的天区组成支持集 `H(a)`；若其成员不释放，这条弧不能替换进当前路径。对已收费等待段，记录当时仍未完成且可立即观测的天区 OR 集；释放整个集合才有机会消除那段等待。再以请求见证的天区共现关系扩充种子，并按锚点类别轮流选取不同的 11 块组。排序值只是搜索启发式，不作为上界。

每个组由 [事件层精确 DP](event_subset_exact_dp.py) 在“组外首访固定、请求见证可重排”的受限问题中求最优，并用原始本地评分器完整回放。只有严格高于当前 `21,119.494551` 才会更新 `best.csv`；组内 `OPTIMAL_RESTRICTED` 不代表全题最优。详情与生成器见 [冲突组程序](conflict_group_search.py)。

## 启动核验

- 输入决策 SHA-256：`ce637a3d24c879d13a73e4001f8f06b0f05405cbf9df2e21264abfb9d564852c`。
- 本机与 Rhodes1 的 `conflict_group_search.py` SHA-256 均为 `2caf24c6874950e666648874827e01bf8a1a5eea3e45b596e765ca5228396239`；`event_subset_exact_dp.py` 均为 `19c4a1396632f6cc458f5a468c5e3e1ef673ed6586f601aade8ec0a93d7593d7`。
- 候选生成器从真实合法增分弧、首访阻塞与 2,123.40 分等待罚中取证，生成 120 个不同的 11 块组，覆盖等待、冲突、跨夜双弧和请求四类锚点。
- 最强等待组覆盖原轨迹中 538.95 分的收费等待；远端单组端到端试运行 214.24 秒、约 21 GiB、结果 `OPTIMAL_RESTRICTED` 且仍为 `21,119.494551`。这只说明该组无提升。

九小时结构化搜索于 2026-09-25 07:06 UTC 在 Rhodes1 的 tmux 会话 `gosim_conflict_k11_20260925` 启动，目录 `/home/shu/gosim-observer-research/conflict_20260925/`，输出 `results/conflict_k11_long/{trace.jsonl,best.csv,summary.json}`，日志 `results/conflict_k11_long.log`。它排除已测单组，并按 11 块集合去重；若运行中更换最优路径，旧组不会自动重访。结束后须取回最佳 CSV、逐行核对远端轨迹与实例 SHA、在本地原评分器复算，再决定是否更新仓库下界。任何阶段均不向排行榜提交。

```sh
ssh rhodes1 'tmux list-sessions'
ssh rhodes1 'tail -n 5 /home/shu/gosim-observer-research/conflict_20260925/results/conflict_k11_long/trace.jsonl'
```
