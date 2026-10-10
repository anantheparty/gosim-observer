# Sophon3 认证诊断覆盖检查

结论：`credential_present=false` **只排除了旧的 `SOPHON_RUN_TOKEN` 有非空值**，不能排除新版变量或 initialize 字段。

| 检查点 | 当前行为 |
|---|---|
| `work/packages/o4s_sophon3/sophon_probe.py:43` | 只读取 `SOPHON_RUN_TOKEN`，且受 `network_allowed` 控制。 |
| 同文件第44行 | `sophon_init` 只记录旧 token 是否非空，未枚举环境变量名。 |
| `agent.py:35` | initialize 的 payload 直接交给 Policy，没有记录消息或 payload 的键名。 |
| `sophon_probe.py:81` | on_snap 只处理后续 snapshot；顶层键筛选仅 `receipt/sophon/flag`，不覆盖通用 auth/token 字段或 initialize。 |
| `agent.py:67` | `sophon_finish_message` 是 finish 消息，不是初始化内容。 |

木星 `sophon3_2d79` 与 jfull `sophon3_jfull_54e0_v2` 的已下载 agent_log 均显示：

```json
{"network_allowed": true, "credential_present": false}
```

两个日志都没有 `env_sophon`、环境名字列表或 initialize 键名列表。结果 ZIP 的 `messages.jsonl` 也没有 initialize 消息，不能从这些已下载产物补回初始化结构。没有发现记录了新版认证名的字段，但这不证明容器当时不存在新版认证。

建议下一次已计划的包附带**仅名称与布尔值**的初始化诊断，不新增端点请求：

```python
log('sophon_auth_schema',
    environment=[{'name': name, 'nonempty': bool(os.environ.get(name))}
                 for name in sorted(os.environ) if name.startswith('SOPHON_')],
    initialize_keys=sorted(msg.keys()),
    payload_keys=sorted(payload.keys()) if isinstance(payload, dict) else [],
    payload_is_object=isinstance(payload, dict))
```

若顶层出现 auth/credentials/sophon 等对象，只补记该对象的**子键名和是否非空**；不打印值、不打印长度/摘要、不复制凭证、不把整个对象传给现有 log。现有 safe() 主要靠字段名与旧 RUN_TOKEN 脱敏，不能用它替代“从源头不记录新值”。未知新变量即使存在，也只作为下一步选择合法认证方式的证据，不能据此猜调用协议。

未改包、未读凭证文件或旧硬编码 anon key 的 probe，未调用任何平台端点。
