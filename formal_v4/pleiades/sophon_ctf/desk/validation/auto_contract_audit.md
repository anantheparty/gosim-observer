# Sophon auto 合同审计（离线）

结论：**公开材料未定义新版 desk 的 auto 认证合同，也未解释 `closed`。目前不能断言 auto 不可达。** 新发现是现有鉴权探测在 `initialize` 处理期间启动，而公开引擎随后才把运行置为 `running`；应先排除这个时机竞态，再增加认证格式对照。

范围：本地公开仓库 HEAD `373d94f32598073b4eff31c15794fcd3474722ae`；最新扩展扫描覆盖全部本地 refs 可达的 **377 个提交、3129 个源码/文本 blob**（仍为浅克隆），替代初审记录的59个提交范围。另有既有 authtest 的非敏感源码与日志白名单字段。未联网、调用平台/模型/提交脚本、读取凭证文件或打印任何凭证值。本轮更新本报告，并新增只含源码对象、路径与命中行号的 `auto_history_scan_new.json`。

## 1. 当前实验究竟证明了什么

运行 `b9ea806e-3d93-4f3a-b2fa-7d36005937dd` 的 `authcheck_result`：

| 已测请求 | 实际认证 | HTTP / error / ok |
|---|---|---|
| `GET /functions/v1/sophon/status?token=…` | 本次 `OBSERVER_RUN_TOKEN`，query | `404 / closed / false` |
| `GET /functions/v1/sophon/desk` | 同一凭证，Bearer | `404 / closed / false` |

来源：[agent_log.json](/home/shu/kamico/observer/work/online/o4s_sophon4_authtest_fc6c/179e0a27-f9d8-4207-b36b-daa402e0c987/agent_log.json)。日志读取只输出了上述白名单字段；没有打印请求 URL、认证头或环境值。

两请求同时改变了路径和认证位置，没有无认证对照，也没有新版 SOPHON 专用凭证。因此只能证明这两个具体调用失败，不能区分：调用时机、token 类别、认证位置、私有服务的运行/阶段条件、路由前统一门控。`404` 本身不证明路由不存在；`closed` 的具体语义未公开。

**重要时机证据：**

1. [authtest/agent.py:17](/home/shu/kamico/observer/work/packages/o4s_sophon4_authtest/agent.py:17) 收到 `initialize` 后构造 Policy，随即 `authcheck.start()`；[authcheck.py:70](/home/shu/kamico/observer/work/packages/o4s_sophon4_authtest/authcheck.py:70) 起后台线程，没有等待首个决策请求。
2. [trusted_engine.py:127](/home/shu/kamico/observer/hackathon-survey26/project_platform/trusted_engine.py:127) 的 colocated 顺序是 `client.initialize` → `transport.publish_initial` → `participant.ready` → `client.begin`。[transport.py:151](/home/shu/kamico/observer/hackathon-survey26/project_platform/transport.py:151) 仅把 initialize 写入 stdin，不等待容器处理完成。
3. [20261004060000_fair_clock_session_deadline.sql:27](/home/shu/kamico/observer/hackathon-survey26/supabase/migrations/20261004060000_fair_clock_session_deadline.sql:27) 的 `observer_begin` 才执行 `status='running'`。第一个 `decision_request` 在 `publish_initial` 返回后发送，因此收到它是比收到 initialize 更可靠的开始屏障。

这证明存在竞态路径，**没有证明两次请求实际抢在 begin 之前，也没有证明 private Sophon 仅接受 running**。旧 Johnny 文档明确写 “only works inside a running evaluation”，所以值得先做此单变量排除。当前日志没有每次 HTTP 开始/结束时刻，无法回溯消除这个歧义。

## 2. 两种 token 的已知合同

| 项目 | `SOPHON_RUN_TOKEN` | `OBSERVER_RUN_TOKEN` |
|---|---|---|
| 公开用途 | Johnny 联系端点 | 通用 observer 运行身份 |
| 公开运输格式 | `POST /sophon/contact-johnny` 的 JSON 字段 `token` | `Authorization: Bearer`，用于 observer-session；模型代理另接受 x-api-key |
| 生命周期 | 文档只说运行中的评测内有效 | 本次运行的 participant capability；重排重启会轮换，通用服务校验活动状态、期限和 scope |
| 签发/注入实现 | 公开仓库和可见历史均未找到 | scheduler 创建 participant/engine 两个独立 capability，runner 向 participant 注入前者 |
| model_disabled | 无公开条件 | 仍然保留；只移除模型代理环境变量 |
| desk auto 接受它？ | 未公开 | 未公开；本次两种尝试均 closed，且时机尚有歧义 |

