# 请求完成证据与数据失效账本

2026-10-03，基于官方完整 GPU direct L3/L4 回放及修复后 policy 的独立只读审查。

## 回放核验

`invalidated_by=V4ST0001` 表示已执行观测被数据丢失回溯撤销，不是非法动作。

| 卡 | 失效 observe 下标窗口 | 失效动作数 | 失效目标命中记录数 | 重同步最佳科学分 |
|---|---|---:|---:|---:|
| L3 | [91,92) | 1 | 16 | 4753.910966 |
| L4 | [231,261) | 30 | 441 | 3471.692464 |

按 CSV 中有效命中、observe_index < action_count_at_trigger 逐目标重新取最高 score：L3 的7241个目标、L4的5957个目标全部与 state_resync.best_scores 一致，没有超出六位小数舍入界的差异。失效索引按 observe 动作编号，不是 decisions.csv 的 decision_id；wait 不进入失效窗口。

最终 agent.log 的科学分与官方分不同，原因是季末最后一轮曝光结束后直接收到 finish，没有下一轮 decision_request 可接入最后的 last_result。官方 finish payload 只带终止原因和动作计数，没有最后命中或最终 best_scores。这个诊断差异不影响实际得分。

| 卡 | agent.log 科学分 | 去掉最后曝光的有效 CSV 重放 | 最后曝光增量 | 官方科学分 |
|---|---:|---:|---:|---:|
| L3 | 6011.048522 | 6011.048522 | 3.953852 | 6015.002344 |
| L4 | 5693.024465 | 5693.024465 | 5.422038 | 5698.446503 |

L3 CSV 全部有效六位小数分相加为6015.002374，较官方内部未舍入累积结果约多0.00003；这属于逐命中输出舍入。L4相加完全相等。

## 发现的两个时序缺口

1. 已过期请求曾公开确认 A 的 factor≥.5。原始 score 有程序倍率歧义，只能推出 lower=.48。后来一次无关数据失效仅撤销 B，原 _resync 重建原始 lower 数组，使 A 从 .5 降到 .48。官方仅在请求完成签名变化时重发已过期结算，A 的有效证明没变化，因此不会再次发送结果。原实现永久丢失已公开的确定证据。
2. wait-until 等动作可以令 observation_request 发布与 observation_request_result 首次在同一批消息送达；此时请求已经过期，不在 active_requests。原实现忽略发布记录，缺少阈值缓存，结果消息又不携带阈值，故将完成证明按 threshold=0 忽略。

当前两条 GPU 回放中，首次已过期请求的六个已完成目标，在重同步后由原始有效 score 推出的 lower 均仍≥.5；因此第1个缺口在这两张卡没有造成实际完成误判。缺口由合法最小消息历史复现，不是将 C/E 拟合当作 factor 真值。

## 修复的账本语义

修复后的 policy 增加三类持久状态：request_thresholds、request_completed（每请求最新权威集合）、request_proofs_changed。

- 先遍历整批新消息，缓存所有请求发布阈值；即使已经过期也缓存。
- state_resync 先按 observe_index 撤销原始 ledger，再从有效观测重建，并采用官方 canonical best_scores。
- 活动快照、重同步中的活动请求和结算/修订结果更新对应请求的最新 completed_target_ids。集合替换，不能仅追加。
- 整批消息处理完后重放全部最新权威完成证明，包括未重发的已过期请求。
- 完成集合变化时，先从有效原始 ledger 重建 factor/lower，再对各请求证明取 max，撤销旧集合同时保留其他请求对同一目标的有效证明。

官方请求完成判定来自请求窗口内、未失效的真实最大 factor。因此完成目标给出的 factor≥threshold 是科学分倍率无关的证据，可以提高全季原始完成下界。它不是某次曝光的精确 factor，也不应伪造某个 observe_index 来挂在原始观测上。

应依赖最新公开权威集合维护其有效性。官方在 data loss 后同时更新活动请求，并为已过期、完成签名发生变化的请求发送 revised 结果；签名未变化则旧完成集合仍成立。

## 独立复查与回归

修复后独立调用实际 Policy._messages，在内存最小账本上验证六个历史，全部通过：

| 回归 | 预期及实测 |
|---|---|
| 首次同批发布+结算，active_requests为空 | A lower=.5 |
| 无关 resync 仅撤销B，过期请求未重发 | A lower保持.5，B lower=0 |
| revised 完成集合变为空 | A回落到有效原始 lower=.48 |
| 两请求对A分别证明.5、.6 | A lower=.6 |
| 撤回.5请求，.6请求仍成立 | A lower保持.6 |
| resync撤销A原始曝光，随后revised撤回A | A lower=0，canonical score=0 |

只读审阅未发现新增的协议/账本错误。阈值在当前协议中对同一 request_id 固定；若未来协议允许修改阈值，需要同时把阈值变化视作 proofs_changed。当前实现没有必要为这种未公开协议增加处理。

本次未修改 policy。官方依据：v4_runner.py 的 state_resync 与请求差分结算（约526–598行）；v4_scorer.py 的 invalidate_window/request_factors/observation_request_status（约434–494行）；v4_workflow.py 的 finish_payload（210–214行）。
