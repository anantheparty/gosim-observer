# Auto 合同补充：生命周期、复核/回执、GET 与 POST

本轮只读本地源码、可见全部 git refs、既有 online 产物和 desk_calls 日志；未联网、调用平台/模型、读取凭证文件、打印运行 token 或修改任何包。

**新增结论：** 首次 decision 后探测仍是正确的时机；但 GET `/desk` 可达不能作为 POST `/desk/flag` 可用的必要条件。CTF 回执不要求正分或 `survey_complete`，也不必等 score 复核成功。公开代码仍未揭示 auto 认证及归榜实现。

## 1. 历史覆盖范围与否定结果

HEAD 仍是 `373d94f`。本轮 `git rev-list --all --count` 为 **377**，包括本地 tags 可达的旧历史，最早可见到 2026-09-27；HEAD 单独可达 59 个提交。之前报告的“59”是 HEAD 范围，应以本轮 all-refs 范围补足。仓库仍标记 shallow，不能声称远端最初以来的完整历史已获取；本轮没有 fetch。

对全部 377 个可见提交搜索文件变更与 `SOPHON_RUN_TOKEN/contact-johnny/sophon/closed`：

| 发现 | 解释 |
|---|---|
| Sophon 相关历史路径只有引擎模块、两个测试、两份 SQL 和 SophonBoards.vue | 没有发现曾公开后删除的 Sophon Edge handler、token 签发器或 auto solve 写入器 |
| `17d68bb` 是 contact-johnny 与 SOPHON_RUN_TOKEN 文档的唯一引入变更 | 旧 JSON-body 合同保留；没有新版 desk 的认证迁移文档 |
| OBSERVER 运行身份变更涉及 `524a6c8`、`b1466d6`、`d7db970`、`de1db4f` | 分别是已有 runner、模型协议、team egress、model_disabled 路径；没有 Sophon 专用凭证分支 |
| starter 的 v4_sophon 与主代码只有私有夜晚/光纤表与得分覆盖 | 没有 HTTP、flag、receipt 或 auto 榜逻辑；本地 practice checker 不能代表服务端认证 |

`challenge/v4_sophon.py:26` 限制 config.task_card.phase 为 practice，是**引擎卡片字段**约束；不能解读为“只有上传预检/public test 才获准 auto”。平台 evaluation phase、batch purpose、卡内 phase 是不同概念。

## 2. 运行 token 生命周期：可以确认到哪里

| 阶段 | 公开机制 | 对探测的影响 |
|---|---|---|
| 调度 | scheduler 为 engine 与 participant 分别创建 capability；participant 获得 OBSERVER_RUN_TOKEN | 只使用本运行 participant env，不借 engine、其他运行或宿主凭证 |
| initialize | colocated 先发 stdin initialize，随后 ready，再 begin | initialize 线程可能早于 running；原 b9ea 两请求有时机歧义 |
| 第一个 decision_request | 只有 begin 返回后才进入工作流决策 | 首次请求到达、尚未返回决策时同步探测可排除 starting/ready 竞态 |
| 活动期间 | 通用 capability 校验 starting/ready/running、哈希、scope、expires/deadline | 这是 observer-session 合同；私有 Sophon 是否相同未知 |
| agent 收到 finish | v4 工作流已结束，但 runner 尚未上传结果/提交数据库 finish | 不是稳定的“运行已结束”认证对照；此时数据库可能仍是 running |
| 上传完成并提交 finish | engine capability 写 score/result_path，run 转 scored | 通用可写/模型能力失效；之后调用不适合验证运行内 auto |
| 重排重启 | capability 轮换 | 不复用旧 attempt 的值 |
| 已结束后的通用 status | observer_run_status 例外允许原 capability 读状态/expired/termination | 不能把这个例外推广到 Sophon `/status` |

精确证据：

- [trusted_engine.py:127](/home/shu/kamico/observer/hackathon-survey26/project_platform/trusted_engine.py:127)、[fair_clock SQL:27](/home/shu/kamico/observer/hackathon-survey26/supabase/migrations/20261004060000_fair_clock_session_deadline.sql:27)：initialize → ready → begin/running。
- [trusted_engine.py:227](/home/shu/kamico/observer/hackathon-survey26/project_platform/trusted_engine.py:227)、[job_runner.py:332](/home/shu/kamico/observer/hackathon-survey26/project_platform/job_runner.py:332)：发 agent finish 后返回工作流结果，随后 pack/upload，最后 `client.call("finish")`。因此不建议用 finish 回调探测认证期限。
- [finish_status_reason.sql:3](/home/shu/kamico/observer/hackathon-survey26/supabase/migrations/20260928000100_finish_status_reason.sql:3)：通用 status 有明确的结束后只读例外；这是不同函数，不能据此推断 Sophon。