精确来源：

- [cli/AGENTS.md:177](/home/shu/kamico/observer/hackathon-survey26/cli/AGENTS.md:177)：唯一明确的 Johnny 请求合同；没有规定 public test、特定 phase、Bearer 或 desk。
- [observer-orchestrate.ts:111](/home/shu/kamico/observer/hackathon-survey26/supabase/functions/_shared/observer-orchestrate.ts:111)、[job_runner.py:214](/home/shu/kamico/observer/hackathon-survey26/project_platform/job_runner.py:214)：公开代码以 `obs_<run-id>.<participant capability>` 包装运行身份。此处是格式说明，不是实际值；不能用 engine 身份、别次运行值或人为拆掉前缀替代。
- [job_runner.py:55](/home/shu/kamico/observer/hackathon-survey26/project_platform/job_runner.py:55)、[docs/model-api-keys.md:123](/home/shu/kamico/observer/hackathon-survey26/docs/model-api-keys.md:123)：team egress/model_disabled 路径保留 OBSERVER 运行身份。
- [session.py:88](/home/shu/kamico/observer/hackathon-survey26/project_platform/session.py:88)、[observer-session.ts:72](/home/shu/kamico/observer/hackathon-survey26/supabase/functions/_shared/observer-session.ts:72)：session 使用并解析 Bearer。[observer-model.ts:43](/home/shu/kamico/observer/hackathon-survey26/supabase/functions/_shared/observer-model.ts:43) 的 x-api-key 支持属于模型 API，不是 Sophon 合同。
- [20260925000100_project_platform.sql:300](/home/shu/kamico/observer/hackathon-survey26/supabase/migrations/20260925000100_project_platform.sql:300)、[20260927000700_poll_without_lock.sql:6](/home/shu/kamico/observer/hackathon-survey26/supabase/migrations/20260927000700_poll_without_lock.sql:6)：通用能力校验接受 starting/ready/running，检查 token 哈希、scope、expires/deadline；不能据此推定私有 Sophon 的条件相同。
- [20261005110000_requeued_run_reopens_session.sql:7](/home/shu/kamico/observer/hackathon-survey26/supabase/migrations/20261005110000_requeued_run_reopens_session.sql:7)：重排后旧 attempt 的 capability 失效。
- [docker_runtime.py:138](/home/shu/kamico/observer/hackathon-survey26/project_platform/docker_runtime.py:138)：runtime 白名单没有 SOPHON 项，但另合并 manifest/team 环境。因此仅凭这份 runner 不能排除部署时其他注入路径。已完成 envdiag 才提供了该次容器无 SOPHON_*、有 OBSERVER_RUN_TOKEN 的运行证据。

**不是 public test 专用的公开证据：** scheduler 的 participant 身份分支依据 project/colocated，而非 Sophon/public-test；preview 在运行身份创建路径上改变时间预算。没有发现“只有 public test 能拿 Sophon token”或“特定阶段自动换成另一 token 名”的实现。另需更正早期成功请求的归因：已核实的10月5日17:10阳性来自 Sophon evaluation run `1e87fc81-de27-40a4-8f4a-792f8f046d7e`，不是有证据确认的 public test；其卡属性 `practice` 不能用作工作流阶段。详见 [publictest_token_audit.md](/home/shu/kamico/observer/work/sophon_desk/validation/publictest_token_audit.md)。专用 public-test 卡与 Sophon 卡的进一步差异见第5节。

## 3. `closed`、榜单与可见性

