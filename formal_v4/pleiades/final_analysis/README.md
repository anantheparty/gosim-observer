# 决赛复盘脚本

这里的脚本为 [../FINAL_RESULTS_ZH.md](../FINAL_RESULTS_ZH.md) 提供数字和图，只分析我们自己的运行。

## 数据

数据来源是官方仓库 [hackathon-survey26](https://github.com/gosimfoundation/hackathon-survey26) 提交 `e37c7ed` 的 `web/src/content/final/`：
- `results.json`：每次运行的得分、状态、重跑次数和起止时间；
- `replays/<run_id>.json`：决赛回放，内容包括：
  - 站点；
  - 目标；
  - 每个 15 分钟时段的天气和不报修时的仪器效率；
  - 每个动作；
  - 总分和基础科学分。

本目录不复制官方数据。`data/pleiades_runs.csv` 是我们 12 次运行的汇总。

## 运行

```bash
export FINAL_ROOT=/path/to/hackathon-survey26/web/src/content/final   # 默认是开发机上的路径
export AGENT_DIR=../agent        # pleiades_behaviour.py 用其中的 astro.py（默认即 ../agent）
```

| 脚本 | 输出 |
|---|---|
| `pleiades_runs.py` | 我们 12 次运行的得分、极差和墙钟时间，以及回放汇总（写出 `data/pleiades_runs.csv`） |
| `card_events.py` | 从回放效率找出故障切换和地震；拟合 H 卡数据丢失的触发时间与作废区间 |
| `pleiades_behaviour.py` | 开局科学分、故障切换后的恢复、指向高度、月距、曝光时长、关顶时的曝光与等待 |
| `make_figure.py` | 按夜累计科学分的图（写到 `out/`，复制到 `../figures/`） |

依赖：
- `pleiades_behaviour.py` 需要 numpy（经由 `agent/astro.py`）；
- `make_figure.py` 需要 matplotlib；
- 其余脚本只用标准库。

## 口径

- **科学分是近似值。** 回放只给每次曝光的总分，所以把它平均分给该曝光的目标，按目标取迄今最好值。
- **回放的效率按不报修计算。** 回放里的效率是卡片真值中的仪器效率，故障系数一直算在里面；报修后的效率由计分器另行恢复。`card_events.py` 用阶梯的形状区分故障切换和地震，这是启发式判断。
- **故障后的恢复指标噪声大。** 每目标、每 15 分钟的得分受目标权重影响，只看多次故障汇总后的中位数。
