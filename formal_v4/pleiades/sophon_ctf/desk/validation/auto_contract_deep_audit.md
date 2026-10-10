# Sophon auto 合同：公开历史与运行证据深审

2026-10-07；仅离线读取已有仓库与产物，没有联网、上传、运行仿真、读取凭证或输出 token。本文接受用户确认的前提：22 个 flag 都存在，auto 榜可以完成。

**结论：公开源码能确定谁负责写榜、通用运行身份从何而来，以及公开的 Johnny 请求合同；不能确定私有 Sophon 的 auto 判定或 S token 签发条件。最新正式评测和对应预检都在首个 decision 缺少 S，均没有发出任何认证探测。它们证明当前两个运行未获得文档描述的能力，不能证明 auto 不存在，也不能算 contact/answer/status 失败。**

## 1. 覆盖范围与最新文档

仓库：`/home/shu/kamico/observer/hackathon-survey26`。

| 项目 | 本轮核对 |
|---|---|
| 工作树 HEAD | `373d94f32598073b4eff31c15794fcd3474722ae` |
| 本地 origin/main | `f8f6b3a0357af32d5dca7e1bcb23e0aa01b6cb9b` |
| 可见历史 | `git rev-list --all` 共 402 个提交；仓库仍为 shallow，不能称已取得远端全部原始历史 |
| 本轮内容搜索 | 所有可达对象中 3,204 个常见源码/文档文本 blob，共 74,283,985 字节；搜索输出仅路径，不输出能力值 |
| S 名称 | `SOPHON_RUN_TOKEN` 只见于技能/CLI/网页文档及文档测试，没有公开签发实现 |
| 写榜表 | `sophon_g_solves`、`sophon_g_finishers` 只见于建表和只读 RPC 的 SQL |
| 端点实现 | `sophon/desk` 只见网页调用；`sophon/answer`、`sophon/status` 无公开实现；没有发现曾公开后删除的 Sophon handler |
| `closed` | Sophon 相关源码的命中仅有普通排行榜阶段状态，不能解释私有端点的同名错误 |

相关历史顺序：`17d68bb` 引入 Johnny body-token 文档；`fbb70a7` 加旧单题名单；`cd0ce1d` 加 debug/auto 多旗表与网页提交框；`16961b7` 再次明确 S 环境变量。

`16961b7e8c2d14775f995a80e2fbec7dbabe4b41` 的时间是 **2026-10-07 13:00:50 UTC**，提交说明称文案经过 owner 批准。该提交只改文档/帮助/测试，没有 runner 或服务器鉴权改动。精确引用采用 `commit:path:line`，因为工作树尚未切到它：

- `16961b7:cli/AGENTS.md:177,361`：运行内 `POST /functions/v1/sophon/contact-johnny`，JSON `{"token":"$SOPHON_RUN_TOKEN"}`。
- `16961b7:cli/AGENTS.md:181,365`：评测运行时环境中会有 `SOPHON_RUN_TOKEN`；解读异常夜晚后告诉夜班看守。

这支持优先查明 S 缺失，而不是继续把 O 当 S 排列认证形式；它没有承诺 Johnny 成功就会写 auto，也未公开 `/desk/flag` 的运行鉴权格式。

## 2. 写榜、run_id 与 user_id：可证边界

以下路径均相对于上面的仓库根目录；行号以当前工作树为准。

| 问题 | 直接证据 | 可以确认 / 不能确认 |
|---|---|---|
| 谁写 auto 行？ | `supabase/migrations/20261006000000_sophon_boards.sql:1–2` 明示由 organizer-run private `sophon` function 写入 | 唯一公开指定的写入方是私有 Sophon；公开 RPC 不写榜。没有公开写入谓词 |
| 记录格式 | 同文件 `:4–8`：`board,team_id,no,at,run_id,user_id`；主键 `(board,team_id,no)` | auto/debug 按队和题去重。`run_id`、`user_id` 都允许 NULL，schema 没有强制 auto 必须带 run_id |
| run_id 来源 | 新表没有赋值函数；`observer-orchestrate.ts:123,138,150–151` 给通用 capability 绑定 scheduler 的 `run.id` | O 内的 run_id 有公开来源；不能证明 Sophon 就从 O 提取该字段。私有 handler 或后台 worker 都可能获得 run_id |
| 旧答案通道 | `20261005130000_sophon_solvers.sql:5–10`：旧表 team_id 主键、run_id 必填、user_id 可空、key 必填 | 旧解题与运行关联明确；无公开触发器/迁移把旧表写入新 auto 表。key 的格式与含义未公开 |
| 网页提交 | `web/src/components/leaderboard/SophonBoards.vue:47–54`：POST `sophon/desk/flag`，body `{flag}`，header `x-sophon-site:1` | 客户端不提交 board/run_id。只有服务端能决定归榜；这个 header 是否强制 debug 未公开 |
| 榜单读取 | SQL `:34–46,52–63` 与 Vue `:24–27` | auto 按 2 倍计总分；RPC 不返回 run_id/user_id，因此无法靠榜单恢复其写入来源 |
| 空榜含义 | SQL `:19–22,38–39` 可见性过滤；Vue `:25–28` 也把 RPC error 展示为空数组 | 空榜本身不等于无人解出。应区分原始 RPC 成功空数组与前端吞掉错误 |

