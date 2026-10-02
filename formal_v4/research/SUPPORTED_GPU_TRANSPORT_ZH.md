# 通过官方兼容 API 接入自有 CUDA 求解器的审计

核实时间：2026-10-03。公开官方仓库 HEAD 为 `f2205aaffcc923bdc1abb91b2c131bb7b82df7b2`。本审计未改变团队配置、启动服务或提交评测；公开源码副本及 SHA-256 位于忽略的 `runs/supported_gpu_transport_audit/`。

## 1. 结论与依据

技术上，可以把自有传统数学求解器实现为标准 OpenAI-compatible 非流式聊天接口，经平台正常配置和 `OPENAI_BASE_URL` 调用。它不要求利用 IP、重定向、私有路径或改变容器隔离。

规则 §4.3 明确允许外部算力、外部服务及自有服务器，§4.2 允许不限服务商的 OpenAI-compatible 公网 HTTPS 接口。§3.6 的至少两个大模型环节是评奖资格要求；本研究不申请该资格。没有找到运行评分必须实际调用 LLM，或兼容服务后台必须是 LLM 的条款。服务应诚实标识 `traditional-cuda-planner`，不能声称其使用大模型。

官方未特别举出“传统 CUDA 数学求解器通过 Model API 接入”的案例，因此上述规则解释是依据条文作出的判断，不是主办方对该具体架构的个别确认。如果需要主办方对资格的正式结论，应另行澄清；本次未联系任何人。

依据：

