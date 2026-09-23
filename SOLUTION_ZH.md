# 巡天调度方案

完整题面和逐项评分公式见 [PROBLEM_ZH.md](PROBLEM_ZH.md)；复杂度与状态推导见 [THEORY_ZH.md](THEORY_ZH.md)；正式场景的可证明分数上界与在线期望模型见 [BOUNDS_ZH.md](BOUNDS_ZH.md)。

2026-09-24 起的系统化练习场研究见 [STRUCTURE_ZH.md](STRUCTURE_ZH.md)：它给出完整状态、等待 OR 与请求整包耦合、固定顺序的精确计时 DP、0/1 路径整数规划骨架，以及“受限求解器 bound 不能充当原题上界”的判别。练习场的资源对偶证明、数值审计与价格证书见 [PRACTICE_MODEL_ZH.md](PRACTICE_MODEL_ZH.md)。两份用户思路的勘误与合并见 [SYNTHESIS_ZH.md](SYNTHESIS_ZH.md)。研究代码和证书由本地 Git 分支 `research/structured-optimizer` 管理；仓库没有远端。

只保留两份可复算的练习场决策文件：[参考排程](results/practice_reference.csv)、[当前本地最优排程](results/practice_best.csv)；分数、哈希与适用范围在 [实验记录](results/practice_manifest.json)。其它 `run_*` 回放是可重新生成的中间产物，已清理。压缩包由 `build_submission.py` 临时打包生成，不纳入 Git。

比赛要求智能体在连续的观测时隙中，为望远镜选择天区、观测项目、临时请求，或等待。天区有可见时间、曝光时长和优先级，天气和仪器状态会影响得分。完成必做天区、各分区的覆盖指标和限时请求很重要；正式场景还奖励覆盖均匀性。每一步只能使用当时公开的信息。

## 在线提交

`agent/my_strategy.py` 对公开的合法候选动作计算单位曝光时间的收益。收益包括预计科学分、限时请求价值、临近截止时的必做/覆盖收益，以及新增天区对覆盖均匀度的边际贡献。练习场没有均匀度奖金，直接使用已验证的公开基线排序。异常检测和故障报告由随包的 `agent/anomaly_detection.py` 处理。运行仅需 Python 标准库。

重新生成可上传压缩包：

```sh
python3 build_submission.py
```

上传 `observer-deterministic.zip` 作为“智能体运行”。必须上传完整压缩包；平台的单文件包装缺少依赖文件。

## 公开天气场景

`offline_plan.py` 用已公开的天气和几何信息，枚举安全的观测时间段，按科学收益及必做天区的时间紧迫度做区间装箱，再安排限时请求。它只适用于公开天气的练习场景，不用于正式隐藏天气场景。

整数规划版见 [MODEL_ZH.md](MODEL_ZH.md)。它将天区首次观测、请求复访和望远镜独占约束放进同一模型，在本机 CPU 上用 OR-Tools CP-SAT 求解；求解后的决策仍用官方评分器验证。此求解器是离线实验依赖，不在上传的智能体包里。

```sh
python3 offline_plan.py --scenario scenarios/dev-reference --out run_plan/decisions.csv
python3 score_decisions.py --scenario scenarios/dev-reference --decisions run_plan/decisions.csv --out run_plan/score_report.json
```

```sh
python3 -m venv .venv-solver
.venv-solver/bin/python -m pip install ortools
.venv-solver/bin/python optimize_public.py --scenario scenarios/dev-reference --out run_cp/decisions.csv --time-limit 90
python3 score_decisions.py --scenario scenarios/dev-reference --decisions run_cp/decisions.csv --out run_cp/score_report.json
```

网站已核实贪心构造器的 `dev-reference` 本地评分与在线评分一致；之后的整数规划版只在本地验证，暂不再上传。正式比赛尚未开放，正式场景表现不能由练习分直接推断。

正式场景的公开数据分数上界可在本地复算：

```sh
python3 bounds_public.py
.venv-solver/bin/python bounds_night_lp.py
```

逐夜容量脚本使用上文 `.venv-solver` 中的 OR-Tools。两个数值都是乐观天气、正确异常报告与请求全完成情况下的数学上界，不是正式智能体的预计得分。[BOUNDS_ZH.md](BOUNDS_ZH.md) 给出证明及在线期望决策模型。
