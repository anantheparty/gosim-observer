# 巡天调度方案

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

```sh
python3 offline_plan.py --scenario scenarios/dev-reference --out run_plan/decisions.csv
python3 score_decisions.py --scenario scenarios/dev-reference --decisions run_plan/decisions.csv --out run_plan/score_report.json
```

本地 `dev-reference` 评分为 15533.87（64 个天区、全部可完成请求）；压缩包在网站练习场两场景平均 9400.10。正式比赛尚未开放，正式场景表现不能由练习分直接推断。