公开表格列名 `F1/F2/...` 是按各 board 首解时间重新 `dense_rank` 得到的显示标签（SQL `:41`），不能把 F4 当作原题 No.4。此次用户确认的 22 题存在性不依赖 SQL 中是否有题目目录。

## 3. S 与 O、注入与生命周期

| 项目 | OBSERVER_RUN_TOKEN（O） | SOPHON_RUN_TOKEN（S） |
|---|---|---|
| 公开产生位置 | `supabase/functions/_shared/observer-orchestrate.ts:109,124,138,151`：独立 engine/participant capability；各自绑定 run.id | 无公开签发实现、格式、轮换或撤销说明 |
| 容器注入 | `project_platform/job_runner.py:214–221` 固定从 participant.run_credential 设置 O 与 OBSERVER_RUN_ID | 文档明确说运行时有 S；固定 runtime 环境没有这项 |
| 公布的用途 | `project_platform/session.py:88–91` 使用 Bearer O 调 observer-session；model handler 接受同类 capability | Johnny 文档仅承诺 JSON body `token:S`，仅运行内有效 |
| model_disabled | `job_runner.py:55–69` 保留 O，仅移除模型代理变量 | 没有公开 S 分支；历史上同为 model_disabled 的运行既有 S 也无 S，不能归因于该开关 |
| 通用过期 | capability 范围/哈希/时效检查；重排时轮换；observer 的结束后 status 有只读例外 | 无公开实现，不能把 observer status 例外推广到 Sophon status |

**固定名单缺少 S 不等于技术上不可能注入。** `docker_runtime.py:139–160` 会合并 manifest、team 与平台 run 环境；`team_egress.py:64,101–104` 禁止 OBSERVER_/SAC_ 前缀，却允许 SOPHON_RUN_TOKEN 这个名字。`observer-orchestrate.ts:24–51` 与 `20261005071000_no_model_evaluations.sql:104–118` 可携带已有队伍变量，但没有生成新 S 的代码。这只是通用运输路径；不能自行把 O 复制成 S 或在 manifest 里伪造能力。

初始化时机确有边界：`trusted_engine.py:127–132` 是发送 initialize → ready → begin；`20261004060000_fair_clock_session_deadline.sql:27` 在 begin 将 run 改为 running。**首个 decision_request 是合适的已开始屏障**。收尾则相反：`trusted_engine.py:227–230` 先通知 agent finish；`job_runner.py:332–343` 后上传并写数据库 finish，所以 agent 的 finish 回调不等于认证已过期。

预检与正式评测共用调度/runner，但创建不同 run。`scripts/configure-v4-phases.py:283–301` 的 public test 使用独立小卡并限制 300 秒；`20261003000100_platform_failure_resilience.sql:343–346` 创建 preview batch/run；`20261006040000_two_stage_evaluations.sql:166–183` 区分 preview 的 runtime/批准条件。公开代码未给出 S 的 preview/phase 条件。卡内 `task_card.phase=practice` 也不是平台的 preview 标记。

## 4. 运行证据：哪些假设已被缩小