| 公开证据 | 能推出 | 不能推出 |
|---|---|---|
| 当前及可见 git 历史没有 Sophon handler；`supabase/functions` 无该服务文件 | 其鉴权、错误与归榜逻辑没有随公开仓库发布 | `closed` 是哪条 if 分支 |
| 通用代码使用 `invalid_run_credential`、`invalid_or_expired_capability`、`session_deadline`；评测入口用 `phase_closed` | 私有返回 `closed` 不等于这些公开错误名 | `closed` 一定是 token 错或阶段结束 |
| [SophonBoards.vue:51](/home/shu/kamico/observer/hackathon-survey26/web/src/components/leaderboard/SophonBoards.vue:51) 网页 flag/files 加 `x-sophon-site: 1`，调用常规 Supabase client | 网站存在来源标记 | 此标记一定决定 debug/auto；删除它就成为 auto |
| [boards SQL:1](/home/shu/kamico/observer/hackathon-survey26/supabase/migrations/20261006000000_sophon_boards.sql:1) 指明私有 sophon 写入，公开函数只读取；run_id/user_id 均可空 | 两榜是独立的服务端数据，auto 总分乘 2 | 通过 run_id 非空、请求头或某种 token 即可归 auto |
| [extra phase SQL:21](/home/shu/kamico/observer/hackathon-survey26/supabase/migrations/20261005120000_extra_phase_entry.sql:21) 与 boards SQL:19 | 榜单可见性依赖 extra_phase_id、时间/active/projects_enabled、team access、hidden/admin | 某次空榜表示无人解出；可见性条件就是 desk 鉴权条件 |

有关历史：`17d68bb`（2026-10-05 15:38 UTC）新增旧 Johnny 文档；`cd0ce1d`（10-05 21:14 UTC）新增 debug/auto 表和 desk UI；`920f339`（10-06 06:26 UTC）只从 rules/FAQ 删除 Johnny 邮箱，未删除 API 文档。没有旧 key → 新 flag 或旧 token → 新 token 的公开迁移。浅克隆范围外与实际部署代码无法离线确认。

## 4. 一份有界运行内鉴权矩阵（建议，未执行）

优先顺序是**先复测时机，再补格式**。在下一次已安排的 Sophon 真卡运行里，收到第一个 `decision_request` 后、输出第一条决策前，串行、有超时地执行；不要在 initialize 里启动竞态线程，也不要等数据库终态或容器退出后请求。agent 的 `finish` 消息与数据库 finish RPC 是两个时点，见第5节；首条决策仍是更清晰的鉴权对照位置。只用该进程自己的当前 env，不导出到宿主机。

固定目的地为主办方 `https://vdiemcofukuxglqsmlyz.supabase.co/functions/v1/sophon/` 下列已知路径，禁止重定向；`O` 表示本次 OBSERVER_RUN_TOKEN，`S` 表示本次实际存在的 SOPHON_RUN_TOKEN。以下不是把任何候选认证方式认定为合同。

| 顺序 | 方法 / 相对路径 | 认证及额外头 | 目的 |
|---|---|---|---|
| 1 | GET `desk` | Bearer O；无 site 头 | 原失败请求在确定 begin 后的单变量复测 |
| 2 | GET `status?token=O` | 无 Bearer | 另一原请求的同样复测；仍是把 O 放入旧路线的实验 |
| 3 | GET `desk` | 无认证 | 与 1 对比，确定是否连缺省请求也得到同一 closed |
| 4 | GET `status` | 无认证、无 token query | 与 2 的负对照；可揭示校验顺序差异 |
| 5 | GET `desk?token=O` | 无 Bearer | 只更换 desk 的凭证位置；借用旧 status 约定，**未被文档承诺** |
| 6 | GET `desk` | Bearer O + `x-sophon-site: 1` | 只改变已知网页标记；即使成功也要看显式 board，不能自行称 auto |
| 条件 7 | POST `contact-johnny` | JSON `{token: S}`；S 缺失时可由主线选择 `{token: O}`，无 Bearer | S 存在时是唯一逐字文档合同；O 替代仅为兼容性实验。此调用可能联系 Johnny，不是只读 GET，主线决定是否启用；不发空 token、不追加 answer/flag/door 操作 |

实际最多 6 个只读请求，条件 POST 最多 1 次；每个超时 3 秒、总上限约 21 秒、无重试/循环，遇到 429 立即停止。若 1 或 2 已明确返回有效 auto 身份，停止剩余猜测并保留结果。若收到 HTTP 200 但没有 board/运行身份语义，只记“可达”，不要算 auto 成功。public preview 不自动重复整套；其环境名称、卡 ID 与真卡分开记录即可，避免把两个模式混为一轮。

日志只记固定 probe ID、decision_sequence、单调时差、UTC 时刻、凭证变量名/存在布尔值、HTTP 状态、白名单 `ok/error/board` 和有限 schema 类型；不记 token、token 哈希、完整 URL/query、Authorization、原始响应或异常字符串。只记录白名单错误文本，未知字符串只记类型/长度，防止服务端回显凭证。

