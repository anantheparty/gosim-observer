# Auto 认证：公开源码证据（只读）

最值得验证的运行内认证名称是 **`OBSERVER_RUN_TOKEN`**，不是尚无公开证据的 `SOPHON_DESK_TOKEN`。这只是源码支持的候选；没有证据证明私有 desk 接受它。

## 确定事实

| 证据路径（相对 hackathon-survey26） | 事实 |
|---|---|
| `project_platform/job_runner.py:214` | colocated participant 环境固定设置 `OBSERVER_API_URL`、`OBSERVER_RUN_TOKEN`、`OBSERVER_RUN_ID`。RUN_TOKEN 来自该 participant 的运行 credential。 |
| `project_platform/job_runner.py:55` | team egress 路径仍保留上述三项与 `OBSERVER_MODEL_DISABLED`。 |
| `project_platform/job_runner.py:64` | model_disabled 只删除模型代理环境项并设置布尔控制变量，**不删除 OBSERVER_RUN_TOKEN**。 |
| `docs/model-api-keys.md:123` | 文档明确说 participant 仍获得 OBSERVER_API_URL、OBSERVER_RUN_TOKEN、OBSERVER_RUN_ID。 |
| `supabase/functions/_shared/observer-orchestrate.ts:138` | colocated 模式使用 participant 的独立运行 capability；不是用户登录凭证，也不是 engine capability。 |
| `project_platform/session.py:90` | 公开客户端把运行 capability 放到 `Authorization: Bearer`，用于 session 请求。 |
| `supabase/functions/_shared/observer-session.ts:73` | session 从 Authorization 解析运行身份，再交给固定映射的 RPC；没有任意 RPC 调用能力。 |
| `project_platform/docker_runtime.py:18,138` | 直接 run_environment 白名单含 OBSERVER_*、模型代理项，不含 SOPHON_*；同时另有 team variables 和 manifest environment 合并路径，故不能推出所有新 SOPHON 变量绝不可能存在。 |
| `web/src/components/leaderboard/SophonBoards.vue:51,58` | 网页 flag/files 请求额外设置 `x-sophon-site: 1`。只知道它标记网页来源，不知道服务端是否据此选 debug。 |
| `supabase/migrations/20261006000000_sophon_boards.sql:1` | debug/auto 写入方是私有 `sophon` 函数，公开 RPC 只读取。仓库没有它的认证或归榜实现。 |

旧 `SOPHON_RUN_TOKEN` 只有 CLI contact-johnny 文档；当前公开源码没有新增 Sophon token 名、desk auto 专用变量、auto 认证头或认证 body 格式。历史报告已覆盖其新增/撤下提示的提交，本轮没有重复扫描历史。

## 尚未证明的事

- `OBSERVER_RUN_TOKEN` 是否被 desk 接受；它在 observer-session 的合法用途不能自动推广到其他函数。
- `x-sophon-site` 是否决定 debug/auto；也可能仅用于 UI 文案、来源或其他检查。
- auto 是否依据运行 capability、其他初始化字段、来源或多种条件共同判定。
- envdiag 本次实际会看到哪些名字；需要等已启动的评测产物，不读任何运行值。

## 最小后续验证

1. 等 envdiag，先检查环境名称是否有 `OBSERVER_RUN_TOKEN`/`OBSERVER_RUN_ID`，以及是否存在额外 SOPHON 或认证相关初始化顶层键。这一步完全不需要额外请求。
2. 若主线授权验证 desk 对运行 capability 的接受情况，在下一次已计划的 **Sophon 评测容器内部**，仅对现有已知 `GET /desk` 作一次受控认证请求；值只在内存使用、绝不打印/写文件/复制到主机。日志只保留 HTTP 状态、`board` 与错误代码，不保留认证头。
3. 如果没有文档或审批允许第2步，则先由主线向主办方确认。不要猜未知路径，不试用户登录凭证，不通过删除网页标记就宣称拿到 auto。
4. 若请求给出 auto 的明确响应，再决定如何自动完成合法游戏链；不要在认证未确定前重放会重置门状态的操作。

本轮只读公开仓库；没有平台调用、模型调用、凭证读取、原包修改或网络实验。
