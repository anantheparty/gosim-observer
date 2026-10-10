# jfull 复核后：回执与首封邮件重新判断

本轮只读取本地产物、练习卡和公开源码，未联网、未读凭证、未提交 flag。

## 结论

目前更值得查的是 **Sophon 专用验收/投递是否执行，以及旧 Johnny 流程与新 desk 是否相通**，而不是先提高巡天总分。
`verified` 仅证明普通评分重放一致，不证明 Sophon 已验收，更不证明应有回执已生成。
首封邮件能唯一复现的是解密结果；还不能唯一推出一个可提交的签到 flag。

## 新证据与边界

| 事实 | 支持什么 | 不能推出什么 |
|---|---|---|
| jfull 的 run.json 只从 pending 变为 verified；ZIP 全部成员内容相同 | 已独立核对；普通复核没有改写下载产物。 | 不代表私有 Sophon 检查器执行过，也不排除另存数据库/邮件。 |
| 本次重扫 jfull v2、Venus，各 10 个文件/ZIP 成员，均无 flag | 已下载的这些内容没有直接出现 flag。 | 不代表不存在未公开或未投递的回执。 |
| jfull 总分 −2882.489535 仍 verified | 负分不会一律阻止普通评分复核。 | 私有 Sophon 是否另设条件仍未知。 |
| 4 次提前 finish 一直 pending，季末结束的 jfull 已 verified | 当前这些运行的实测差异成立，后续实验保留 survey_complete 更稳妥。 | 不能据此断言平台的正式规则是“只复核季末结束”。公开调度源码没有此过滤，测试明确把 agent_finished 排入 score 队列。 |
| sophon1 有 token、contact-johnny 成功后收到邮件；之后没有 token | Johnny 是已经实际验证过的投递渠道；当前同一路径没有被调用。 | 不能仅凭时间相关认定重开阶段造成故障，也可能存在只发一次、阶段绑定或私有配置变化。 |
| 所有批次 model_disabled=True | 排除用这一个布尔差异解释 token 消失。 | 不等于排除其他运行配置/阶段配置差异。 |

普通 score_job 重放 decisions/actions、比较摘要并返回数值分数；SQL 的 verified 条件是重算总分与原总分在容差内一致。
该公开路径没有 Sophon 条件检查或回执投递代码。它也不会重启参赛智能体去联系 Johnny。
所以“等 score 步骤补出 flag”没有公开实现支持；ZIP 不变恰与普通复核实现一致。

源码位置：

- `hackathon-survey26/project_platform/job_runner.py:351`：score_job。
- `hackathon-survey26/supabase/migrations/20261005200100_super_board_ad_unchanged.sql:63`：verified 判定。
- `hackathon-survey26/supabase/migrations/20261002000500_public_runner_pool.sql:268`：待复核查询，不筛总分或终止方式。
- `hackathon-survey26/supabase/functions/_shared/observer-orchestrate_test.ts:426`：agent_finished 也成功排入 score 队列的测试。

## a. 总分门槛与回执位置

jfull 的分数是 `5234.183924 − 8050 − 66.673459 = −2882.489535`。
8050 来自漏掉 161 个普通必测目标，每个扣 50；不是 Sophon 失败惩罚。
练习 sky 检查只要求至少 3 条符合夜晚/onset/光纤条件、有效且单行 score > 0 的观测；
dive 只看最后一次 observe 的指向与行星高度。两者都不读总分或 required_missing。
网页还明确写“本榜分数仅供参考，不计入任何排名或奖项”。这些都让隐藏总分门槛的假说优先级下降，
但练习判据不构成私有真卡判据的证明。

历史 sophon1/2 已有约 +8007 分且跑满季末，仍未见这套新 flag：这反驳“只要正分就一定收到”的简单解释。
旧运行早于新 desk 完整上线，故不能严格排除新验收另加门槛。
本地 sophon2 的旧 run.json 仍写 pending；其后来 verified 采用主会话最新平台查询，不能拿旧快照反驳。

