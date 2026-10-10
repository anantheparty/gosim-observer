# Sophon3 私有交付记录

包目录：`work/pkgs/sophon3/`。默认 `jupiter`，修改 `probe_config.json` 的 `dive_object`
或注入 `SOPHON_DIVE_OBJECT` 可切换 `saturn / mars / venus`。未打 ZIP、未上传、未提交 flag。

## 已确认条件与未知项

| 项目 | 证据与判断 |
|---|---|
| 练习 sky | `local/check_sky.py:93–103`：glyph 夜、onset 后、glyph fibre 上 valid=true 且 score>0 的 observation 行累计 ≥3。不是三次 report，也不要求三次曝光。 |
| 引擎异常增益 | `hackathon-survey26/challenge/v4_runner.py:791–797`：另要求整段曝光 fully_open，才使用参考条件 ×2.5；练习 checker 的正分条件稍宽。新包直接记录超过正常上限的得分，额外验证真正异常。 |
| 练习 dive | `check_sky.py:104–110`：最后 observe 开始时指向距指定行星 ≤1°，且行星在地平线上。没有目标分配/得分要求。 |
| 空分配、低高度 | `challenge/v4_fiber_map.py:354–390` 允许空 assignments、中心高度 0–90°；30°限制用于目标得分。四颗行星实测均合法。 |
| 真实 flag | 实际 flag 文本、总数与 sky/dive 的真实门槛未公开。练习码不能提交；没有把它们放进探测包。 |
| receipt | 本地 README 明言真卡 ground station 会留下 receipt；公开代码没有该验收实现，不能确认具体文件或字段。两份旧 result.zip/独立结果文件都未发现真实 flag/receipt。 |
| Johnny | `hackathon-survey26/cli/AGENTS.md:177` 仅约定评测内 POST `sophon/contact-johnny`，JSON `{"token":"$SOPHON_RUN_TOKEN"}`。新包采用该请求，不添加未经文档确认的 key/answer 猜词。 |
| debug / auto | SQL `20261006000000_sophon_boards.sql` 存 board、run_id、user_id，综合分为 debug+2×auto；如何判定 auto 属于未公开服务逻辑。前端只 POST `{flag}`，无 board 参数。“评测内自动满足条件计 auto”仍是推测。 |
| F1… | 是按首次解出排序生成的显示标签，不能据此推断固定编号或 flag 总数。 |

真实公开卡和练习卡同为 Paranal、60 夜、相同夜历。公开卡公告与配置中未找到明确行星指令。
本地 README 的唯一示范选择 `jupiter`，因此作为首轮候选；这不是实际验收星体的证明。

## 文学线索