## 3. score job 的 receipt 不是 CTF ground-station receipt

公开 [job_runner.py:352](/home/shu/kamico/observer/hackathon-survey26/project_platform/job_runner.py:352) 的 score job：下载已保存结果 → 验证 decisions 摘要 → 重放 actions → 返回 `{run_id, decisions_digest, score}`。**此阶段不运行 participant 代码**。SQL 所说的 score “receipt” 是该 job 的结果对象，用来写 verified/corrected/rejected/unverified；没有 Sophon flag 字段或 auto solve 写入。

相反，既有 `/desk/receipts` 返回 `checked[{run_id,checked_at,receipt}]` 与 `waiting`，CTF 文本和签发码出现在这个独立结果中。公开代码没有其 worker 实现。

以下直接来自 [desk_calls.jsonl](/home/shu/kamico/observer/work/sophon_desk/desk_calls.jsonl) 第 250 行及相应 run/result.zip：

| 运行 | 引擎分数 / termination | 地面站 checked_at（UTC） | 回执内真实码数量 |
|---|---|---|---:|
| 木星 `d76dd617` | −2882.489535 / agent_finished | 10-06 18:20:04 | 1 |
| 土星 `cab3db18` | −2883.591462 / agent_finished | 10-06 18:25:03 | 2 |
| 火星 `ece27a08` | −2882.489535 / agent_finished | 10-06 18:25:06 | 1 |
| 金星 `ca9ab66c` | −2882.489535 / agent_finished | 10-06 18:30:04 | 1 |
| 木星跑满 `4cb33db6` | −2882.489535 / survey_complete | 10-06 18:35:04 | 1 |
| envdiag `b96463f0` | −2883.591462 / survey_complete | 10-06 20:25:03 | 2 |
| REDRUM-M `dbe89770` | −15200 / survey_complete | 10-06 20:30:02 | 0，Nothing unusual |
| glyph `aa850d07` | −13088.140320 / survey_complete | 10-06 20:36:12 | 2 |

因此，“必须正分”“必须 survey_complete 才有回执”均被数据否定。不是把 practice code 当成真实码，也没有重复提交这些已见签发码。

另外，sophon2 `2dd4bcc3` 的地面站 `checked_at=2026-10-05T23:00:04.722861Z`；[diag_2dd4bcc3.json](/home/shu/kamico/observer/work/online/diag_2dd4bcc3.json) 的 score job `finished_at=23:00:44.173989Z`。回执早 **39.451128 秒**，直接否定“score 成功后才可能发回执”。当前本地 run.json 的 pending 快照不能代表 checked_at 那一刻的状态，故不依靠这个较弱推断。

公开 [rescore_and_sampling.sql:15](/home/shu/kamico/observer/hackathon-survey26/supabase/migrations/20261004110000_public_rescore_and_sampling.sql:15)、[:65](/home/shu/kamico/observer/hackathon-survey26/supabase/migrations/20261004110000_public_rescore_and_sampling.sql:65)、[:206](/home/shu/kamico/observer/hackathon-survey26/supabase/migrations/20261004110000_public_rescore_and_sampling.sql:206) 更解释了 pending 的另一来源：抽样开启时只复核每队每卡最佳与稳定 20% 其他运行；剩余保持 pending。该选择器没有 termination 过滤。不能再把“提前 finish 的几次没 score”作为平台普遍合同。

## 4. 首 decision 后 GET 与 POST 各认证组合

**GET 不是 POST 的公开前置条件。** [SophonBoards.vue:51](/home/shu/kamico/observer/hackathon-survey26/web/src/components/leaderboard/SophonBoards.vue:51) 承诺的网站动作是 POST desk/flag 与 GET desk/files；没有 GET desk 的运行身份合同，更未承诺 GET 返回 `board`。delayed 包要求先 GET 明确返回 board=auto 才 POST，是有意保守的策略，不能把未触发 POST 当成 auto 不支持的证据。

