# SOPHON_RUN_TOKEN：已有产物的离线核查

核查日期：2026-10-07 UTC。只读取已有产物与公开源码；未调用平台、网络或模型，未修改包。本文仅记录变量名、存在性、运行标识、阶段、时间、HTTP 状态及证据定位；不包含凭证值、请求头值或令牌解析内容。

**结论：10 月 5 日 17:10 的 Sophon 卡评测中，进程环境确实存在 `SOPHON_RUN_TOKEN`，并发生 9 次 Johnny HTTP 200。现有证据不能把它称为“准备阶段的 public test”。** 同日 22:58 的 Sophon 卡评测已不含该变量；后续 Sophon3 评测和现存唯一可确认的 `v4-public-test` 产物也记录为空。

当前没有找到 10 月 5 日 public test 的独立产物，因此“当时 public test 曾注入”仍未证实，也不能从缺少产物推断它从未注入。此前“准备期公开测试返回 Johnny 200”的说法应改为上述可定位的 Sophon evaluation 事实。

## 运行对照

下表中 `L` 均指 `agent_log.json` 的 `log` 字符串解码为 JSONL 后的行号，不是外层 JSON 文件的物理行号。相同日志也可在相邻 `result.zip` 的 `agent.log` 内定位。所有 Sophon 卡目录的 scenario ID 为 `179e0a27-f9d8-4207-b36b-daa402e0c987`。

| 产物目录（相对 `work/online/`） | 运行阶段与 ID | 实际运行开始时间 UTC | 变量存在性与 Johnny 状态 | 证据 |
|---|---|---|---|---|
| `sophon1_2a97/179e0a27-f9d8-4207-b36b-daa402e0c987/` | Sophon evaluation；run `1e87fc81-de27-40a4-8f4a-792f8f046d7e`；batch `2a97f632-a405-4b19-be97-f703474238a0` | `2026-10-05T17:10:42.551163+00:00` | `SOPHON_RUN_TOKEN` 存在；9 次 HTTP 200 | `agent_log.json` L9：`sophon_init.meta.env_sophon` 包含该变量名。L11、12、84、144、211、302、336、411、424：`johnny.status=200`。`run.json` 的 `/id`、`/batch_id`、`/started_at`；`result.zip` 内 `workflow_result.json` 的 `/scenario` 为 `Sophon practice prototype`。 |
| `sophon2_f599/179e0a27-f9d8-4207-b36b-daa402e0c987/` | Sophon evaluation；run `2dd4bcc3-78ae-4162-b1c9-ce12b452596b`；batch `f5995cb0-cc61-453c-bedf-aef75f0d4411` | `2026-10-05T22:58:42.884734+00:00` | `SOPHON_RUN_TOKEN` 不存在；Johnny 被跳过 | `agent_log.json` L9：`sophon_init.meta.env_sophon=[]`；L10 为 Johnny 跳过记录。`run.json` 同上字段；同样的 Sophon scenario。 |
| `sophon3_2d79/179e0a27-f9d8-4207-b36b-daa402e0c987/` | Sophon evaluation；run `d76dd617-37cb-4d25-a604-654ed77239c3`；batch `2d79ab4b-3b0c-40cc-b2fb-42e92db5e636` | `2026-10-06T18:14:38.056898+00:00` | 非空凭证存在性 `false` | `agent_log.json` L9：`sophon_init.credential_present=false`；`run.json` 同上字段。 |
| `o4s_sophon3_envdiag_15dd/179e0a27-f9d8-4207-b36b-daa402e0c987/` | Sophon evaluation；run `b96463f0-7ccf-46af-b009-2083ec46d012` | `2026-10-06T20:20:49.214136+00:00` | 非空凭证存在性 `false` | `agent_log.json` L10：`sophon_init.credential_present=false`；L11、885：`johnny_skip`。 |
| `sophon3_pubtest/` | 已确认 public test；产物内未找到可直接绑定的 run/revision ID | 产物未提供可用于本审计的运行开始时间 | 非空凭证存在性 `false` | `agent_log.json` L9：`sophon_init.credential_present=false`；L10、12：`johnny_skip`。`result.zip` 内 `workflow_result.json` 与 `score_report.json` 的 `/scenario` 均为 `v4-public-test`。 |

