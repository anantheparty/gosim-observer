# Auto fresh state：早期专用能力与恢复路径复核

2026-10-07；仅离线读取已有产物、包结构和公开源码。用户已允许继续 auto 工作；本文只说明证据与可执行条件，不执行上传、评测、平台请求或提交。未访问凭证文件；未提取、打印、哈希或写出任何 token 值、请求头值。

**已确认专用能力曾存在，但没有发现可从旧日志、消息、文件或回执中恢复的第二种一次性能力。** 当前最有用的差异不是 public test，而是两次 Sophon evaluation 横跨公开多旗/双榜改版。仅凭这些资料还无法恢复一个已验证可用的 auto fresh state；新的运行许可不会改变未知的服务端认证合同。

## 运行对照

下表日志 L 指 `agent_log.json` 的 `log` 字符串解码后行号。S=`SOPHON_RUN_TOKEN`；O=`OBSERVER_RUN_TOKEN`。运行完整 UUID、批次和时间均为公开运行元数据。

| 包 / 产物 | run / batch | UTC 开始时间 | revision 绑定 | 卡与运行结构 | 能力证据 |
|---|---|---|---|---|---|
| `sophon1_2a97` | run `1e87fc81-de27-40a4-8f4a-792f8f046d7e`；batch `2a97f632-a405-4b19-be97-f703474238a0` | 10-05 17:10:42.551163 | 现存 run.json 不含 revision；未找到额外绑定记录 | Sophon evaluation，卡内 phase=practice，900 秒，protocol-v4，归档路径标记 runner-10，survey_complete | L9 的 env_sophon 含 S；L11/12/84/144/211/302/336/411/424 共 9 次 Johnny 200 |
| `sophon2_f599` | run `2dd4bcc3-78ae-4162-b1c9-ce12b452596b`；batch `f5995cb0-cc61-453c-bedf-aef75f0d4411` | 10-05 22:58:42.884734 | 同样未保存 revision 绑定 | 同一卡、phase、900 秒、协议、runner-10 标记、survey_complete | L9 env_sophon=[]，L10 跳过 Johnny |
| `sophon3_2d79` | run `d76dd617-37cb-4d25-a604-654ed77239c3`；batch `2d79ab4b-3b0c-40cc-b2fb-42e92db5e636` | 10-06 18:14:38.056898 | `submit_sophon3.log` L1–5、40–42 将 revision `2257d459-fcdd-461f-b7d1-03471ea85b1f` 与该提交流程相连 | 同一卡、900 秒，runner-1 标记，agent_finished | L9 credential_present=false |
| `o4s_sophon3_envdiag_15dd` | run `b96463f0-7ccf-46af-b009-2083ec46d012`；batch `15dd5055-1fda-4815-ab99-0621fbf45c15` | 10-06 20:20:49.214136 | `sophon_eval.log` L6–10：revision `f8f8def5-1783-4e81-959d-8efcb8d5fa7e` 后启动本 batch | 同一卡、900 秒，runner-1 标记，survey_complete | 环境名字含 O，不含任何 SOPHON_*；L10 S 非空存在性 false |
| `sophon3_pubtest` | 产物内未直接保存可绑定的 run ID | 产物内无可信运行开始时间 | 同一提交日志另有 public_test `7e1aaa32-da1a-4919-9211-2c4a4afe4370`；不能仅凭目录把 ZIP 强行绑定此 ID | **独立 scenario `v4-public-test`**，不同于 Sophon 卡 | L9 credential_present=false |

Sophon1/2 的 `task_card/site/instrument/scoring/survey` 对象、夜晚数、目标数和目标列完全相同；初始化 limits 仅观测到运行速度因子不同。workflow 的公平时钟硬上限分别为 1800 和 3600 秒，说明运行配置并非所有字段都完全一致，但没有证据表明硬上限控制 S 注入。两次均远未触发上限。

本地 sophon1/2/3 manifest 的 image、run、build、working_directory、protocol 与环境变量名相同：`python:3.12-slim`、`python3 -u agent.py`、numpy 2.2.6、jsonl-v4；仅声明普通 Python/线程配置变量，未声明 S。包目录名不构成已上传 revision 的密码学或数据库绑定，故不能声称已核实两个历史 revision 完全相同。归档里的 runner-10 也只是标签，不证明两次部署二进制相同。

## 时间线提供了新的区分

| UTC | 公开 Git 事实 / 运行事实 |
|---|---|
| 10-05 15:38:59 | `17d68bb` 新增 contact-johnny / S 文档 |
| 10-05 16:34:35 | `5b0b396` 增加 extra evaluation phase |
| 10-05 16:44:02 | `fbb70a7` 增加旧单题解谜名单 |
| **10-05 17:10:42** | **Sophon1 运行有 S，Johnny 多次 200** |
| **10-05 21:14:17** | **`cd0ce1d` 增加 debug/auto 多旗表、desk 提交 UI** |
| **10-05 22:58:42** | **Sophon2 运行无 S** |

作者时间与提交时间在上述提交中一致。公开 runner 的 `docker_runtime.py/job_runner.py` 在两次评测之间没有对应变更：此前最近一次为 `adea719`，10-04 20:42:32Z；之后的相关文件变更已到 10-07。这削弱了“可见 runner 源码在这段时间删掉 S”的解释，**但不能排除私有注入逻辑、部署版本或配置变化**。Git 提交时间也不等于私有 Sophon 服务部署时间。