现有 `authtest_delayed` 与 `autoflagbody` 已将探测放到第一个 decision_request，时机选择合理。后者允许直接用同队已知真实码检查写入入口，因此能检验前者没有覆盖的分支。

| `/desk/flag` 组合 | 合理性与局限 |
|---|---|
| JSON `{flag, token: SOPHON_RUN_TOKEN}`，无 Authorization | token 真在当前 env 时最贴近旧 Johnny 合同；但 desk 是否沿用仍未证明 |
| JSON `{flag, token: OBSERVER_RUN_TOKEN}`，无 Authorization | 比 GET 更直接地测试新版写入端点是否沿用旧 body-token 约定；把 O 替代 S 是待证兼容性实验 |
| JSON `{flag}` + Bearer O | 通用 observer 的认证习惯，也是当前网页使用 Supabase client 的结构类比；私有 desk 不保证支持 |
| query `token=O` + JSON `{flag}`，无 Authorization | 旧 status 的位置类比，公开 desk 文档支撑较弱；只在限定矩阵中测一次 |
| JSON token O + Bearer O | 单一传输全部失败后的兼容性对照；两处同时改变，单独成功时无法确定是哪处被接受 |
| 以上再加 `x-sophon-site: 1` | 只证明网站来源标记会否影响分支；可能走 debug 或拒绝，不能以 HTTP 200 自封 auto |

不建议为了这次实验添加用户 JWT、anon key、其他账号/运行值，或拆分/重签 token。公开 Supabase config 没有 Sophon 函数部署条目，无法知道其 gateway verify_jwt 配置；通用函数的设置不能替代私有部署证据。

使用已知真实码比猜测 flag 更合适，但响应需要分层解读：

- `board=auto` 才明确表明该响应的身份域；`solved=true` 本身只证明某个解题记录成功，随后由主线已有榜单/desk 查询核实归榜。
- `wrong_answer` 可能来自内容/归榜/签发绑定检查，不能单独断言认证失败。反之，`closed` 仍没有公开语义。
- 同一签发串在第 250 行的 9 个不同 run 回执中重复出现，另一个在 2 个 run 重复；这否定“每个 receipt flag 必须逐运行唯一”，但不能证明 debug 码可直接记入 auto，也不能推出其签名算法。
- GET 的 `found`/`pending` 内容或成功状态不等于已产生 auto solve；公开 SQL 的写入方始终是私有 Sophon。

## 5. 剩余低风险、有界的验证

不建议再开一轮大矩阵。先等已准备的 delayed/body 包结果；本轮离线检查时 online 下尚未出现它们的新结果目录。

1. 保留首 decision 的同步屏障；不在线程里与初始化或 finish 竞争。最多使用既有 body/query/Bearer 三项，只有需要时才补 body+Bearer，任一 solved 或 429 就停止。
2. 若同一次 GET 缺省/带 O 均 closed，而 POST body 成功，说明 GET 门控不适合判断写入合同。无需继续猜 GET 路由。
3. 若有一个 POST 认证组合可达但回错答案，再从该身份域的已知只读 receipt 入口取得它实际签发的码，使用同一种认证提交一次；这个后续动作需要主线按当前端点授权实施，本报告不执行。
4. 若全部相同 closed，停止追加认证排列。若主线仍希望补一个只读样本，可仅对已知 `GET /desk/receipts` 用同一当前运行 Bearer 请求一次，检查回执读取是否与导航/提交分开授权；它仍属未公开合同，信息量低于已安排的 POST。更优先向主办方询问 current-run token 名、body/Bearer、允许阶段与 auto 归榜规则。
5. 日志保存固定 probe ID、decision_sequence、开始/结束 UTC 与单调耗时、HTTP 状态、有限枚举的 error/board、布尔 solved/no。不要输出 request URL、header、token、token 哈希、原始响应或动态键。现有探针允许输出任意字符串 error/board，可进一步收紧为固定枚举，以避免服务回显值进入日志；这里只提出建议，未改包。

计时边界补充：socket timeout 是单次阻塞超时，不等于严格的总耗时；若继续扩展探针，使用总截止时间并且无自动重试，避免慢速分块响应拖过决策预算。鉴权验证只在当前已授权主办方 Sophon 路径中进行，不扩展到 observer-session、模型端点或管理 API。
