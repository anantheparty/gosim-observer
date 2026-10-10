# No.4 全量响应复核

结论：**没有找到已返回但漏交的真旗，也没有找到明确指向 No.4 的未使用入口。** 最新根页仍是 21/22，仅缺 No.4。唯一出现过的 `pass` 已与被拒绝的假通行证逐字匹配；它不是漏掉的另一串旗标。私有判据未知，不能据此断言 No.4 没有其他条件。

范围：`desk_calls.jsonl` 第 1–406 行（最后时间 `2026-10-07T05:43:17Z`）、`house_map.jsonl` 全 124 条、`rooms.json`、`boards_now.json`、`work/online/sophon_flags.log`。只读离线分析，未请求任何端点，未读取凭证。机器摘要用题号别名代替完整旗标。

| 交付文件 | 内容 |
|---|---|
| `no4_full_evidence.json` | 源日志 SHA-256 与时间边界、全部字段及首次/末次出现、28 种响应结构、附加字段时间序列、完整特殊响应、所有合同提示、旗标来源与盖章关联、receipt 与榜单编号映射 |
| `audit_no4_full.py` | 离线重建脚本；输入仅上述本地文件；不执行 hand-in 或任何请求脚本 |

## 检查结果

| 检查 | 结果与定位 |
|---|---|
| 全字段 | 47 个真实顶层字段，另以 `_raw_text` 包装第 209、210 行两份非 JSON 响应；总计 100 个归一化字段路径。没有 `usage` 字段，但合同已从 `answer/door/go/visit/more/checkout/message` 等字段提取，不能把“无 usage”说成“无提示”。 |
| 直接 `flag` | desk 共 17 次，全部与已盖章题号匹配。No.17 在 L265 返回，对应独立 hand-in 日志 L13；No.18 在 L20 返回，对应 hand-in L12。仅审 desk 中的提交记录会漏掉这两次盖章。 |
| Receipt | 7 次快照、62 条记录、10 个唯一 run；各 run 的 receipt 正文在已见快照间保持一致。所有回执码仅对应已解 No.1、No.6、No.22；没有未交代码，也没有先出现后消失的代码。7 次 `waiting` 均为空。 |
| 唯一 `pass` | L25，`2026-10-06T19:05:04Z`。相同串在 L254（`2026-10-07T04:33:00Z`）提交，HTTP 422、`error=fooled`，原话：`Johnny grins. "Gotcha." That pass was never real.` |
| 酒吧附加字段 | 含 `/desk/bar` 的已见响应中，197 条仅 `ok/johnny/door/message`，1 条另有 `pass`，3 条仅为 GET 用法提示。没有第二个 pass、隐藏 receipt 或 flag 字段。只出现一次是观测事实，不能推断服务端的一次性触发机制。 |
| 字符串全扫 | 递归扫描所有回复字符串及 house 响应，并与 desk/hand-in 接受记录匹配；**未映射的实际返回旗标串为 0**。共 33 个别名：21 个已解题、1 个假 pass、1 个格式占位符、10 个只在失败提交中出现的猜测。 |
| 根页状态 | 18 份快照，`pending` 始终为空。L282、346、395 均 21 题，仅缺4；最后三份 `found` 相同。`next` 从 front door→bar→typewriter→the house→house entrance→ballroom→front desk，L252 起不再出现；它没有给出 No.4 指引。 |
| 普通房间缓存 | 40 个房号，唯一额外合同字段在 237，为已解 No.17。217 不在此缓存，但独立 GET 的旗标已映射 No.18；不是漏查或漏交 No.4。L400、401 的 214 子路径只返回 404，没有新字段。 |
| House 地图 | 124 份响应、123 个唯一房间，已公布出口未读取目标为0。唯一 `note` 在地图 L120，指向已解 No.16 卷尺；唯一 `flag` 在 L124，是已交 No.10。最深房正文中的 pass 指同一 No.10。旧地图不能证明新实例已探索完，也没有证据把新实例当作 No.4。 |

## 容易误读的榜单编号

**榜单 `F4` 不等于题号 No.4。** 公开 SQL `hackathon-survey26/supabase/migrations/20261006000000_sophon_boards.sql:41` 明确使用：

```sql
'F' || dense_rank() over (partition by board order by min(at), no)
```

这是该榜各题的首次获旗时间排序标签。缓存里只有本队成绩，所以恰好也与本队当时的获旗顺序一致。用 `boards_now.solved_at == desk.found.at` 精确关联，18 条全部匹配：

| 榜单显示 | desk 题号 | 榜单显示 | desk 题号 | 榜单显示 | desk 题号 |
|---|---:|---|---:|---|---:|
| F1 | 1 | F7 | 7 | F13 | 10 |
| F2 | 2 | F8 | 8 | F14 | 13 |
| F3 | 19 | F9 | 11 | F15 | 15 |
| **F4** | **18** | F10 | 20 | F16 | 21 |
| F5 | 3 | F11 | 9 | F17 | 14 |
| F6 | 5 | F12 | 16 | F18 | 22 |

此榜单缓存止于 `2026-10-06T20:11:06.353973+00:00` 的 No.22，早于后来解出的 No.12、No.6、No.17。它的 F4 不是漏解题的名称证据，F18 也不是 No.18。

## 附加内容是否还有未归属支线

| 字段/内容 | 已归属题目与证据 |
|---|---|
| `radio` | No.19 Hallorann；desk L13 返回、L14 盖章 |
| `page`、`lipstick` | No.5 打字稿、No.6 天空字母；分别 L127、L251 盖章 |
| `letter`、`margin/margin_answer`、`bookshelf` | No.7 作业、No.8 名著、No.20 人列计算机；L133、134、140 盖章 |
| `map/legend` | No.11 树篱；L135 盖章 |
| `measurements`（仅 L150） | No.16 卷尺；L153 盖章 |
| `hotel_register/bar_tab/photograph_caption` | No.13 舞厅名单；L160 盖章 |
| `darkroom`、`frames` | No.15 照片、No.21 倒计时；L164、168 盖章 |
| `more/checkout` | No.14 退房；L205 盖章 |
| `question/answer`（237） | No.17 镜子；L265 返回，hand-in 日志 L13 盖章 |
| `loss_of_signal`（仅 L206） | No.22 完赛文本，同行 `no=22/solved=true`；不是额外未交代码 |
| `pass`（仅 L25） | 已被 L254 明确判为假；无 `no=4`、新路由或替代码 |

No.4 与酒吧之间目前仍只有“编号相邻、唯一特殊 pass”这样的推测；日志没有给它正式名称或作答合同。本轮不建议根据缺号再提交 pass、重走四词门或猜新端点。机器摘要保留了每项原字段与时间，可供后续出现新题面时重新关联。

快照末尾 L404–406 的 `/desk/gotcha`、`/desk/fooled` 均为普通 404 `no_such_place`，也未增加字段或题面。
