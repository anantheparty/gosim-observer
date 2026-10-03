# 阶段 2 归档：同槽公开约束投影未提分

2026-10-04 JST。状态：`reject_no_parameter_rescue`。生产包未改，未操作 Git index，未执行线上动作。阶段 1 的原 4 个输出及 MANIFEST 保持冻结。

## 因果结论

在同一份 READY native 源码上新增公开同槽约束，仅在联合集合排除原 C、最新单条集合仍容许原 C 时，将当前 planning env 的 C/E 投影到最近可行状态。没有主动 probe；持久点拟合、raw-factor 安全账本、report 规则、geometry/native 源码保持原版。

一次自然信息机会确实改变了实际动作，但完整官方本地 L2 季节总分下降 **46.773815**。按预声明拒绝此最小规则。保留可辨识性机制与严格公开筛选证明，不继续扫触发参数、添加 probe 或用其他卡补救；此结果也不能证明所有利用信息的决策规则都无价值。

| 分项 | control | constraint | constraint − control |
|---|---:|---:|---:|
| 总分 | 6823.661561 | 6776.887746 | **−46.773815** |
| sum_best_scores | 6674.649933 | 6627.655434 | −46.994499 |
| uniformity_penalty | −0.988373 | −0.767689 | +0.220684 |
| observation_request_reward | 200 | 200 | 0 |
| report_settlement | 100 | 100 | 0 |
| required_penalty | −150 | −150 | 0 |

control/constraint 分别执行 1107/1099 次 observe，观测 8410/8383 个不同 target；required_missing 均为 3，2 个 observation request 均完成，invalidated_observations 均为 0。分数取独立官方 runner 输出，未以参与者累计分或 RMSE 替代。

## 首次分叉

共同前缀为 528 个 action / 489 个 observe。**第 529 个 action（observe_action_index=489）**首次分叉，时间 `2026-11-20T06:43:01Z`，slot `N20261119-S024`。

信息仅来自已经完成的 observe 486/487/488，实际时长 108/74/92 秒，声明 DARK/DARK/BRIGHT。原 C/E 为 `0.6776306282862244 / 0.8916989671936985`，投影为 `0.6584720563124241 / 0.9162111913099674`。两组日志均只出现一次投影机会。

| 实际动作 | control | constraint |
|---|---|---|
| pointing (alt, az) | (75.2167003, 61.5350803) | (84.1576671, 41.0389339) |
| duration_seconds | 230 | 174 |
| program | DARK | DARK |
| assignment 数 | 14 | 11 |

后续动作受首次分叉后的真实反馈影响。整季差值归于该冻结策略的因果处理，不能将所有 science 损失归于第一条曝光本身。不同状态下的预测 rate 也不作为提分证据。

## 公开保证与限制

slot 使用 initialize 的公开 `survey.slot_seconds`、night anchor/end/slot_count 推导，核对曝光开始时保存的 current bulletin 的 issued_at/night_id/slot_id。阈值、倍率、mismatch、f0*t0 和 q0 取公开 initialize 配置。runtime 输入仅用公开 target 属性、动作、公告、hit score 与既有几何计算；没有把 observations.csv 的 factor/quality/prog_mult 当成返回字段。

只接收完全处于同槽、实际时长不超过 120 秒、至少 3 个舍入区间下端为正的 hit，且当前公告不存在非 terrain 事件。官方 scorer 此时取一个 midpoint；永久 terrain 在该点仅为零或全通，正 hit 排除 terrain，无需知道隐藏 terrain 范围或使用 65° 先验。原始积分的 event start/end 切分依靠公告筛选排除。

证明限定于已核对的官方生成器/runner：所有与 slot 重叠的非 terrain / 非 fault 事件会在该 slot 公告中出现，quake 由 effect 表公告；fault onset 位于 slot anchor，E 在 slot 内固定；串行 runner 不会在 observe 内执行 report；永久 terrain 首尾覆盖整个 survey。报告、跨槽、公告缺失/矛盾、空集合与 slot expiry 会拒绝或清空约束。共同 C 需要上述清洁条件，允许任意未知方向损失时不能从低 score 推导同样的双侧约束。

在完整运行之前，public-only replay 对 READY native 的 98 条合格短曝光和旧强 L2 的 82 条保留了所有事后 truth 标签。READY native 仅 1 次自然不同 program 联合机会、1 次联合独有冲突，且离线候选与后续真实 Linux 首次分叉一致。truth 只在先完成公开推断之后验证保真，以及由独立 runner 评分；没有挂载给 participant。实际 constraint 轨迹记录 90 条合格短曝光、2 次自然不同 program 联合机会、1 次冲突。这里不声称这些频率适用于其他卡或更改机制的模拟器。

## 复现和资源门检

`pair_audit.json` 全部 7 项门检通过：control actions.jsonl 逐动作等于 READY native、control 精确复现 6823.661561、22 文件 source lock 未变、两组 protocol complete、两组低于 900 秒、无 traceback、participant 无 truth mount。

源锁 SHA256：`600e2dcb1061bd4bfc35b37481fc9be3e75463c6785cd0c06243796a7948fca5`。参与者包含 READY 的 20 个原文件及 2 个新增文件；driver SHA256 为 `3badbbdf7fa19acb78b53d8052260ca41ad376106c0b33bbbb0c03322b8fbe44`，运行后均未修改。

Rhodes1 在 `2026-10-03T17:38:30.408734+00:00` 启动，driver PID 678992。control 使用 cores 4,5、PID 679083；constraint 使用 cores 6,7、PID 679090。每组 2 CPU / 2 GiB / 全局协议 900 秒，Docker image 固定，network none、participant/dependencies 只读挂载。accounted_seconds 为 522.308 / 520.967；两组 termination 为 survey_complete、exit code 为 0。

`completion_resources.json` 在 `2026-10-03T17:52:08.819596+00:00` 确认上述 3 个 PID 与两个命名容器均无残留，cores 4–7 已释放。`L2_live_resources.json` 保存启动后的实际 CPU/memory/network/mount 元数据。`remote_input_sha256.json` 保存实际远端 36 个 runner/card 文件和 880 个依赖文件的哈希；MANIFEST 汇总全部归档文件及输入哈希。负结果与严格筛选修正均写在 stage2，未重写阶段 1。