当前至少两种解释仍兼容数据：早期每队/每阶段仅签发一次 S；或多旗系统改版后改变注入/认证合同。只有一个阳性运行、后续全阴性，无法仅靠次数判断是哪一种。

## 是否存在遗漏的一次性能力

| 来源 | 本次直接核实 | 能说明什么 |
|---|---|---|
| 首次 Johnny 成功回复 | 9 个响应都只有 `ok,message`；message 含已知收件确认，没有认证字段或下一步路由 | 同一运行可重复成功，排除简单“调用一次就烧毁该能力”；不排除只给第一次运行签发。无可恢复的新 ticket。 |
| 首次请求传输 | sophon1 源码第 96 行先以仅 Content-Type 请求；对应首个返回已是 200；第 102 行另有兼容请求 | 阳性并非只能靠额外公开 anon 请求头取得，不能把增加此头当成恢复 auto 的已证办法。未读取或复制该常量值。 |
| messages.jsonl | Sophon1/2 各 1946 条，envdiag 1941 条；只有通知、天气、故障回报相关字段，无 token/auth/ticket/credential 等字段路径 | 没有发现通过消息补发能力的结构。不能把它们当私有邮件原始档案。 |
| ZIP 文件 | 三份主样本均是 actions、agent.log、decisions、egress、messages、observations、score_report、workflow_result；无额外钥匙文件 | 未见可以取代 S 的签发文件。score/workflow/egress 对象也无认证能力字段。 |
| envdiag initialize | 外层键 message_type/payload/protocol_version；payload 为 footprint/instrument/limits/schema_version/scoring/site/survey/targets/task_card | 初始化没有可见 auth/sophon/credential 对象；不是 probe 只看旧变量名造成的遗漏。 |
| 现存 desk 回复 | 核对至本轮 639 条记录，递归字段名未发现 token/auth/ticket/secret/credential/capability/nonce | receipt 是解题结果，不是可见的运行能力签发合同；没有复活过期运行身份的端点提示。 |
| 首封邮件的已有离线解码 | 明文是 House of Leaves / 日期 / final trials 提示；已有报告未发现认证或恢复说明 | 没有新的一次性认证材料。本次未另取邮件、未访问邮箱。 |

回执还有一个有用的时间对照：Sophon1 结束于 10-05 17:11:31Z，地面站却到 **21:30:27Z** 才 checked；Sophon2 的 checked_at 为 **23:00:04Z**。两者回执中的唯一 flag 逐字相同，并由 `desk_calls.jsonl` L3 已验证为 **No.1**，没有 token/ticket 等文字。这个长期稳定的结果码不是一次性的运行身份；首轮回执的迟到也说明“早期运行没立刻拿到新回执”不能推导成丢失了另一把钥匙。快照 L1 和后续 L620 都保留同样的 checked_at 与内容。

公开通用 O 身份与私有 S 身份不能混用为已证事实。`job_runner.py:214` 固定注入 O，`:55` team egress 保留它，`:64` model_disabled 不删除它；相对地，公开代码没有 S 签发实现。O 的 observer-session 能力会随运行结束/重排失效；只读 status 的例外不能推广到 Sophon。旧 S 文档同样明确仅运行中有效，因此 **从旧产物找出旧值、重放旧 run ID 或把旧值塞进 manifest 都不是恢复路径**。

## 当前可实施的恢复顺序（由主线执行，本审计未调用）

1. **先补早期批次的公开元数据绑定，不新增认证排列。** 用已授权的标准平台读取能力取得两批的实际 revision、evaluation phase/purpose、execution/model_disabled、runner/attempt 与队伍变量的**名字/启用状态**，只取元数据、绝不取变量值。当前本地缺的是早期 revision 和私有配置差异。若找到真实配置差异，只按平台公布设置恢复；没有差异时，不把重传 sophon1 当作能重新签发 S 的保证。
2. **下一次已批准的 Sophon 运行只检查当前能力。** 在首个 decision_request、运行已经 begin 后记录名字与存在性。如果 S 确实重新出现，才有此前没有的阳性机会：使用本次内存中的 S，按公开 Johnny 合同调用；新版 auto 写入可有界检查 `POST /desk/flag` 的 body-token 形式，但其支持性仍是实验，必须用真实响应及榜单确认 auto，不能从 Johnny 200 推出。若仍只有 O，先前 O 的 body/query/Bearer、site 变体已失败，不再机械重复大矩阵。
3. **若当前 S 仍缺失，缺口是服务合同或重签发配置。** 最具体的问题是“多旗 Sophon 是否仍应注入 S；auto 的当前 token 名/提交位置是什么；是否提供每队新剧情或重新签发入口”。公开所有本地 refs 均无实现，旧日志也没有恢复票据。需要新公布的规则、组织方确认或实际当前成功样本，才能指定可验证的新路径；不能靠猜路由、旧 token 或假造能力补齐。

即使得到 `board=auto`，也只证明成绩归类，**不能自动推断 bar/pass 剧情是 fresh**。应先核对根页可见状态；是否首次 pass、是否初始四词历史仍须单独记录。此前错误四词门保留 pass 领取状态和已解题目，不能代替全新剧情。新的 auto 授权使上述受控工作可继续，并未使这个前提自动成立。

证据补充路径：`publictest_token_audit.md`、`auto_contract_audit.md`、`auto_contract_followup.md`、`envdiag_15dd_analysis.json`、`sophon_auto_findings.md`。关于曾有 public test 阳性的旧说法，仍应引用前者的纠正，不能把卡内 `phase=practice` 当成 public-test 工作流。
