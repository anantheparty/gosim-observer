# SOPHON_RUN_TOKEN 注入差异：单变量审计

仅离线；未读取凭证文件、提取或输出 token 值、调用平台或修改包。公开源码工作树为 `373d94f32598073b4eff31c15794fcd3474722ae`，涉及文件无本地改动。

**尚未找到可独立解释注入差异的已证单一变量。** 本轮排除了几项常见混淆：两次早期运行不是 public test 差别、不是提前结束差别，也没有普通出网切换到 TeamEgress 的证据。实际可见配置差异是硬时间上限；但其代码与 token 注入无关。`model_disabled` 和早期 revision 创建时间没有保存在现有产物，必须标未知。

## 1. 最接近的阳性/阴性对照

所有 Sophon 卡场景 ID 为 `179e0a27-f9d8-4207-b36b-daa402e0c987`。

| 维度 | Sophon1：有专用变量 | Sophon2：无专用变量 | 判断 |
|---|---|---|---|
| run | `1e87fc81-de27-40a4-8f4a-792f8f046d7e` | `2dd4bcc3-78ae-4162-b1c9-ce12b452596b` | 不同运行 |
| batch | `2a97f632-a405-4b19-be97-f703474238a0` | `f5995cb0-cc61-453c-bedf-aef75f0d4411` | 不同批次；本地 run.json 没有 batch.mode/model_disabled |
| run 创建时间 UTC | 10-05 17:09:29.236870 | 10-05 22:57:45.312153 | **不是 revision 创建时间** |
| 开始时间 UTC | 17:10:42.551163 | 22:58:42.884734 | 相隔约 5 小时 48 分 |
| 结束时间 UTC | 17:11:31.100096 | 22:59:17.515727 | 两次均正常结束 |
| 初始化存在性 | agent_log 解码 L9 `env_sophon` 含 `SOPHON_RUN_TOKEN` | 同位置为空列表 | 差异在 initialize 已存在；不是后续请求过期造成“值无效” |
| Johnny | 9 次 HTTP 200 | 缺变量后直接跳过 | 首次不是用一次即消耗的 token |
| scenario / 卡内 phase | Sophon practice prototype / practice | 完全相同 | 不能把 practice 解释为 public test |
| termination / run.status | survey_complete / scored | survey_complete / scored | 排除“sophon2 提前 finish 所以拿不到注入” |
| 协议 / budget / clock | participant-agent-protocol-v4 / 900 / cpu | 相同 | 共同的 v4 成功路径需要 colocated；不等于已读到 batch.mode 数据库字段 |
| 归档路径标签 | runner-10 | runner-10 | 标签相同，不代表二进制、私有部署或配置相同 |
| 初始化卡内容 | task_card/site/instrument/scoring/survey 等 | 与 Sophon1 逐对象相等 | 公布给智能体的卡没有可见开关差异 |
| 初始化 limits | 速度因子 0.7518 | 速度因子 0.795 | 其余字段一致；正常 CPU 校准差异 |
| workflow hard cap | **1800 秒** | **3600 秒** | **确实不同的组织方运行配置**；均未触顶 |
| egress.json | 存在，1 个目的地记录 | 存在，空列表 | 公开 engine 只在 TeamEgress 分支写该文件；不支持普通模式→TeamEgress 切换解释 |
| engine / score diagnostics | 未保存对应 diag 文件 | 两 job 都 succeeded，log 均为空 | 阴性不是启动失败；诊断没有补出注入参数 |
| 实际 revision ID / 创建时间 | 本地缺失 | 本地缺失 | 不能拿包名、文件 mtime 或 run.created_at 代替 |

证据文件：`work/online/sophon1_2a97/<scenario>/run.json`、`agent_log.json`、`result.zip`；`sophon2_f599` 同结构；另有 `work/online/diag_2dd4bcc3.json`。ZIP 中的 `workflow_result.json` 保存时钟和 termination，`egress.json` 保存出网结构。本轮未读取或打印出网请求内容。

## 2. Manifest / revision / public-test 的边界

本地 `work/pkgs/sophon1/observer.project.json`、sophon2、sophon3 的 image/build/run/working_directory/protocol 与 environment 完全一致：Python 3.12 slim、numpy 2.2.6、`python3 -u agent.py`、jsonl-v4；环境只有 `PYTHONDONTWRITEBYTECODE/PYTHONPATH/OPENBLAS_NUM_THREADS/OMP_NUM_THREADS`。不存在通过本地 manifest 直接配置专用 token 的差别。sophon1 probe 第 40 行与 sophon2 第 55 行均从同一个环境变量读取；阴性日志明确是变量名不存在，不是名字拼错或把认证失败误记成缺失。

但是 result.zip 没有原始提交源码，旧 run.json 没有 revision 字段。以上仅核实**现存本地包**，不伪称已把它们与两个历史 revision 的 source_digest 连起来。

后续有较好的绑定：`submit_sophon3.log` L1–5、40–42 给 revision `2257d459-fcdd-461f-b7d1-03471ea85b1f`、一次 passed public-test 和 batch `2d79ab4b-3b0c-40cc-b2fb-42e92db5e636`。但日志没有 revision 创建时间。`sophon_eval.log` L6–10 将 envdiag 的 revision `f8f8def5-1783-4e81-959d-8efcb8d5fa7e` 与 batch `15dd5055-1fda-4815-ab99-0621fbf45c15` 相连，也不含数据库创建时间。

已保存的独立 public-test ZIP 的 scenario 明确是 `v4-public-test`，变量不存在；没有 Sophon1 阳性的 public-test 产物。公开 `scripts/build-v4-public-test-card.py` 构建独立 PT 卡，不能靠改卡内 phase 或选择预检恢复真卡能力。

