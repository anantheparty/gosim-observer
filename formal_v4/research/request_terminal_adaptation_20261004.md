# RequestCache 安全终局 report 适配（2026-10-04）

可审查适配包已放在 `formal_v4/results/request_terminal_adaptation_20261004/`。目前确认了原包保留、真实 RequestCache 短入口一致性、公开有效 ledger 的终局安全门，以及官方 runner 的合成短协议时序；尚未进行本策略的真实 matched L3，因此没有 RequestCache 实际分数增量结论。旧 `FOUR_CARD_ACTUAL_RESULT.json` 的 native 四卡结果不是本适配的收益证据。

## 原包与入口

基线 ZIP 为 `/Users/kamico/Downloads/observer_request_exact_cache.zip`，SHA256 `e55becb74bbf2a707aeb893fb054a857610312c81d815181a28bfcf5e5ff092a`，29 个成员。它与 `request_geometry_integration_20261004/control_package` 的每个成员完全相同。新 `control_package` 保留全部 29 成员字节；新 `full_wrapper_package` 保留 27 成员原字节，仅修改 `observer.project.json` 的 `run` 和相应 `build_manifest.json`，增加 `wrapper.py`、`terminal_report_agent.py`。原有 policy/config/terrain/request/cache/transport 参数全部原样保留；两个 ZIP、逐文件 SHA、必要 manifest 差异见 `package_preservation.json` 与 `source_lock.json`。

`wrapper.py` 先导入原 `research.agent_request_exact_cache`，让原模块安装 `DisabledRemote`、`ExactCachedRequestRemotePlanner`、`ExactCachedRequestPolicy` 等全部工厂，再包装真实 `ExactCachedRequestPolicy`。它不安装 native 几何工厂。新环境开关 `REQUEST_TERMINAL_REPORT_ENABLE` 默认 `1`，可设 `0`；最小墙钟余量默认 10 秒且不可设成非有限值或低于 10。未触发门之前每次原 policy 调用一次，动作直接返回；触发时先由原 policy 完成选择，再冻结该动作，输出一个 report，并在下一次请求直接释放同一动作，不把新 report 反馈交给原 actor。

## 官方时序与安全范围

本次重新阅读了官方 `v4_runner.py`、`v4_scorer.py`、`v4_workflow.py`、`v4_config_check.py`、`agent_core/protocol.py` 及 Python `AGENTS.md`。作用域内没有要求修改的 AGENTS 文件。官方 report 只有 `{"action":"report"}`，没有 target 字段，目标是当前尚未修复的 instrument fault。不能把临时 observation_request 的 target 当 report target。

`v4_runner.py:504` 的主循环只在 `now < survey_end` 时请求动作，`650` 的 finish 直接结束，`655` 的 wait 更新时刻，`667` 的 report 保持时刻和 observe rank 不变并排队结果，`711` 的 observe 先截到 survey_end。`713–719` 还规定起点在 slot 内时截到该 slot 所属 night_end；日间 gap 起点没有这次夜末裁剪。guard 根据公开 nights 计算 `effective_end=min(now+duration,survey_end,occupied_night_end)`，仅 effective_end 达到 survey_end 才把 observe 视作终局；早夜长指令即使 declared duration 跨到 survey_end，也可能被剪短并有后续 actor 决策，必须拒绝。到 survey_end 后没有额外请求来补发 report，所以必须在最后动作之前插入。最后 wait 可以通过自动 wait-until 展开跨到末时刻；最后 observe 可以直达末时刻；提前 finish 也是其原轨迹的最后动作。已经 `now >= end` 则不报告。

官方没有独立的总 decision request 数量 quota；公开限制为自上次正确报告以来的误报免罚数、最大连续 report 数，以及全局墙钟。guard 从自己实际发送的原 report 和对应公开反馈维护计数，不重复计入 `report_result` 消息；correct 清零误报数。只有剩余免罚数大于零、连续 report 未达上限才允许插入。报告会多占一次真实请求、序列号和非零墙钟时间；`v4_workflow.py:252` 与 `269` 在请求前后检查截止时间，因此不能泛称“免费报告”。guard 在原动作选择和自身 ledger/Jain 扫描之后用单调钟扣减已用时间，要求仍至少 10 秒。这个余量是实际执行保护，并不能证明任意外部调度停顿都不会耗尽全局预算；真实 Linux matched run 必须完成预算 gate。