- [规则 §3–4](https://github.com/gosimfoundation/hackathon-survey26/blob/f2205aaffcc923bdc1abb91b2c131bb7b82df7b2/web/src/content/rules.zh.md#L37)：外部服务、自动决策、接口条件、评奖资格。
- [自备模型 API 文档](https://github.com/gosimfoundation/hackathon-survey26/blob/f2205aaffcc923bdc1abb91b2c131bb7b82df7b2/docs/model-api-keys.md#L109)：队伍不限服务商名单，允许任意满足条件的公网 HTTPS 兼容 base。
- [端点校验](https://github.com/gosimfoundation/hackathon-survey26/blob/f2205aaffcc923bdc1abb91b2c131bb7b82df7b2/supabase/functions/_shared/observer-public-base.ts#L1)：只接受默认 443、公网 DNS/TLS，拒绝 IP、内网、重定向；不改变这些规则。
- [容器出网](https://github.com/gosimfoundation/hackathon-survey26/blob/f2205aaffcc923bdc1abb91b2c131bb7b82df7b2/project_platform/egress.py#L1)：仅连接官方代理；使用平台注入的 `OPENAI_BASE_URL` 和 scoped `OPENAI_API_KEY`，不需要把自有服务器密钥交给容器。

## 2. 正常调用格式

平台代理收到请求后，按团队的配置调用 `base + /chat/completions`，并用团队配置的模型名称替换请求的 `model`。请求示意：

```json
{
  "model": "traditional-cuda-planner",
  "messages": [{"role": "user", "content": "{\"schema\":\"traditional-planner-v1\",\"session\":\"随机UUID\",\"seq\":1,\"op\":\"choose\",\"state\":{}}"}],
  "max_tokens": 4096,
  "stream": false,
  "n": 1,
  "temperature": 0
}
```

响应使用标准 chat completion envelope，`choices[0].message.content` 为严格 JSON 字符串，其中装载求解器动作。`model` 保持真实名称。响应可以包含 `id`、`object: chat.completion`、`created`、`finish_reason: stop` 等标准字段。

`usage` **不是必需字段**。保存模式下缺失 usage 将保守使用本次预留 token 上界记账；临时 relay 模式不计 tokens。不应编造大模型 token 使用记录。

具体校验见 [validateChat](https://github.com/gosimfoundation/hackathon-survey26/blob/f2205aaffcc923bdc1abb91b2c131bb7b82df7b2/supabase/functions/_shared/observer-model.ts#L77)、[保存模式转发](https://github.com/gosimfoundation/hackathon-survey26/blob/f2205aaffcc923bdc1abb91b2c131bb7b82df7b2/supabase/functions/_shared/observer-model.ts#L188)、[临时模式转发](https://github.com/gosimfoundation/hackathon-survey26/blob/f2205aaffcc923bdc1abb91b2c131bb7b82df7b2/supabase/functions/_shared/observer-personal-model.ts#L59)。源码不检查实际推理后端是否为神经网络，但这项事实本身不代替规则解释。

## 3. 临时“不保存”模式

该模式适用于当前 practice：密钥、端点和模型名称仅在打开的参赛页 Vue 内存中，代理经 Broadcast 唤醒页面，页面经 portal 调用服务。`sessionStorage` 只保存“曾连接”布尔标志，不存密钥。必须保持页面打开；重新加载、切换路由或关闭页面会清掉本次连接。

源码：[usePersonalModel.ts](https://github.com/gosimfoundation/hackathon-survey26/blob/f2205aaffcc923bdc1abb91b2c131bb7b82df7b2/web/src/composables/usePersonalModel.ts#L5)。

**保存模式切换到 relay 会立即删除已有加密密钥，保存新密钥也会替换已有配置。**因此接入前只读 UI 中的模式、端点、模型名称、key hint 元数据；若已有长期配置，不应为了本次试验直接覆盖或删除。本审计只读公开文档，无法确定当前队伍页面是否已有 provider。

隐藏卡无人打开页面，若届时仍依赖该接口，必须用平台支持的加密保存配置，并保证服务可复现至核验结束。

## 4. 硬限制与会话设计

| 项目 | 官方实现 |
|---|---|
| 请求 | 64 KiB；JSON 清理补入默认字段后再次核对 |
| 响应 | 192 KiB |
| messages | 1–128 条，文本 content；正常 role 字段 |
| 输出参数 | `max_tokens` 或 `max_completion_tokens` 仅选一个，1–4096 |
| 并发 | 每 run 最多 4 个未完成请求 |
| 调用数量 | 配置文档默认每 run 100,000；实际 run 按启动时设置 |
| tokens | 保存模式默认 1,000,000,000；relay 不计 tokens |
| 超时 | 保存模式 120s；relay 上游 110s；这些上限远大于每卡900s预算可承受值 |
| 传输 | 不支持 streaming，n 必须为1；不跟随 redirect |

当前 HTTP `RemotePlanner.choose` 的完整 10,000 目标 scores/factors JSON 不能假定符合 64 KiB。α公开目标 catalog 转成列式 JSON（此测量保留 CSV 字符串）为751,737字节，gzip+base64 为309,140字节，需要7个48KiB内容块；初始化还需其它公开配置。

可实施的普通协议：

1. 每卡创建独立随机 session UUID；只发送本卡公开初始化与本程序已经取得的观测状态。
2. 初始化和必要的全量状态用普通文本 content 分块；每块含 session、总块数、块号、内容 SHA-256。完整接收并校验后原子提交。
3. 后续发送准确状态 delta，或小于限制的完整压缩状态；不可未经分析降低 required 完成度证据的精度。
4. 每次 choose 带 decision sequence 和独立 request nonce；服务去重同一 nonce，拒绝同 seq 不同 payload。官方 gateway 的 Idempotency-Key 不会传给自有上游，因此去重信息应位于普通 message content 内。
5. 每会话拥有独立账本和状态；GPU 调度可共享计算资源，但不能串卡或继承其它卡的天气信息。服务有容量限制、TTL、close，保持审计记录。
6. 严格解析动作，失败走本地算法；不能让网络探测长时间吞掉900s。

把 gzip+base64 放在 message 的文本 content 是兼容接口中的普通应用数据；不能改用不支持的 Content-Encoding 绕过代理大小限制。

## 5. 延迟与总分验证

此次完整云端 CPU 评测耗时231–317秒，剩余预算不是无限。官方代理增加 Edge、数据库记账、relay Broadcast/页面和 HTTPS 转发；本机 CD2 的约0.49秒调用不能代表完整代理延迟。四卡可能同时运行，自有 GPU 串行锁会增加排队。

设还需 N 次决策，非搜索开销H、本地每次c、代理GPU每次g、预留R，则GPU调用数量k必须满足：

`H + (N-k)c + kg + R <= 900`。

应先用免费接口检查测完整代理 p50/p90、初始化块延迟、四卡并发排队；再决定GPU配额。无真实时限失败的完整四卡分数，才是评估该路线收益的依据。更强单步搜索不保证全季分数单调提高，deadline、观测覆盖、天气信息与故障辨识仍属于整体策略。

## 6. 独立原型与本地门检

实现文件：`model_gpu_transport.py`、`model_gpu_adapter.py`。客户端沿用原 RemotePlanner 的 check/choose/close 接口、次数/耗时与两次搜索失败后停用逻辑；不修改冻结的参赛入口或 GPU 后端。adapter 仅监听 IPv4 loopback，默认19928，固定后端可用 `http://127.0.0.1:19926` 连接现有隧道。

scores/factors 使用精确 overwrite delta：初始化服务器零数组；每次成功 ACK 后客户端才提交上次数组。若 ACK 丢失，下次完整 reset，避免“服务器已变更但客户端不知，随后该值改回上次ACK值”时漏同步。不量化浮点数。服务端每 session 单独保留数组并验证递增 sequence；动作仍交给原 GPU 接口计算。

42KiB base64 文本分块、SHA-256、随机 upload_id/nonce、同请求响应缓存。上传和receipt TTL120s，最多16个上传、4096个receipt、4个并发；上传与receipt容量32MiB，会话数组另限32MiB，最多16会话/每会话100,000目标、TTL2h；单次解压最多12MiB。只允许四种固定 backend 操作，不转发任意 URL/文件/shell。

`python3 -m formal_v4.research.model_gpu_transport_checks`：16项本地 stub 门检全部通过，2.567秒。覆盖分块最后一块直接计算、重复nonce不重算、数据/SHA损坏、解压上限、TTL/容量/并发、协议错误、认证/CORS/路径/大小、session隔离、陈旧sequence、状态下降、ACK丢失后的精确复位、2次失败回退。含10,000目标质量数组+16目标delta的一块请求检查。

这只证明本地兼容传输与状态同步，不证明真实GPU收益或平台代理可用。测试只建立自动关闭的随机本地端口 stub，没有部署19928、改变队伍密钥或消费评测次数。