## 3. 环境变量筛选：哪些解释成立，哪些不成立

| 公开路径 | 精确机制 | 对 S 缺失的解释力 |
|---|---|---|
| `project_platform/job_runner.py:214` | participant 基础运行环境只构造 O 身份和模型代理项，未构造 S | 公开注入起点本来就没有 S，阳性存在说明还需部署/输入侧证据。 |
| `job_runner.py:55`、`:89` | TeamEgress 运行环境只保留 O 相关四项，再合并 egress 设置 | 假如私有代码把 S 仅塞入该中间 dict，确实会被此处过滤；但两次都有 TeamEgress 文件，不能据此解释只有第一次保留。 |
| `docker_runtime.py:18`、`:142` | run_environment 不在固定白名单的键会在第 143 行**抛异常** | 不是“未知 S 被 Docker 安静删除”。两次成功启动排除了这一简单叙述。 |
| `docker_runtime.py:154`、`:160` | manifest.environment、team.environment、run_environment 分开合并 | team.environment 不受同一个 runtime 白名单限制。 |
| `team_egress.py:63`、`:101` | 普通变量名规则允许 S，保留的是 OBSERVER_/SAC_ 等前缀 | S 走队伍变量通道在公开代码中是可能的；不能因此断言它当时真的在团队表里。 |
| `job_runner.py:64` | no_model 只移除模型代理四项，增加 OBSERVER_MODEL_DISABLED | 不会按名字直接删除 S。 |
| `20261005071000_no_model_evaluations.sql:103` | 数据库剔除 disabled=true，以及 no_model 时 model=true 的队伍变量 | 这是可解释差异的**条件候选**：若 S 通过该通道且被标 model/disabled，单个标记足以改变输出。实际标记未知。 |
| 同 SQL `:28–31` | 自动 model 分类只匹配 OPENAI_/ANTHROPIC_、指定后缀及 LLM_ | **SOPHON_RUN_TOKEN 不匹配**。不能无条件说切 no_model 就会删掉 S；需要人工标记或私有注入规则这一额外条件。 |

因此，“environment allowlist 删掉了 token”必须指明哪层、哪条输入路径；当前记录不够。若部署与公开代码一致、且真实 revision 的 manifest 也与本地相同，那么 team.environment 是一个值得核查的合法注入通道。这是带前提的排查方向，不是签发器已经定位。

最近 envdiag 的环境名字明确含 `OBSERVER_MODEL_DISABLED` 与 O，不含任何 SOPHON_*；早期两包仅记录 SOPHON 名字，**无法从缺少完整环境清单判断当时 no_model 是开还是关**。初始负例和后续负例相同，不足以把近期设置倒推回 10-05。

另查了自动删除规则：`20261004040000_team_variables_and_egress.sql:198` 按队伍密钥保留策略删除 secret 队伍变量；默认保留 **7 天**，并在尚未公布的 sealed 阶段继续保留（`20260926000600...:44`；`20260927001200...:19`）。公开默认规则不支持“运行后约 6 小时自然清除”的说法。真实组织方配置或人工删除未保存，不能完全排除，但没有必要凭此假设发生过清除。

## 4. 硬上限确实变了，但没有找到因果连接

`challenge/fair_clock.py:65–76` 读取组织方 `OBSERVER_CLOCK_MODE` 与 `OBSERVER_WALL_CAP_SECONDS`；默认 cpu 硬上限为 2 倍预算（第 60 行）。因此 Sophon1 的 1800 与 Sophon2 的 3600 可以由组织方 wall-cap 覆盖解释；后续 Sophon3/envdiag 甚至为 10800。

此路径不构造 participant 环境、不生成能力，也不读 S。两次早期运行没有超时，初始化时就已观察到差异，所以 wall cap 不是已证明的原因。它的实际作用是提示：同一个 runner-10 标签期间，组织方运行配置确实可以变化，不能只比较 Git 提交或标签就宣称部署完全相同。

公开本地历史中，job_runner/docker_runtime 在阳性与阴性之间没有变更，observer-orchestrate 相关最近变更也早于两次运行。与此同时，debug/auto 双榜公开提交 `cd0ce1d` 在 10-05 21:14:17Z，恰好夹在二者之间。私有 Sophon 签发/认证随改版变化仍是较直接的候选，但 Git 时间不是部署时间，不能凭相关性定论。

## 5. 能区分候选的最小缺失证据

当前没有理由用新 HTTP 认证排列替代元数据排查。由主线在既有授权下取得这些**不含值**的数据，即可判断下一步是否存在单变量对照：

1. 两个早期 batch 的实际 `revision_id/mode/purpose/phase_id/model_disabled`；revision 的 `created_at/source_digest/manifest`（仅普通配置和变量名字）；对应 run 的 attempt/placement/runner 版本标识。若 mode/phase/model_disabled 相同，可继续排除这几类候选。
2. 当时 S 是否进入 team.environment；若有，仅核对来源类别、名字、`model/disabled/updated_at` 与变更审计时间，**不取值、hint、密文、请求头或签发原文**。若正好是 disabled 或 model 分类改变，才有明确修复对象；不能把一个旧的运行凭证重新启用后当成当前有效凭证。
3. 若上述元数据一致，需私有注入合同或部署记录确认旧/新系统是否更换 token 名、签发条件或运行绑定。公开代码与下载产物没有携带这些信息。本地没有足够证据承诺重跑 sophon1、取消 no_model、改 manifest 或切 public test 能恢复它。

相关综合报告：`auto_fresh_recovery_audit.md`。本次新增证据主要是 TeamEgress 双阳性、allowlist 的抛异常语义、S 不命中自动 model 分类、诊断日志为空，以及 hard-cap 覆盖来源；其余事实为交叉复核。