在两次请求及冻结动作都及时提交的前提下，false report 的无损结论来自它仍在免罚区间，结算为零、天气不变、冻结动作不变。correct report 奖励为非负，按官方损坏故障/修复语义改善效率，不改曝光时间、命中几何、program band 或 observation rank；既有有效 ledger 不动，science best、required 完成和非负请求奖励不会减少。这里采用官方 challenge 的损坏 instrument fault 语义；runner 自身的事件校验未强制任意自定义故障 multiplier 都小于等于 1，因此此论证不扩展到把“故障”写成增益事件的自定义场景。

Jain 是唯一可能反向变化的 score 项。终局 wait/finish 没有新曝光，Jain 伤害为零；终局 observe 即使增益也可能让某一 RA band 更不均匀，必须扣除最坏伤害，不能直接假设总收益为 100。

## 公开 ledger 与 Jain 上界

guard 只读公开 columnar catalogue、自己发送动作的 program、rounded hit score、resync 无效窗口、临时请求公开证书。每个 score 以六位小数舍入误差 `eps=0.500001e-6` 转换为 factor 区间：

`lower = max(0, score-eps)/(weight*max(declared_multiplier,mismatch))`；
`upper = min(1, (score+eps)/(weight*min(declared_multiplier,mismatch)))`。

区间截到 `[0,1]`，零权重或零分母按未知区间保守处理；旧 ledger 的无效 rank 被完全剔除。临时请求 `completed_target_ids` 给出该请求阈值的有效 factor 下界。发布消息先缓存阈值，因为 result 不带阈值；revised result 替换完成集合，不能并集保留旧证明；遇到 resync 还保守清除所有请求证书，再接纳当前权威证据。这个清除可能舍弃仍有效的过期请求证明，使安全门更保守，却不保留过时完成状态。

设各非空 RA band 的已有完成比例区间为 `[l_k,u_k]`，最终 assignments 中尚无完成下界证明的目标给出最大增量 `d_k`，`q_min=sum(l_k²)`，`s_max=sum(u_k+d_k)`，band 数为 K，均匀项权重 U。对 `P=U*(1-s²/(K*q))`，沿 repaired 最终 ledger 相对 control 最终 ledger 的单调比例路径，有正向偏导

`dP/dr_k <= 2*U*s_max²*(u_k+d_k)/(K*q_min²)`。

因此可能增加的惩罚不超过各偏导上界乘 `d_k` 的和，同时永远不超过 U。`q_min=0` 时用 U；没有可能增量时用零。只有 `worst_jain_harm <= correct_reward` 才插入。control 的最后曝光自身已有的增量也在 `[l_k,u_k+d_k]` 内，故这个范围覆盖比较的两份最终 ledger。请求 rewards 必须非负（官方 checker 强制）；请求窗口由同一 start/end 决定，插入 report 不改变它们。

## 已完成检查与证据限制

`public_entry/L1` 与 `/L2` 使用官方公开 initialize 和本策略已经完整跑完的 RequestCache control 输出。每卡运行原控制入口、wrapper disabled、wrapper enabled 三个真实 subprocess，每个收到三次 decision request 和两份实际本策略 score feedback。六个 subprocess 的 JSONL responses 在相同输入上完全一致，前三个动作也都与原 Linux control 记录完全相同。真实工厂 summary 为 `ExactCachedRequestRemotePlanner`，offline transport、remote calls=0；没有 initialize ACK、traceback 或远程调用。平台为 macOS arm64，NumPy 2.0.2，此短检不能替代目标 Linux NumPy 2.2.6 的整季验证。