| 线索 | 可信度与用途 |
|---|---|
| THESHINING | 主会话已从真卡读出三遍。可关联 Kubrick，但“由此跳到 2001，再选择 Jupiter/Saturn”尚未得到比赛证据支持。 |
| House of Leaves、Johnny | 出版社导读明确有 Zampanò 的手稿与 Johnny Truant：支持 Johnny 名称可能沿用此书的角色，而非只有《闪灵》的台词联系。[出版社导读](https://www.penguinrandomhouse.com/books/36526/house-of-leaves-by-mark-z-danielewski/9780375703768/readers-guide?pubDate=20260610)。 |
| JAN 5 1997 | 作者网站读者论坛的书内年表，将该日标为 Zampanò 给手稿发现者/出版者的注记日期。它与 House of Leaves 有直接文本联系，比任意日期猜词更值得追踪；仍属读者整理，非比赛后端证据。[MZD 论坛年表](https://forums.markzdanielewski.com/forum/house-of-leaves/house-of-leaves-aa/3912-key-to-all-mythologies-the-introduction)。 |
| HAL 猜想 | HAL 在小说中的启用日期是 January 12, 1997，并非 January 5；不应把邮件日期直接当成 HAL 证明。[MIT 当年报道](https://news.mit.edu/1997/hal-0115)。 |
| final trials / 智子潜入 | 目前无法对应新的可验证 API、字段或具体行星。保留为后续 receipt/邮件上下文的解读线索。 |

只查询了这些公开文学资料，未向外发布比赛代码、完整私有解密文本或运行结果。

## 包行为

- 复用 sophon2 的协议入口、向量天球/光纤几何与异常得分识别思路；用轻量覆盖规划代替得分优化，900 秒曝光，优先补齐当夜未测清的 fibre。无需模型。
- 首次确定异常后开始字形投票；只有正分返回参与，零分/关闭不作为暗像素。agent 不读练习真值，不内置字母消息、glyph 夜或 onset。
- 正常走完夜历后，在配置行星仍高于地平线 1° 的末次可用时刻发出 60 秒空 assignments 曝光，随后 finish。剩余计费预算 <45 秒时改用最近可见窗口提前收尾。
- 有运行 token 且非本地 runner 时，初始化和最终曝光前各联系 Johnny 一次，最多两次；daemon 线程、8 秒 socket timeout、拒绝重定向。终止不等待慢网络。真实服务响应尚未测试。
- `SAC_LOCAL_RUNNER` 一旦存在，本地强制无网络；不输出 token 值/JWT claims；没有复制 sophon2 的公共 anon key。未知 Sophon 消息、相关额外字段及 finish payload 均记录并脱敏。

## 本地实测

使用官方 `archive/starter_kit_v4/local_runner.py`，每次上限 900 秒，四次串行；本机新增至多 runner+agent 两个进程。

| 最后行星 | 最后曝光 UTC | 行星高度 | 角距 | 异常行数 | 字形逐像素匹配 | 两个练习码 |
|---|---|---:|---:|---:|---:|---|
| Jupiter | 2026-11-30 08:13:00 | 43.685° | 0.000° | 6480 | 30/30 | 均通过 |
| Saturn | 2026-11-30 06:28:00 | 2.070° | 0.000° | 6480 | 30/30 | 均通过 |
| Mars | 2026-11-30 08:13:00 | 40.807° | 0.000° | 6480 | 30/30 | 均通过 |
| Venus | 2026-11-30 08:13:00 | 9.217° | 0.000° | 6480 | 30/30 | 均通过 |

每次输出 `SOPHON{local-sky-ok}` 和 `SOPHON{local-dive-ok}`，termination 均为 `agent_finished`；
runner 实际耗时 29.1–30.0 秒、引擎计费 4.62–4.74 秒。练习卡目标较少，不能据此断言真卡耗时相同。
得分约 397 是探测策略的副产物，本包不以正式竞赛得分为目标。
另外通过 Johnny 完全 mock 的离线门控、两次上限、请求体和日志脱敏测试，以及预算收尾/不足最小曝光时长分支测试。

完整结果：`work/sophon_desk/validation/sophon3_validation.json`；
四个运行：`work/sophon_desk/validation/sophon3_{jupiter,saturn,mars,venus}/`。
验证入口：`python3 -B work/sophon_desk/validate_sophon3.py`（仅重验产物和 mock，不重跑模拟器）。

复现默认运行：

```bash
python3 -B hackathon-survey26/archive/starter_kit_v4/local_runner.py --card work/sophon_desk/local/sophon-local --agent work/pkgs/sophon3 --wallclock 900 --out work/sophon_desk/validation/sophon3_jupiter
python3 -B work/sophon_desk/local/check_sky.py work/sophon_desk/validation/sophon3_jupiter --object jupiter
```

## 建议线上顺序

1. 先上传默认木星版，一次完整运行同时覆盖 sky、最后曝光、Johnny；检查初始化的 credential_present 和 johnny_response 状态，确认新平台是否注入 token。
2. 下载完整结果 ZIP、独立 run.json、agent_log.json，再运行下述离线扫描。不要只读旧有九个固定文件。扫描器输出 flag 和候选位置，不输出凭证值；超过 32 MiB 的 ZIP 成员显式标记跳过。
3. 如果收到 sky receipt 而无 dive，根据回执文字调整；没有新提示时先试 Saturn，再 Mars/Venus。一个最后曝光只能针对一颗星体，不能在同一运行同时满足四个不同最后指向。
4. 若出现实际 flag，由主会话提交并观察 debug/auto 归属。未确认前不要臆造 flag 字符串，也不要把 `{key: ...}` 猜词扩展当成已有协议。

```bash
python3 -B work/sophon_desk/scan_receipts.py work/online/NEW_RUN --out work/sophon_desk/validation/NEW_RUN_receipts.json
```

扫描覆盖目录中的 JSON/JSONL/log/txt/csv 等文本及 ZIP 全部成员，识别实际 `SOPHON{...}`、
receipt/sophon/flag 等字段与文件名；重点人工复核 `workflow_result.json`、`score_report.json`、
`messages.jsonl`、`agent.log`、新增文件以及独立 run.json 的 score_summary/score_check。

未读凭证文件，未调用模型/比赛平台，未改 c3*、现有仿真目录，未 commit/push/upload。
