# Auto 候选运行认证：精确公开源码证据

**已证明：** 标准 participant 容器获得 `OBSERVER_RUN_TOKEN`，model_disabled 路径也保留它；它用于 observer-session 的运行级认证。
**未证明：** 私有 `sophon/desk` 是否接受这个 capability，以及 `x-sophon-site` 是否控制 debug/auto。不要把候选写成已验证机制。

以下是本地公开仓库 HEAD `373d94f` 的逐字源码片段，未读取任何真实环境值或凭证文件。

## 1. Colocated 引擎确实走 participant 环境创建，并随后应用 model_disabled

[project_platform/job_runner.py:231](/home/shu/kamico/observer/hackathon-survey26/project_platform/job_runner.py:231)（第 231–240 行）

```python
    participant = payload.get("colocated")
    if is_v4_bundle(scenario) and (participant is None or payload.get("instance") is not None):
        # v4 cards run only next to the participant container (thousands of steps).
        raise JobError("v4_requires_colocated")
    if participant is not None:
        # Public scenarios only: the scheduler never colocates a private instance.
        if payload.get("instance") is not None:
            raise JobError("colocated_private_instance")
        runtime, environment = _participant_runtime(payload, participant, root, http, sealed)
        environment = _without_model(payload, environment)
```

## 2. Participant 固定注入运行级变量（这里只是源码变量引用，没有真实凭证值）

[project_platform/job_runner.py:214](/home/shu/kamico/observer/hackathon-survey26/project_platform/job_runner.py:214)（第 214–221 行）

```python
    environment = {
        "OBSERVER_API_URL": payload["session_url"], "OBSERVER_RUN_TOKEN": participant["run_credential"],
        "OBSERVER_RUN_ID": payload["run_id"],
        "OPENAI_BASE_URL": participant["model_base_url"], "OPENAI_API_KEY": participant["run_credential"],
        "ANTHROPIC_BASE_URL": anthropic_base(participant["model_base_url"]),
        "ANTHROPIC_API_KEY": participant["run_credential"],
    }
    return DockerWorkspace(workspace, manifest, manifest.image), environment
```

## 3. Team egress 保留运行身份；禁模型只删除模型代理项

[project_platform/job_runner.py:55](/home/shu/kamico/observer/hackathon-survey26/project_platform/job_runner.py:55)（第 55–69 行）

```python
def _team_environment(environment: dict[str, str]) -> dict[str, str]:
    """Run identity only: no model-proxy settings next to the team's own variables."""
    return {key: environment[key] for key in ("OBSERVER_API_URL", "OBSERVER_RUN_TOKEN", "OBSERVER_RUN_ID",
                                              "OBSERVER_MODEL_DISABLED") if key in environment}


_PROXY_MODEL_ENV = ("OPENAI_BASE_URL", "OPENAI_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY")


def _without_model(payload: dict, environment: dict[str, str]) -> dict[str, str]:
    """An evaluation without a model (本次不提供模型): the platform has already left out the team's
    model variables; the project also gets no model-proxy settings and OBSERVER_MODEL_DISABLED=1."""
    if payload.get("model_disabled") is not True:
        return environment
    return {**{k: v for k, v in environment.items() if k not in _PROXY_MODEL_ENV}, "OBSERVER_MODEL_DISABLED": "1"}
```

## 4. 官方文档明确运行身份仍在容器中

[docs/model-api-keys.md:123](/home/shu/kamico/observer/hackathon-survey26/docs/model-api-keys.md:123)（第 123–124 行）

```text
private run logs. The participant container still gets `OBSERVER_API_URL`,
`OBSERVER_RUN_TOKEN` and `OBSERVER_RUN_ID`, and no platform model credential.
```

## 5. 通用 session 客户端认证形式

[project_platform/session.py:88](/home/shu/kamico/observer/hackathon-survey26/project_platform/session.py:88)（第 88–91 行）

```python
            request = urllib.request.Request(self.url, data=body,
                headers={"Authorization":"Bearer "+self.credential, "Content-Type":"application/json",
                         "Accept-Encoding":"gzip", **encoding,
                         **({"x-region":SESSION_REGION} if SESSION_REGION else {})}, method="POST")
```

## 6. 通用 session 服务端接收并解析 Authorization

[supabase/functions/_shared/observer-session.ts:72](/home/shu/kamico/observer/hackathon-survey26/supabase/functions/_shared/observer-session.ts:72)（第 72–79 行）

```typescript
export async function sessionRequest(request: Request, rpc: Rpc): Promise<unknown> {
  const { run, token } = capability(request.headers.get("authorization"));
  const body = await boundedJson(request, 17 * 1024 * 1024);
  if (!body || typeof body !== "object" || Array.isArray(body) || typeof body.action !== "string") {
    throw new ProxyError(400, "invalid_session_request");
  }
  const base = { p_run: run, p_token: token };
  // Fixed mapping: a request can never pick an arbitrary privileged RPC.
```

## 7. 公开网页给 desk 请求加的来源标记（用途未公开）

[web/src/components/leaderboard/SophonBoards.vue:47](/home/shu/kamico/observer/hackathon-survey26/web/src/components/leaderboard/SophonBoards.vue:47)（第 47–58 行）

```typescript
async function submit() {
  if (!flag.value.trim()) return
  busy.value = true
  try {
    const { data, error } = await supabase.functions.invoke('sophon/desk/flag', { body: { flag: flag.value.trim() }, headers: { 'x-sophon-site': '1' } })
    const body = data ?? (error && 'context' in error ? await (error as { context: Response }).context.json().catch(() => null) : null)
    reply.value = body?.message ?? pick('No answer.', '没有回应。')
    if (body?.solved) { flag.value = ''; await load() }
  } finally { busy.value = false }
}
async function download(name: string) {
  const { data } = await supabase.functions.invoke('sophon/desk/files/' + name, { method: 'GET', headers: { 'x-sophon-site': '1' } })
```

## 最小验证

先等本次 envdiag 的环境**名字**，确认 OBSERVER_RUN_TOKEN/OBSERVER_RUN_ID 是否实际存在；不需要读取其值。若主线批准后续平台实验，可在下一次已计划的 Sophon 运行容器里对已知 GET /desk 作一次限定认证验证，日志只留 HTTP 状态、board、错误码，凭证只在内存使用且不离开已批准的目的地。未获得相应授权前不实施，也不猜新端点。
公开仓库没有 sophon 服务实现；上述 observer-session 认证证据不能独立证明 desk 的接受规则。