原运行没有保存完整逐决策 snapshot，所以我们只恢复可由 actions/decisions/messages 与公开 score 投影证明的字段。`observations.csv` 在读取边界只保留 observe_index/target_id/score，未使用 factor/quality/prog_mult/fiber/valid 列。可恢复 now、rank、score hits/计数、report 结果、消息顺序、latest 公告；running_total 从 rounded 公开 best ledger 重建。原 wallclock 和请求执行中每一步的 authoritative completed_target_ids 不可恢复。短前缀发生在首次请求发布之前，active_requests=[] 正确；使用共同固定 0/900 时钟，不声称原时钟完全复现。完整重建文件中的 active_requests=[] 是 guard fixture，而非原 snapshot 的完整复制。详细声明见各卡 `*_public_reconstruction.json`。

完整记录的 1093/1214 动作作为 fixture 逐步喂给 guard，在最后动作前各插入一次；删除插入 report 后动作对象逐项等于原记录。这个检验不调用整季原 policy 重新选动作，不能称“真实整季 policy parity”。短入口检验加上 wrapper 的调用结构证明终局前不修改原动作；新增 guard 时间成本能否影响真实墙钟仍需 matched run。

| 本策略记录 | 最后动作起点 / 观察序号 | 最后动作 | 剩余免罚 | Jain 最坏伤害 | correct 条件收益下界 |
|---|---|---|---:|---:|---:|
| L1 | 2026-12-03 08:14:29Z / 984 | wait-until 08:15:00Z，31 秒 | 2 | 0 | 100 |
| L2 | 2026-12-14 08:13:58Z / 1087 | observe，62 秒 | 2 | 0.3326639711 | 99.6673360289 |

L2 gate 只接纳截至 rank 1086 的反馈，没有读取 rank 1087 的最终结果作为 gate 证据。L1 的最后 observe 已经结束，其反馈在末 wait 请求上公开，因此可以使用。上表是本策略公开记录安全审计，不是 report correctness 或实际分数增量。

`check_official_short.py` 另完成 9 项 quota、计时、request 证书撤销、resync、冻结 actor、ack、占用夜末裁剪约束检查，并在完全合成天气下让原官方 runner/protocol/scorer 处理 wait/observe/finish 三种 tail 各 correct/false 的 6 组短 matched packet。只有内存 scenario/footprint loader 被替换，runner 的 report/loop/scoring 代码不改；UTC/rank 不变、额外一次 request、精确释放 tail、false=0/correct=100 的合成结果均通过。所有合成输入和输出留在 `official_synthetic_packets/`，不使用真实卡 truth。全部检查日志、每次原始 stdout/stderr 均保留。首次分段阅读漏掉 runner 的 713–719 行，导致第一版错误声称只裁到 survey_end；独立审查后已修正，旧源码/包/报告/锁完整保留于 `FAILED_TIMING_AUDIT_1/`，没有在该版上启动真实整季。两卡最终夜末都等于 survey_end，修正后重新检查的 Jain 数值不变。

## 下一步真实 matched L3

`MATCHED_L3_PLAN.json` 已准备，但本次未启动整季、SSH、GPU、提交、自动化或 git commit。root 下一步可以在同一官方 L3、同一 image/NumPy 2.2.6、2CPU/2GiB/900 秒、独立核上同时运行新 `control_package` 与 `full_wrapper_package`。必须使用新真实 control 的分数和动作，不能用旧 native 6004... 或 native 四卡表。

先核对 source_lock/ZIP，再锁定每次启动与输出；两边都 complete 且无 timeout/OOM/traceback 后，仅删除 intervention 的新增 report，比较全动作、原 decision 字段、observe rank 和数据丢失方案。公开 gate、冻结和释放事件必须一致；false 时所有 score 项完全相同，correct 时 official report_result、实际 Jain 变化及总增量必须符合条件下界。若无插入或动作 parity 失败，也应原样保存并报告，不能宣布收益。仅通过这次真实 matched gate 后才能建立 RequestCache 上的实际增益证据。
