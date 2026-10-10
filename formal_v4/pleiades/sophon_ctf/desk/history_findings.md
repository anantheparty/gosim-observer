# Sophon 公开历史核查（离线）

结论：公开历史支持“早期 Johnny/单一解谜名单，后来新增 desk 多 flag CTF”这一演进，但没有公开旧答案迁移、新 flag 验收、token 注入或回执投递实现。发现过删除的 Johnny 邮箱提示；没有发现可直接提交的新 flag。

范围：只读 `hackathon-survey26` 的全部本地可达历史；HEAD `373d94f32598073b4eff31c15794fcd3474722ae`。这是 **shallow clone，59 个提交**，最早边界 `d293dea`（2026-10-04 17:18:08 UTC）；“未找到”只限此范围。未 fetch、调用平台、读凭证、跑仿真或修改仓库。

| UTC 时间 | 提交 | 直接证据 | 对解题的意义 |
|---|---|---|---|
| 10-05 14:11:27 | `ac9cacd` / #336 | 首次新增 `challenge/v4_sophon.py`、archive 镜像、测试；说明是移植主办方 prototype | 只实现私有夜晚/光纤表、2.5 倍等可配置评分覆盖。没有 planet、flag、Johnny、desk 或回执逻辑。 |
| 10-05 15:38:59 | `17d68bb` / #342 | `cli/AGENTS.md` 和 CLI 网页同时新增 `contact-johnny` + `SOPHON_RUN_TOKEN` 文档；rules/FAQ 增加 Johnny 邮箱 | Johnny 联系路径是正式公开过的线索。代码中没给 token 签发/注入条件。 |
| 10-05 16:34:35 | `5b0b396` / #335 | 新增 `private.observer_extra_phase` 与 `current_competition().extra_phase_id` 条件 | Extra 阶段可先只对指定队伍开放，再取消限制；匿名与登录身份看到不同榜单有实现依据。 |
| 10-05 16:44:02 | `fbb70a7` / #346 | `20261005130000_sophon_solvers.sql` 注明 `private.sophon_solves` 早已在生产库手工创建；每队一行 `run_id`、`key` | 旧单一谜题记录并非本次 migration 首创；公开代码不能确定 `key` 是答案、内部标识还是其他值。 |
| 10-05 16:56:14 | `8519a34` / #348 | 分数“不重要”改为正式说明：仅参考，不计排名/奖项 | 历史文案没有提出巡天总分为正或达到阈值才发奖。私有验收另有条件仍无法排除。 |
| 10-05 21:14:17 | `cd0ce1d` / #361 | 新增 `SophonBoards.vue` 和 `20261006000000_sophon_boards.sql`，debug/auto、多 flag、完赛文字、desk 提交框/文件按钮 | 明确是新的一组表与入口；没有 SQL 数据迁移、触发器或旧 `key` → 新 `no` 映射。 |
| 10-06 06:26:42 | `920f339` / #372 | 提交标题 “Contact line: organizer address only”；从 rules 英/中与 FAQ **删除 Johnny 邮箱** | 确实存在撤回过的公开提示。CLI 的 token API 保留，不能据此认定 Johnny 服务已停用；删除动机未知。 |
| 10-06 13:08:58 | `afa6bd5` / #382 | 新 CLI skill 的网页测试明确要求不含 `sophon/easter/egg`（`web/tests/cliInstall.test.ts:23`） | 通用 skill 刻意不带彩蛋内容；不能把 skill 缺线索误认为完整指南也取消了 Johnny。 |

## 能确认的接口与数据关系

- 当前 `cli/AGENTS.md:177` 仍只描述 `contact-johnny` 接收运行 token、仅评测内有效。全部本地历史中 `SOPHON_RUN_TOKEN` 的唯一引入提交是 `17d68bb`；未找到公开注入实现或后来删除注入代码的提交。
- `SophonBoards.vue:51,58,79,80` 只公开 `desk/flag` 与 `desk/files/<name>`，两个文件名为 `sophon-card-public.zip`、`sophon-local.zip`。没有第三个隐藏文件名或新下载路径的历史。
- 新 SQL 第 1 行明确说新榜数据由主办方运行的 **`sophon` 函数** 写入；公开 RPC 仅只读。仓库无该函数实现，无法由通用 score 成功推导 Sophon 的私有验收成功。
- `private.sophon_g_solves` 可存 `debug`/`auto`，`run_id` 和 `user_id` 均可空；这允许运行关联与人工提交两种来源，但 schema **没有规定**两类如何归榜。
- `private.sophon_g_finishers` 有 `evals`、`k`、`is_first`、双语完赛文字；公开 RPC 只返回文字等。`k` 的含义及通关总关数没有说明。
- 前端 `F1/F2/...` 是按已被解出 flag 的首次时间排序出来的标签，不等于服务端原始 `no`；空榜也不透露有多少题。
- 所有本地历史的 `SOPHON{` 命中只来自提交框占位符；没有 flag 值。以 Mary/Sakurai/THESHINING/House of Leaves/1997/ground station/final trials/local-sky/local-dive 搜索相关代码和文档，也未发现新增或已删除的谜面内容。

