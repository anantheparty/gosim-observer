# Sophon 木星真卡：结构对比与 receipt 排查

比较：`work/online/sophon2_f599/` → `work/online/sophon3_2d79/`。只读原始产物，未调用平台。

## 结构结论

| 文件 | JSON 路径数（含根与容器） | 新增 / 删除 / 类型变化 |
|---|---:|---:|
| workflow_result.json | 78 → 78 | 0 / 0 / 0 |
| score_report.json | 48 → 48 | 0 / 0 / 0 |
| run.json | 32 → 32 | 0 / 0 / 0 |

ZIP 文件集合完全相同：actions.jsonl、agent.log、decisions.csv、egress.json、messages.jsonl、
observations.csv、score_report.json、workflow_result.json，共 **8 个文件**（另有一个目录条目；此前“9个文件”的说法不准确）。
两份 ZIP 的 40 字符 archive comment 都恰好是 result_path 的 Git commit，不是新回执。

变化均为已有字段的值：分数/计数/运行时间/ID/摘要；新运行 termination_reason=agent_finished，
旧运行 survey_complete；fair_clock.hard_cap_seconds 从 3600 到 10800。没有新增 Sophon 状态字段。
两份 run.json 的 score_check 都是 pending，不能把它当成 Sophon 专用验收状态。

## 完整性与补充扫描

- 两次 decisions/observations/messages 的文件 SHA-256 均符合 score_report，run.decisions_digest 也匹配。
- workflow_result 内嵌 score_report 与独立 score_report 完全相同。
- 两次独立 agent_log.json 均 truncated=false，log 与 ZIP 内 agent.log 逐字节相同。
- 新日志有 30 个完整字形记录，无 `?`；messages 只有 1935 条 bulletin、9 条 forecast，没有新增 Sophon 消息。旧日志另有两条 report_result。
- 新运行 finish payload 只有标准 v4 字段，无 receipt；egress.json=[]，没有 Johnny HTTP 回复。
- 除原扫描外，还扫描了解码后的 JSON 字符串（排除 Unicode 转义漏检）、ZIP comments/extra；两次仍无真实 SOPHON{...} 串。因此本次没有调用 hand_in.sh。

完整字段/数值差异：`validation/sophon3_vs_sophon2_structure.json`。
完整性检查：`validation/sophon3_vs_sophon2_integrity.json`。

## token 缺失意味着什么

新真卡日志为 network_allowed=true、credential_present=false；两个 johnny_skip、零响应。
这排除了本地 SAC_LOCAL_RUNNER 禁网开关误触发，也不是 Johnny 请求超时或被拒绝：请求根本未发出。
只能确定 participant 进程没有可用 SOPHON_RUN_TOKEN；公开代码不能进一步区分未签发、未传递或另有前置步骤。
7 夜 / 16 光纤通用公开测试不是 Sophon 真卡，因此那里无 token 本身不是故障证据。
公开 orchestrate/runner 源码未找到 Sophon token 注入或 receipt 验收实现；相关文档不能证明私有部署实际已接通。

目前优先考虑“地面站在 participant 之外验收/递送，或本轮尚未触发该环节”，
而不是结果 JSON 有一个被忽略的现成字段。新 Johnny 回复在本轮已可排除；用户邮箱仍未检查。
若地面站也没有收到运行，换行星无法修复 token/验收路径；四星结果仍能检验行星条件，但不是该路径的保证。

## 主会话下一步可只读确认

1. **完整平台 diagnostics**：本次下载的 agent_log.json 只有 available/bytes/truncated/log，**不含 diagnostics**。
   因此尚未验证评测详情「评分/引擎」的独立诊断。针对实际 RUN 使用
   `survey26 --json results log d76dd617-37cb-4d25-a604-654ed77239c3 --full`，或正常展开页面诊断。
   目录名 `179e0a27-...` 是 scenario_id，不是 run_id，查询时不要混用。
2. **本轮批次上下文**：查看批次 `2d79ab4b-3b0c-40cc-b2fb-42e92db5e636` 所属 phase_id/slug，确认它是当前开放的 Sophon extra 阶段；已确认运行的确使用 Sophon 天空，但下载的 run.json 不含 phase 归属。
3. **已存在的只读响应**：复核 `desk/files/<name>` 原始 JSON 是否有 URL 以外字段；本队 Sophon 页面/RPC 是否后来出现 auto 记录或 finishers 文本。没有证据时不猜新路由、不重复提交旧猜词。
4. **刷新后的元数据/诊断/结果**：在评分完成后稍后再读一次，比较是否有新结果引用、诊断步骤或时间。现有 ZIP 的 commit 是固定快照；当前快照无回执不能排除事后递送。不要把 score_check 的变化直接解释成彩蛋状态。
5. **邮箱交用户检查**：由用户查看原 Johnny 邮件线程与本次完成时间（18:15:20 UTC）附近的新邮件/附件；我们不访问邮箱。

另一个待证实的触发差异：新包最后曝光在 08:14 结束后 finish，距季末 08:15 尚有 60 秒，
因此平台标记 agent_finished。练习检查器明确接受它；私有地面站是否只处理 survey_complete 未知。
若四星都无回执，应先核对验收入口/完成条件，再决定是否另测“最后曝光后只 wait 到季末”。
本轮没有修改已上传/待跑包，也没有据此启动新评测。

收到另外三颗行星下载通知后，继续离线扫描；只对实际出现的真实 flag 使用获准的 hand_in.sh，逐次回传原样回复与来源。
