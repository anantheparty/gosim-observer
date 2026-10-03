# 冻结的 terminal report 微实验（读取 L3 truth 前）

依据：只读四条自然控制公开 actions/decision timestamps、hit score 和 state_resync/report_result；没有使用 factor/quality/prog_mult 标签或 terminal teacher labels。公开审计脚本 `terminal_report_audit.py` 的 `read_selected_csv` 明确只取所列公开等价字段。

唯一具体评估点预先固定为 L3 `2026-12-22T07:59:58Z`，observe rank 992，原下一动作整段到公开 survey_end `2026-12-22T08:15:00Z`。理由是四卡自然控制中 L3 唯一没有历史正确 report，且公开完成比例可给出终末修复的 Jain 最坏损失小于 100；不按真实故障时刻挑点。

冻结动作：在最后已决定的原动作之前发 **一次** `{ "action": "report" }`，下一 round trip 不经 planner、也不更新其 C/E/terrain/ledger，用本文件同时保存的 `public_audit.json` 中 L3.final_action 原样发出。正常末动作仍为902秒、同program/pointing/13 assignments。没有新增 observe，没有加 probe，没有改时长、纤维或program。

一般可部署触发规则：公开 now 与 survey_end、冻结 planner 动作的实际终点可以确定这是最后一个动作；该动作之后不再 replanning；已有 report_result 可确定 false_count 小于 allowance；当前公开 factor 上下界证明最终 assigned targets 最坏 Jain 损失小于 correct_reward；剩余 wallclock 应足够两次额外协议处理（建议保留10秒）。一次 terminal gate 只触发一个 report，不花光两次额度。

预先假设：故障可能存在，也可能不存在；不预先声称 L3 的 report 会 correct。false 时免费额度使直接分差0，冻结末动作保证轨迹不受belief更新影响。correct 时报告+100，修复不改变program band，原同一末动作的科学分/required/REQ非减；observe rank、时刻、data-loss窗口和几何不变。唯一负边际是Jain，公开区间解析界为0.7021997616960498，因此correct总收益至少99.29780023830395。这个是条件局部证书，不是已测全季策略。

Evaluator允许只读完全公开 local-cards/L3 truth 和已有自然控制官方CSV，核验以下事实：report correctness、奖惩、最后曝光积分/几何与原始final observation一致、报告修复后的分差、原前缀ledger不变、Jain与所有奖励、时钟与observe rank不变。不得读取bulk/pair_audit/terminal_target_labels，不据truth修改该点、动作或触发门槛。不跑全季、不改生产代码。

若false或门检失败，保留失败；不换别的点救结果。官方四卡控制total为6362.021539/6823.661561/6004.504542/5974.281941，但本实验只修改和评分最后局部动作，不称新四卡完整成绩。
