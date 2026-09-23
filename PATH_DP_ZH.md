# 固定首访顺序的时间路径动态规划

本文只研究未来天气真值已公开的 `dev-reference` 离线练习场。比赛的完整状态与计分见 [PROBLEM_ZH.md](PROBLEM_ZH.md)，不预设首访顺序的全局模型见 [GLOBAL_PATH_MODEL_ZH.md](GLOBAL_PATH_MODEL_ZH.md)。

## 精确内层问题

把所有候选动作起点按 150 秒游标展开。对于**事先给定**的 64 个天区第一次完整观测顺序，完成集合由已执行的首访前缀确定。若请求标签和复访见证也预先给定，状态 `(k,t)` 足够：`k` 为已完成的必经事件个数，`t` 为当前游标。边包括合法完整观测、带有效请求标签的完整复访、天气中断的零科学观测、等待至下一时隙边界及终止。首次观测的科学分取评分器逐段质量，等待费用取起点的“是否还有未完成且可立即完整观测的天区”。所有边使游标严格前进，所以按时间拓扑序做最长路，对**该受限动作图**求得精确答案。

`sequence_path_dp.py` 使用固定必经事件及合法完整复访；[sequence_weather_path_dp.py](sequence_weather_path_dp.py) 再加入已审计的天气中断边，模型与通用填充收益上界见 [WEATHER_PATH_DP_ZH.md](WEATHER_PATH_DP_ZH.md)。[sequence_active_requests_dp.py](sequence_active_requests_dp.py) 进一步将全部可行请求的访问见证从强制序列中释放，用活动窗口的请求位掩码记带标签完整访问；它固定 64 个首访的相对顺序且要求 17 个可实现请求全部获奖。它的证明、复杂度和回放见 [ACTIVE_REQUEST_DP_ZH.md](ACTIVE_REQUEST_DP_ZH.md)。这些限制都不能推出原题的全局最优性。

## 如何使用及验证

版本化的 [89 事件核心](results/practice_core.csv) 给出一个首访顺序和请求见证；[当前最好完整路径](results/practice_best.csv)由活动请求 DP 在此首访顺序上重选实际标签、时间与复访，再由官方本地评分器独立回放。重新评分：

```sh
python3 score_decisions.py --scenario scenarios/dev-reference --decisions results/practice_best.csv --out runs/practice_best_score.json
```

内层算法的主要价值是准确评价一个给定顺序，并为全局分支、列生成或整数规划提供可行路径。先前对短块排列、单次或双次事件插入的试验改善过输入顺序，但只能搜索很小的邻域，无法判定是否困在局部谷地。后续重点是让首次天区、观测时间、请求标签和复访共同竞争时间容量；具体模型及未闭合的可证明上下界见 [GLOBAL_PATH_MODEL_ZH.md](GLOBAL_PATH_MODEL_ZH.md) 和 [REQUEST_UNCONDITIONAL_BOUND_ZH.md](REQUEST_UNCONDITIONAL_BOUND_ZH.md)。