| 样本 | 安全读取结果 | 解释 |
|---|---|---|
| 早期 Sophon1 | S 存在，Johnny 9 次 200 | S 合同至少曾实际运行；重复调用成功不支持简单“一次调用即烧毁” |
| envdiag `b96463f0` | 环境名字含 O，无 SOPHON 名称；initialize/payload 顶层键无 auth/sophon 字段 | 该样本不只是旧探针遗漏了新变量名。并未检查任意嵌套动态数据 |
| delayed `bad776d9` | 首 decision；O 有、S 无；六种既有 GET 组合均 closed | 排除该组请求的 initialize 竞态；不定义 closed 的私有语义 |
| flagbody `60eb961f` | 首 decision；真实已知码配 O 的 body/query/Bearer/site 组合均 closed | 已覆盖直接 POST；无需再以 GET 不返回 board 为理由重复该矩阵 |
| oldanswer `9d5bdb27` | O 的三种旧 answer 组合均 401 | O 不能在已试组合下替代 S；无效于判断真实 S 请求结果 |
| **新正式 run `e829a69b`** | **2026-10-07 18:52:39–18:52:49 UTC；decision_sequence=1，observer_present=true，sophon_present=false，probes=[]** | **在 16961b7 文档之后仍无 S。零请求，不能记为 contact/answer/status 被拒绝** |
| **对应 public-test `8cf96709`** | **主线核对完整 agent_log：同样 decision_sequence=1、O=true、S=false、probes=[]，无 skipped** | **排除本次版本“只在预检注入 S”的解释；该条是主线提供的只读核对，本报告未重复获取** |

最新正式产物：`work/online/o4s_sophon4_contact_answer_9328/179e0a27-f9d8-4207-b36b-daa402e0c987/{agent_log.json,run.json}`。run.json 为 scored、score_check=pending；这些字段不补足缺少的 S，也不表示自动解题请求曾发出。

地面站、score job 和 auto 写榜应分开：公开 score runner 只是重放动作并提交分数；私有地面站回执已在负分、agent_finished 的运行出现，且 Sophon2 的 checked_at 早于 score 完成约 39.45 秒（详见 `auto_contract_followup.md`）。所以正分、survey_complete、score verified 不是一般性回执必要条件。已有回执也没有证明“发现 flag 自动写 auto”；还可能需要运行内提交或其他私有条件。

此前扫描既有 agent_log 没有实际 `SOPHON{...}` 字面串。因此“从 agent 输出自动收旗”既无公开实现证据，也还没有被这些运行直接测试；不能拿空榜把它排除。

## 5. 最小可区分验证

**当前最有信息量的是明确能力签发合同，不是重复 O 排列。** 可向主办方附两条新的 run ID、首 decision 的布尔结果及新版文档，询问：当前 Sophon 阶段是否仍自动注入 S；若有前置资格/配置，其公开条件是什么；运行内 auto 的 token 位置与写榜端点是什么。无需交出 token 或队伍凭证。

| 后续实验（本轮未执行） | 最小顺序与证据 | 可证伪范围 |
|---|---|---|
| 得到当前有效 S 后验证旧合同 | 首 decision → POST contact-johnny `{token:S}` → 成功后 POST 已知旧 answer → GET 旧 status；严格限时，429/鉴权失败即停 | 能区分 S 通道可用与当前注入缺失。旧名单变化但 auto 不变，仅说明没有观察到桥接 |
| 验证 runtime HTTP 写榜 | 当前运行内，用已确认的 S 认证位置向 `/desk/flag` 交一个已知真实码一次；外部检查 auto 行 | 明确 board=auto/对应新行才证明该写入途径。GET `/desk` 不是公开的 POST 前置条件，无需为增加它单独重传 |
| 无 HTTP 的日志单变量 | 如仍没有有效 S 且主线愿意花一次受控运行，只增加一次真实已知码的 agent 输出，其余观测保持基线；等地面站处理后比榜 | 阳性支持产物处理路径；阴性只否定所试日志形式/前提，不否定所有自动解法。公开证据很弱，优先级低于签发合同澄清 |

运行探针应只记录固定 probe ID、decision 序号、UTC/耗时、HTTP 状态、白名单错误、board、solved/no；不记录 URL/query、headers、token、token 哈希或原始响应。继续沿用真实 S-only 包的“缺 S 零请求”策略；此次最新运行已完成这一分支，没有必要修改包后再试同一空条件。

最终边界：**auto 可完成是已知前提；当前缺的是公开实现未提供的能力签发/识别与写榜条件。公开历史没有足够证据把运行内 HTTP、地面站、日志扫描、旧 answer 桥接中的任意一个断言为唯一正确通路。**