解释边界：

- 已开始时复测成功而旧 initialize 探测失败：强烈支持时机问题；相同 run 的时刻证据优于不同日部署对比。
- 无认证与多种携带 O 的请求都相同 closed：支持“共享拒绝/门控”假设，但仍不能判断门控位于认证之前还是之后，更不能概括为 auto 永久关闭。
- 某一格式返回不同的认证错误：只说明请求走到不同分支，不等于认证成功。
- 所有有界探测仍失败：保留矩阵结果，向主办方询问新版 auto 的准确凭证名称、body/Bearer 合同、允许 run 状态与 phase。停止枚举未知端点或加工 token。

## 5. 扩展离线审计新增证据

本节只补初审未建立的证据。没有开展新的平台实验，也没有因公开代码的通用 observer 契约而宣称 Sophon auto 认证已确定。

### 5.1 容器收尾、结果上传与身份失效不是同一时刻

正常 colocated v4 的公开顺序为：

`最后决策/工作流结束 → agent finish 消息 → 最多30秒收尾并关闭容器 → 打包上传结果 → engine调用数据库finish → run变为scored`

| 精确来源 | 新增事实与影响 |
|---|---|
| [trusted_engine.py:229](/home/shu/kamico/observer/hackathon-survey26/project_platform/trusted_engine.py:229)、[:145](/home/shu/kamico/observer/hackathon-survey26/project_platform/trusted_engine.py:145) | `run_v4_session` 先调用 provider.finish；这个方法只调用 transport.finish，没有向数据库发结束RPC。 |
| [transport.py:24](/home/shu/kamico/observer/hackathon-survey26/project_platform/transport.py:24)、[:156](/home/shu/kamico/observer/hackathon-survey26/project_platform/transport.py:156) | 默认收尾上限30秒，发送finish后关闭stdin，等待进程退出，随后关闭进程；stderr继续进日志，stdout不再作为决策处理。不是可以任意延长运行的窗口。 |
| [job_runner.py:288](/home/shu/kamico/observer/hackathon-survey26/project_platform/job_runner.py:288)、[:304](/home/shu/kamico/observer/hackathon-survey26/project_platform/job_runner.py:304)、[:342](/home/shu/kamico/observer/hackathon-survey26/project_platform/job_runner.py:342) | 容器/egress先关闭，之后才发布结果；结果上传成功后，engine才调用session的finish。因此 agent收到finish时，正常成功链路通常尚未把DB run设为终态。取消、超时、其他失败路径仍可更早结束运行。 |
| [20261001000600_evaluation_hardening.sql:94](/home/shu/kamico/observer/hackathon-survey26/supabase/migrations/20261001000600_evaluation_hardening.sql:94)、[:99](/home/shu/kamico/observer/hackathon-survey26/supabase/migrations/20261001000600_evaluation_hardening.sql:99) | engine finish要求run仍为running，然后项目运行变成scored；该方法的重复finish容错不等于participant仍可调用通用API。 |
| [20260925000100_project_platform.sql:304](/home/shu/kamico/observer/hackathon-survey26/supabase/migrations/20260925000100_project_platform.sql:304)、[20260927000700_poll_without_lock.sql:10](/home/shu/kamico/observer/hackathon-survey26/supabase/migrations/20260927000700_poll_without_lock.sql:10) | 通用participant检查同时要求活动状态、未过期及相应deadline。因此即使存储的expires_at较远，run进入scored也使通用运行能力失效；不能把expires_at理解成离线继续使用的许可。 |

由此可作两项有限推断：

- agent `finish` 回调并不天然等于“运行凭证已经因DB终态失效”；但私有 Sophon 是否接受收尾期请求仍未公开，不能据此保证auto成功。
- **收尾期不能依赖本次上传结果生成的地面站receipt**：本次结果此时尚未上传。公开runner既不调用Sophon，也不写其成绩表。若私有服务另有实时机制，本地源码没有给出；不能假定在本次finish里即可取到这次运行的最终receipt。

生命周期还可精确到两个独立时限：[20261004060000_fair_clock_session_deadline.sql:16](/home/shu/kamico/observer/hackathon-survey26/supabase/migrations/20261004060000_fair_clock_session_deadline.sql:16) 先对preview取 `min(runtime,300)`；colocated随后将session deadline设为约 `3×该预算+120秒`，expires至少再延长1800秒（同文件L21–26）。这是外层安全期限，**不会延长容器30秒收尾期，也不覆盖终态撤销**。假设formal配置900秒，外层deadline约为begin后2820秒；preview配置300秒则约1020秒。此前因初始化竞态失败的假设仍应以首条决策后的实测区分。

