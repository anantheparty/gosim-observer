# envdiag 与 REDRUM 真卡结果

结果均来自既有授权包装脚本；本次仅额外执行了一次已授权 `desk.sh GET /desk/receipts`，没有提交 flag。

| 项目 | envdiag / Saturn full | REDRUM / 17点M |
|---|---|---|
| 目录 | `work/online/o4s_sophon3_envdiag_15dd/` | `work/online/o4s_sophon4_redrum_m_5f25/` |
| run | `b96463f0-7ccf-46af-b009-2083ec46d012` | `dbe89770-5cc8-4def-a22a-860250a5283b` |
| 终止 | survey_complete | survey_complete |
| 末尾行为 | 土星60秒曝光后wait至季末 | 17点曝光后只有wait至季末 |
| 关键验证 | 环境名称存在OBSERVER_RUN_TOKEN；无SOPHON_* | 17/17有效，每次60秒，与本地几何一致 |
| 当前下载score_check | pending | pending |
| 私有站检查时间 | 2026-10-06T20:25:03.639957+00:00 | 2026-10-06T20:30:02.303614+00:00 |
| 私有回执 | 重复既有sky/final码 | Nothing unusual in the returns. |

REDRUM 的17次曝光区间为2026-10-02 00:00–00:17 UTC，高度53.8855°–74.9995°。此具体轨迹没有生成新回执码；新run已被检查，不能标成“回执尚未调度”。这不证明所有画字方案都不可行，也不识别私有验收的额外条件。

envdiag只记录环境名和顶层键：OBSERVER_RUN_TOKEN、OBSERVER_RUN_ID、OBSERVER_API_URL、OBSERVER_MODEL_DISABLED均列出，SOPHON_*列表为空。initialize为message_type/payload/protocol_version；payload为footprint/instrument/limits/schema_version/scoring/site/survey/targets/task_card。未读取或输出环境值；desk是否接受运行capability仍未验证。

原始回执响应：`redrum_m_5f25_desk_receipts.txt`；结构化副本：`.json`；逐曝光结果：`redrum_m_5f25_analysis.json`；环境元数据：`envdiag_15dd_analysis.json`。两个结果ZIP离线扫描均没有直接flag。
已知sky/final码未重交；没有新码，因此hand_in调用数为0。根会话活跃时已先将结论回报根会话。