| 优先级 | 回执可能位置/环节 | 现有证据与下一步 |
|---|---|---|
| 高 | Johnny 的异步邮件，或与之相连的私有服务状态 | 唯一已经观察到的真人可见投递通道。当前无 token，原路径未被触发；用户确认只有首封邮件，所以暂不能说“藏在新邮件里”。应核实现在是否仍应注入 token、真实回执设计投递到哪里。 |
| 高 | 独立的 Sophon 验收记录尚未产生/未被触发 | 普通 verified 与彩蛋验收不同。新榜由私有 sophon 函数写，公开 scorer 不写。可能是验收条件未中、旧/新流程脱节或投递异常，目前无法区分。 |
| 中 | 评测详情原始响应、完整 score diagnostics 或后续私有服务日志 | 已知只读入口。重点查“是否执行 Sophon 检查、是否有跳过原因”，不只扫 SOPHON 字样；但这些字段是否存在未获公开合同保证。 |
| 中低 | desk/flag 的成功响应、通关记录 text_en/text_zh | 正确答案可能推进关卡并返回下一条信息；这是后续输出，不是无答案领取回执的已知接口。新旧 API 的响应字段差异也需留意。 |
| 低 | 结果 ZIP 或已知下载文件被异步更新 | jfull 重下后没有变化，优先级降低。前端只有两个固定下载名，没有公开“领取回执文件”按钮；不据此猜文件名或接口。 |
| 低 | 站内私信 | 当前为空，也没有公开代码证明 Sophon 使用它。 |

首封旧邮件可能是剧情/密码学前置关，新 sky/dive 收据可能是另一条流程。
旧 sophon_solves 的 key、强制 run_id 与新 g_solves 的多关/debug/auto 模式不同，公开代码没有迁移对应关系。
因此收到旧谜题邮件，不能证明已经获得新 CTF 的“签到关”题面或交卷规则。

## b. 五个候选如何重新看

以下沿用原来的五个，**没有新增猜词，没有提交**。本次运行结果没有增加它们任何一个的准确格式证据。

| 顺序 | 候选 | 适用假说与当前评价 |
|---:|---|---|
| 1 | `SOPHON{house-of-leaves}` | 若签到关收“解密指向的书名”，这是最直接的语义答案；仅格式不同于已拒的大写无分隔版。小写连字符来自练习示例，真卡是否采用未知。 |
| 2 | `SOPHON{43728561}` | 若要交的是加密密钥，这是经明密文往返核对的逆映射；不是任意反转。旧 key 列名并不能证明所求为此，故仍低把握。 |
| 3 | `SOPHON{johnny-truant}` | 若书名只是中间线索、要认出 Johnny 身份，则有文学关联；题面没有明确要求。 |
| 4 | `SOPHON{zampano}` | 若日期是关键、要认出注记作者，则有旁证；引用的是此前查到的读者年表，未获比赛官方确认。 |
| 5 | `SOPHON{the-shining}` | 天空给出的另一条稳定线索，格式假说同第一项；不能称作首封邮件的签到答案。 |

Mary、字母、干扰项与置换顺序的分析维持上一份报告：其余数学信息已经用于筛选/解密，Mary 没有唯一的额外抽取方法。
完整明文更像后续指引，也可能直接指向书名；仅凭“签到题应该简单”不能补出唯一花括号内容。
422 的 wrong_answer 仍只说明提交值不被接受，既不证明必须是动态签发串，也不证明换大小写就能过。

## 下一步最有区分力的确认

1. **先确认服务合同**：由主会话/用户在既有渠道询问当前 Sophon 是否应注入 SOPHON_RUN_TOKEN，以及真实 sky/dive receipt 的指定位置；附 sophon1 与 jfull 的运行 ID、token 存在性、verified 时间即可，不含 token 值。本报告没有代为联系任何人。
2. **已有只读材料**：保存 jfull 的完整 score diagnostics，并以同一登录身份核对 current_competition 的 extra_phase_id、新三榜及旧 sophon_solvers；榜单过滤问题仍独立存在。
3. **若继续做线上实验**：保持 survey_complete。当前只有木星跑满并 verified，其他三颗行星的提前 finish 结果，不能作为“经过同样验收仍失败”的覆盖证据。不过 sky 理应独立于选哪颗行星，缺全部回执更值得先排查验收/投递。没有新的门槛证据前，不把大量时间投入追巡天分数。

扫描记录：`validation/sophon3_jfull_54e0_v2_offline_review_receipts.json`、
`validation/sophon3_venus_6fc6_offline_review_receipts.json`。
首封邮件完整推导及文学旁证：`johnny_first_mail_analysis.md`。