另外，`sophon3_saturn_1842`、`sophon3_mars_1cfd`、`sophon3_venus_6fc6`、`sophon3_jfull_54e0`（及其 `_v2` 重复下载）的初始化也均为 `credential_present=false`。`54e0` 与 `_v2` 是同一个 run `4cb33db6-089a-4b42-b0d2-f370c89d8267`，不能计作两个独立运行。

## 为什么不能把阳性归到 public test

| 问题 | 可核实事实 | 能支持的结论 |
|---|---|---|
| `phase=practice` 是否说明是公开测试？ | Sophon1、Sophon2 的 `sophon_init.meta.task_card.phase` 都是 `practice`；相邻 `run.json` 含 evaluation `batch_id`，输出 scenario 是 `Sophon practice prototype`。 | `practice` 是卡片属性；不是 public-test 工作流标识。两次是同一 Sophon 卡的不同评测。 |
| 现存 public-test 证据是什么？ | `sophon3_pubtest/result.zip` 明确给出 scenario `v4-public-test`。`submit_sophon3.log` L1–2 记录 revision `2257d459-fcdd-461f-b7d1-03471ea85b1f`；L4–5 另有 `public_test`、run `7e1aaa32-da1a-4919-9211-2c4a4afe4370`、`passed`。 | 可以确认有后续 public test，且保存的 public-test 产物没有非空凭证。但 ZIP 内未见直接连接该 run ID 的字段，本文不把目录与该 ID 强行绑定。 |
| 是否有遗漏的早期 ZIP？ | 本次枚举 `work/online/` 下 212 个 `result.zip`，按 `workflow_result.json` 的 scenario 分类，仅发现 1 个 `v4-public-test`，即上行目录；也筛查了 225 个 `agent_log.json`。 | 现有下载产物中没有第二份、可证明 10 月 5 日 public-test 行为的结果；范围仅限本地已有文件。 |
| HTTP 200 能否证明存在非空运行凭证？ | Sophon1 源码从环境读取 `self.token`；为空则直接返回。阳性运行还明确记录了变量名。 | 环境变量存在、代码绕过缺失分支且请求获得 200，形成一致证据链。本文不检查凭证内容，也不推断具体注入实现。 |

## 源码复核

| 文件与位置 | 与本问题有关的事实 |
|---|---|
| `work/pkgs/sophon1/sophon_probe.py:40`、`:63`、`:73` | 令牌来源是 `os.environ.get` 的 `SOPHON_RUN_TOKEN`；`env_sophon` 从 `os.environ` 的变量名生成；无令牌分支直接返回。源码中的其他常量及请求头值未复制到报告。 |
| `work/pkgs/sophon2/sophon_probe.py:55`、`:78`、`:133` | 同样从环境读取并记录变量名；Johnny 调用存在缺失令牌返回分支。 |
| `work/pkgs/sophon3/sophon_probe.py:43`、`:44`、`:49` | 从环境读取 `SOPHON_RUN_TOKEN`；`credential_present` 是 `bool(self.credential)`；没有凭证时跳过调用。因此该布尔值代表非空凭证，而非猜测。 |
| 三个包的 `observer.project.json` `/environment` | 仅列出 `PYTHONDONTWRITEBYTECODE`、`PYTHONPATH`、`OPENBLAS_NUM_THREADS`、`OMP_NUM_THREADS`；未声明 `SOPHON_RUN_TOKEN`。 |
| `hackathon-survey26/cli/AGENTS.md:177`、`:355` | Johnny 文档表述为“仅在运行中的评测内有效”；文档未承诺每个 public test 都会注入该变量。 |
| `hackathon-survey26/challenge/v4_runner.py:12`；归档版同位置 | runner 明确把协议接线归到平台层。对公开 `challenge/`、`archive/starter_kit_v4/`、`project_platform/`、`supabase/functions/` 的变量名搜索未发现 `SOPHON_RUN_TOKEN` 的注入实现；缺少公开实现不能证明服务端没有或不应注入。 |

后续若要进一步核实“10 月 5 日 public test”，需要那次 public-test 的独立 run ID 和对应日志，而不是继续使用 `practice` 属性作为阶段依据。本次没有请求或下载任何新产物。