### 5.2 Public test 是不同卡与不同run，不只是缩短时限

| 精确来源 | 新增事实 |
|---|---|
| [scripts/build-v4-public-test-card.py:31](/home/shu/kamico/observer/hackathon-survey26/scripts/build-v4-public-test-card.py:31) | 官方构建规格是 `card_id=PT`、`phase=public-test`、scenario=`v4-public-test`，7夜、2000目标、300秒；它不是Sophon卡的另一个运行开关。 |
| [v4_bundle.py:78](/home/shu/kamico/observer/hackathon-survey26/challenge/v4_bundle.py:78)、[:105](/home/shu/kamico/observer/hackathon-survey26/challenge/v4_bundle.py:105) | public-test builder调用的 `build_card_bundle` 不传sophon调度；Sophon的显式opt-in在另一条 `build_spec_bundle` 路径读取 `card.json.sophon`。因此公开PT卡不包含Sophon调度，但不能据此推定私有HTTP鉴权是否允许preview身份。 |
| [20261003000100_platform_failure_resilience.sql:343](/home/shu/kamico/observer/hackathon-survey26/supabase/migrations/20261003000100_platform_failure_resilience.sql:343) | preparation完成后会新建 `mode=project,purpose=preview` 的batch，再创建独立run并存入 `preview_run_id`；public-test run与后来formal evaluation run是不同身份。 |
| [scripts/configure-v4-phases.py:284](/home/shu/kamico/observer/hackathon-survey26/scripts/configure-v4-phases.py:284)、[:297](/home/shu/kamico/observer/hackathon-survey26/scripts/configure-v4-phases.py:297) | 配置器要求专用公开测试卡，不能复用practice/formal/final卡；v4 preview所处phase也必须colocated。不能拿卡片`phase=practice`来判定preparation/public test。 |

这一差异支持分开记录preview与Sophon evaluation结果；不支持“公开测试成功/失败便证明真卡auto同样成功/失败”。已验证的早期token阳性归因也已在第2节更正。

### 5.3 Auto 写入契约的新增结构约束

[20261006000000_sophon_boards.sql:4](/home/shu/kamico/observer/hackathon-survey26/supabase/migrations/20261006000000_sophon_boards.sql:4) 的成功记录主键为 `(board,team_id,no)`，不包含run_id；`run_id`只是可空字段。该公开DDL没有规定auto必须非空run_id，也没有用外键/检查约束强制某个运行状态。完赛记录主键为 `(board,team_id)`（同文件L11–14）。

因此：**表结构不能证明auto要求单次900秒运行包办全部题，也不能证明跨run累积被允许。** 这两种限制若存在，都要由私有writer施加。首次/后续覆盖策略、何时写run_id、自动归榜依据，仍没有公开实现；不要把携带一个run_id误当作提交认证合同。

### 5.4 全部本地历史扫描结论

机器索引：[auto_history_scan_new.json](/home/shu/kamico/observer/work/sophon_desk/validation/auto_history_scan_new.json)。扫描377个可达提交的3129个唯一源码/文本blob（包括归档runner、bundle、Rust/脚本/文档），仅记录对象ID、路径、匹配名与行号，不保存任何运行凭证或请求头值。

- `SOPHON_RUN_TOKEN` 在全部可见历史中仍只见于 `cli/AGENTS.md` 和生成的 `web/src/content/cli.en.md`、`cli.zh.md` 文档；没有签发/注入实现。
- `sophon_g_solves`、`sophon_g_finishers` 的历史内容只出现在榜单迁移SQL，没有INSERT/UPDATE writer或自动提交RPC。
- Sophon相关可执行源码仍限于可选天象调度、bundle、runner与展示UI；没有 `/functions/v1/sophon` handler，也没有可验证的新auto凭证名称、认证body/头或`closed`分支。
- 这比初审59提交的范围更完整，但仓库仍为shallow；未声称覆盖未取得的远端历史或私有部署。没有为本审计fetch任何对象。

本轮没有找到可将候选认证升级为已确认合同的新证据，未新增鉴权排列或平台实验建议。