## 下一步建议

1. 不再消耗评测或提交额度去验证“重新跑一遍就会自动把 flag 放进 ZIP”；公开代码没有这条承诺，重复实验目前信息增益小。
2. 优先向主线明确两项需主办方确认的配置事实：新版 desk 是否仍接收旧 Johnny 邮件关卡；当前 Sophon 运行是否应该注入 token。旧流程和新流程并存的证据比额外正分阈值强。
3. 若允许额外只读请求，可核对旧 `sophon_solvers()` 和新榜、同身份的 `current_competition()`；本报告未自行调用。新榜为空不能代替旧名单查询。
4. 新实验若继续，应采用真正的单变量验收区别（例如最后一次曝光是否有有效目标/正分），并先本地确认条件。历史没有给出具体行星或总分门槛，不把猜测写成要求。

已经收到主线说明：`house-of-leaves`、`the-shining` 小写连字符候选也均已 422；本报告不建议重复提交。没有发送任何 flag。

## 追加：已下载公开包审计

已检查四个同名/下载包及解压后的 `card/sophon-card/`，没有发现额外 CTF 题面、真实 flag、receipt 文件名或隐藏文本。本结论限 ZIP 结构、全部文本/字段检查；不宣称排除了任意数字隐写。

| 文件 | 字节 | SHA-256 | 内容 |
|---|---:|---|---|
| `sophon-card-public.zip` | 457 | `02717723a26de8252525e7cc89d528eb460c8bec8b3591461ca856edcc085729` | 实际是 JSON `{ok,url}` 下载响应，不是 ZIP；未输出或复制 URL。 |
| `sophon-local.zip` | 437 | `4517fc0308dcc319e8da64229049bac1f2611e54f5e915b127ac00e41fd6d40c` | 同上，仅下载响应，非另一版数据。 |
| `dl_sophon-card-public.zip` | 140551 | `6a3a3abdc7127e8084259a0c02b2366f8706f2eb3059d97d58c5400ac60469c4` | 9 成员：2 目录 + 7 文件。 |
| `dl_sophon-local.zip` | 157712 | `ecb34666b2b580380d0074aaae710be6ac11570d5b78b9996855d491e441087c` | 20 成员：4 目录 + 16 文件；包括 README、checker、完整练习世界。 |

验证结果：

- 两个真实 ZIP 都没有总注释、成员注释、加密成员、前置数据或 EOCD 后附加数据。中央目录与 local headers 的 extra 都只有标准 `0x5455`（Unix 时间戳）和 `0x7875`（Unix UID/GID），文件名一致、无未知 extra 类型。
- ZIP 修改时间分别为 2026-10-05 19:39:06 UTC（真卡）与 19:36:31 UTC（练习），只是打包元数据，未发现解释为谜题的依据。
- 真卡 7 文件是 fiber/score 两配置，及 targets、footprint、night_calendar、bulletins、forecasts；解压目录的 7 个文件逐字节匹配 ZIP，无额外文件。
- 两包全部成员均为 ASCII 文本，无零宽字符/非 ASCII 字符线索。CSV 均列数正常。
- 真卡目标有 6000 个，练习 4000 个，目标 ID 连续为 `V4T000001…V4T006000` / `…V4T004000`，没有天体姓名列。除 ID 外非数值仅五类 `BGS/ELG/LRG/QSO/Star` 与 required 布尔值。
- 公告分别 1935 条、预报分别 9 条，仅普通天气/地形事件枚举、方向、时间/夜晚编号；没有自由文本 reason、note、信件、receipt 或隐藏 URL 字段。站名只是 `VISTA/Paranal (4MOST)`。
- 两包 fiber/score 配置和 60 夜夜历逐字节相同；目标/天气/足迹不同，符合 README 声明练习是另一天空。练习 `truth/v4_sophon.jsonl` 为 30 条时间/光纤表，observation_requests 文件为空。
- 仅已知 README 提到真实 ground station 检查评测并留下 receipt，没有位置/名称；仅 checker/README 出现 `SOPHON{local-*}`，明确不能提交。`--object` 无默认值，只有显式传入行星才检查 dive，README 用 Jupiter 只是示例。

逐成员哈希、标准 extra 字段、JSON 键/字符串分类、解压比对记录：`work/sophon_desk/validation/public_archive_audit.json`。没有保存下载 URL。
