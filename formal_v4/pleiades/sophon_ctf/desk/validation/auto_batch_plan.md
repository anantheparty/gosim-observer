# Auto 成功后的最小批量候选包

候选目录：`work/packages/o4s_sophon4_autobatch_candidate/`。**目前 disabled，未上传、未打包、未评测。** 认证模式尚未冒充为已验证；需主线依据真实 auto 成功结果设置配置。

## 真值列表与来源

- `flags.json` 包含 **21 个不同的真实成功码**，编号 No.1–22，排除 No.4，No.22 最后。
- `desk_calls.jsonl` 中 `POST /desk/flag`、HTTP 200、`solved=true` 提供 19 个；`sophon_flags.log` 第 12、13 行补 No.18 和 No.17。
- 每个编号的来源文件及精确行号见同目录之外的 `validation/auto_batch_provenance.json`。只从成功 hand-in 提取，不把谜面、bar.pass 或仅见过未验收的串混入。
- 已额外对比 desk_calls 第 25 行的假 pass，确认它不在静态列表中。列表没有运行 token、用户 token、邮箱凭证或模型凭证。

## 与原包的差异

以 `work/packages/o4s_sophon4_autoflagbody/` 为基础：

| 文件 | 变化 |
|---|---|
| `authcheck.py` | 改为已验证认证模式下的单次批量提交器；默认关闭 |
| `flags.json` | 新增 21 个真码静态列表 |
| `autobatch_config.json` | 启用状态、认证模式、验证来源与 `verified_nos` 已确认编号 |
| `agent.py`、`glyph_policy.py`、`probe_config.json`、`probe_geometry.py`、`astro.py`、manifest、requirements | 7 文件与源包逐字节一致 |

原 agent 在**首个 decision_request 到达后、发出首条决策前**调用 authcheck.run 一次；批量完成或停止后继续原观测逻辑。原 glyph policy 用 `wait(until_utc=survey.end_utc)` 收尾，没有新增 finish 动作。网络异常不向观测主循环传播。

这保留了原包的 survey_complete 路径；本轮没有跑引擎，因此不声称已在线验证候选包终止状态。

## 启用条件

当前配置为 `enabled=false`、`verified_nos=[]`，其他项为 null。确定某种方式确实记入 **auto** 后，由主线设置；下例 `[1]` 仅适用于验证探针已经确认 No.1 的情况：

```json
{
  "enabled": true,
  "auth_mode": "<唯一已验证模式>",
  "verified_board": "auto",
  "verification_run_id": "<产生认证/归榜证据的run UUID>",
  "verified_nos": [1]
}
```

支持的模式仅为已有探针中的 `body_sophon`、`body_observer`、`bearer_observer`、`query_observer`、`body_bearer_observer`、`bearer_observer_site`。**每次只执行选定的一种，不在批量过程中猜测或回退模式。** 模式对应的 token 仅从当前运行 env 读取，在内存中传给固定主办方 `sophon/desk/flag`；没有用户 JWT，也不把当前 env 值带入包。

元数据门槛是防误启用措施，不是服务端认证证明；主线仍须核实验证结果确实来自 auto 榜。disabled 时连运行 token 值都不读取。

Auto 记录是 team-wide，验证运行已经提交的编号不能在后续运行重新当作未解题处理。启用时 `verified_nos` 必须是非空、不重复的有效编号列表，并且由主线纳入验证运行已确认的全部编号；字符串、布尔值、No.4、未知编号均拒绝。程序在读取 token/发请求前过滤这些编号，日志只写 `skipped_count`，不输出被跳过的编号列表。若全部已确认，则不读取 token、不联网。

对于服务端临时返回 `already_solved`，即使同时有匹配的 no 和 `board=auto`，候选也**停止整批**，不自动更新跳过列表或继续提交。这样不会把未核实的重复响应当作本地状态依据；主线可离线核实后再更新配置。本候选依赖配置跳过，不扩大运行时成功判断。

## 有界执行与日志

| 行为 | 上限或停止条件 |
|---|---|
| 请求范围 | 固定 HTTPS 主办方 `/functions/v1/sophon/desk/flag`；禁止重定向 |
| 提交次数 | 静态 21 码减去 `verified_nos`，每码至多一次；预计 `[1]` 时最多 20 次，剩余 No.22 最后 |
| 重试 | 不重试，不自动换认证 |
| 429 / closed | 立即停止整批 |
| 身份失效、401/403/404、5xx、意外响应、明确 board=debug | 停止整批，继续观测收尾 |
| already_solved | 即使编号匹配且 board=auto 仍停止；依赖预先核实的 verified_nos 跳过 |
| HTTP 200 | 只有 solved=true 且回报 no 与本次编号一致才继续 |
| HTTP 422 wrong_answer/locked | 记录编号与固定错误枚举后继续下一个已验真码，不重试；其他 422 停止 |
| 单次请求 | socket timeout ≤3 秒，额外主线程硬截止 4 秒 |
| 总批次 | 90 秒，正常间隔 0.25 秒；v4 官方为 global-only、无 per-decision timeout |
| 硬截止仍在执行的请求 | 结果未知；停止新增请求，最多剩一个 daemon worker，不重试；退出容器时一并结束 |
| 日志 | 只记固定事件、请求编号、状态、固定 error/board 枚举、布尔 solved、有限 no、耗时 |

日志不输出 flag 本文、任何 token、token 哈希、URL/query、认证头、服务端原始文本、动态 JSON 键或异常信息。服务器把凭证放进 error/board/未知键的模拟回显测试已通过。

限额是服务端合同的一部分：候选不假定 auto 有豁免，遇 429 停止，不绕过次数限制。如确有每小时小额上限，21 条可能需要另行分批计划；本候选不会自己重复评测或重传。

## 离线验证

`PYTHONDONTWRITEBYTECODE=1 python work/sophon_desk/validation/test_auto_batch_candidate.py`

17 个测试通过；所有 HTTP 入口均被 mock，没有平台、模型或引擎调用。覆盖：默认禁用、配置验证门槛、21 码顺序与 No.4 排除、验证编号跳过和仅计数日志、全已确认时不联网、already_solved 保守停止、429/closed/认证错误/错榜停止、未知结果停止、单次与总截止、局部失败不重试、固定请求路径和各认证映射、回显脱敏。文件哈希与来源清单见 `auto_batch_provenance.json`。
